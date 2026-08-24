# FirstGreen 技术实现规格（Codex 可直接执行）

本文件把主 PRD 转换为工程约束、接口、算法和首轮实现顺序。冲突时，以 `01_PRODUCT_PLAN_AND_PRD.md` 的产品边界为准；以本文件的技术接口为实现基线。

## 1. 运行模式

MVP 支持两种模式：

1. **One-shot CLI**：`firstgreen run fleet.yaml` 在前台运行直至所有任务终态。
2. **Local daemon（同一代码路径）**：后续可由 `firstgreen daemon` 常驻。第一轮可先完成 one-shot，但 domain/service 层不得依赖 CLI 进程生命周期。

所有时间读取通过注入的 `Clock`，所有持久化通过 repository interface，所有 worker 通过 adapter interface。

## 2. 最小领域接口

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class StartAttemptRequest:
    run_id: str
    task_id: str
    attempt_id: str
    prompt: str
    worktree: Path
    timeout_seconds: int
    adapter_config: dict[str, Any]


@dataclass(frozen=True)
class AttemptHandle:
    adapter: str
    external_id: str
    pid: int | None


@dataclass(frozen=True)
class WorkerEvent:
    type: str
    timestamp: datetime
    payload: dict[str, Any]
    raw: str | None = None


class WorkerAdapter(Protocol):
    async def doctor(self) -> "DoctorResult": ...
    async def start(self, request: StartAttemptRequest) -> AttemptHandle: ...
    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]: ...
    async def cancel(self, handle: AttemptHandle, reason: str) -> "CancelResult": ...
    async def inspect(self, handle: AttemptHandle) -> "AttemptStatus": ...
```

```python
class WorkspaceManager(Protocol):
    async def create_attempt_workspace(self, spec: "WorkspaceSpec") -> "Workspace": ...
    async def inspect(self, workspace_id: str) -> "WorkspaceStatus": ...
    async def cleanup(self, workspace_id: str, *, dry_run: bool = False) -> None: ...
```

```python
class Verifier(Protocol):
    async def verify(self, request: "VerificationRequest") -> "VerificationResult": ...
```

## 3. 数据库要求

最低表：

- `schema_migrations`
- `runs`
- `tasks`
- `task_dependencies`
- `attempts`
- `verification_runs`
- `events`
- `scheduler_decisions`
- `resource_leases`
- `runtime_samples`

关键约束：

- `tasks(run_id, task_key)` unique；
- `attempts(task_id, ordinal)` unique；
- `tasks.winner_attempt_id` nullable FK；
- winner compare-and-set 必须在事务中；
- 可额外建 `task_winners(task_id PRIMARY KEY, attempt_id UNIQUE)` 简化唯一性；
- timestamps 使用 UTC；
- SQLite WAL 和 foreign keys 开启；
- 大 stdout/stderr/raw event 可写 artifact 文件，DB 存路径、hash 和摘要。

## 4. 状态迁移

使用集中式函数：

```python
transition_attempt(attempt_id, expected_statuses, new_status, metadata)
transition_task(task_id, expected_statuses, new_status, metadata)
```

禁止业务模块直接 `UPDATE status`。非法迁移抛 domain error，记录 event。

## 5. Codex Exec adapter

建议命令构造：

```text
codex exec --json \
  --sandbox workspace-write \
  -c agents.max_threads=<n> \
  <prompt>
```

具体 CLI 参数必须在实现机器上通过 `codex exec --help` 和官方文档再次确认，不要凭记忆硬编码。

实现细节：

- 使用 `asyncio.create_subprocess_exec`，不拼 shell 字符串；
- 用 subprocess 的 `cwd=<worktree>` 指定工作目录；不要依赖未经本机 `--help` 验证的目录 flag；
- 代码编辑任务显式传 `--sandbox workspace-write`；`danger-full-access` 只能由用户在隔离环境中显式 opt-in；
- POSIX 下创建新 process group/session；
- stdout、stderr 并行读取，防止管道阻塞；
- stdout 每行尝试 JSON parse；失败则作为 `worker.raw_event` 保留；
- 事件进入 artifact 前经过 privacy filter；默认不保存 reasoning、prompt、agent-message 的完整 payload；
- 解析器使用 tolerant mapping，未知字段忽略但保留经过过滤的 envelope/raw；
- `capture_sensitive_events=true` 只能显式开启，并且仍不得记录 credentials；
- task prompt 作为单独 argv 或 stdin 的方式以官方 CLI 实测为准；
- 进程退出后发出 completed/failed；
- cancel：SIGTERM process group，等待 grace period，仍存活则 SIGKILL；
- cancellation 之后继续消费剩余 pipe 直到 EOF 或 timeout；
- 不把 stderr 默认视为失败，最终以 exit code 和事件为准。

## 6. Worktree safety

创建步骤：

1. `git rev-parse <base_ref>` 得到 SHA；
2. 验证 repo root；
3. 为 attempt 生成无用户可控路径穿越的 slug；
4. 在产品专属根目录创建；
5. `git worktree add -b <branch> <path> <base_sha>`；
6. 写入 `.firstgreen-attempt.json` marker，含 run/task/attempt/repo/base；
7. DB 写 workspace record。

删除步骤：

- 读取 DB 和 marker 双重确认；
- 确认 path 在 configured workspace root 下；
- 确认不是 repo main worktree；
- winner 默认不删；
- 使用 `git worktree remove`，必要时 prune；
- 失败时标记 cleanup_pending，不递归暴力删除未知路径。

## 7. Verifier runner

- command 配置可以是 argv list 或显式 shell string；默认推荐 argv list；
- 如果允许 shell，配置必须显式 `shell: true`；
- cwd 固定 attempt worktree；
- 每个 command 有 timeout 和 output cap；
- verifier 运行期间占用独立 semaphore；
- command logs 写 artifact；
- changed paths 使用 `git diff --name-only <base_sha>...HEAD` 和 working tree 状态组合；
- MVP 可以接受 Agent 未 commit 的修改；
- verifier pass 后计算 diff hash，以便审计 winner 内容。

## 8. Winner transaction

SQL 语义：

```sql
UPDATE tasks
SET winner_attempt_id = :attempt_id,
    status = 'verified',
    verified_at = :now
WHERE id = :task_id
  AND winner_attempt_id IS NULL
  AND status NOT IN ('cancelled', 'blocked');
```

受影响行数为 1 则 winner；否则 superseded。随后在事务外异步取消其他 attempts。任何 cancellation failure 不回滚 winner。

## 9. Hedge policy v1

```python
@dataclass(frozen=True)
class HedgeDecision:
    launch: bool
    reason: str
    threshold_seconds: float | None
    threshold_source: str
    sample_count: int
    estimated_extra_cost: float | None
```

逻辑顺序：

1. task replay-safe？
2. hedge enabled？
3. winner absent？
4. active primary exists？
5. replicas < max？
6. budget available？
7. slots/resources available？
8. controller not in backoff？
9. threshold available？
10. elapsed >= threshold？

每个 false 都返回显式 reason，按采样频率去重记录，避免日志爆炸。

Runtime bucket key 单独实现，不散落在 scheduler：

```text
(repo_fingerprint, task_class, adapter, model, verifier_profile)
```

历史样本需要记录是否 success、failed、cancelled、censored。v1 quantile 可先只使用非 cancelled 的 terminal attempts，并在报告中说明局限。

## 10. Concurrency controller v1

```python
@dataclass
class ConcurrencyState:
    current_root: int
    min_root: int
    max_root: int
    last_change_at: datetime
    pressure_windows: int
    healthy_windows: int
```

Pressure signals：

- recent provider retryable/rate-limit errors > threshold；
- verifier queue wait > threshold；
- memory > configured percentage；
- load average normalized > threshold；
- cancellation backlog > threshold；
- process spawn/worktree failures > threshold。

Healthy：

- backlog exists；
- no pressure；
- minimum completed samples in window；
- cooldown elapsed。

Action：

- pressure：`max(min_root, floor(current_root / 2))`；
- healthy：`min(max_root, current_root + 1)`；
- otherwise hold。

Nested budget admission：

```python
requested_threads = task.max_subagent_threads
if (active_root_thread_caps + requested_threads) > total_agent_thread_budget:
    deny_or_reduce_requested_threads()
```

若允许动态降低某个 root 的 `agents.max_threads`，必须在 attempt config snapshot 中记录实际值。

## 11. CLI 最小合同

```text
firstgreen doctor
firstgreen init [PATH]
firstgreen validate MANIFEST
firstgreen run MANIFEST [--policy POLICY] [--dry-run]
firstgreen status [RUN_ID] [--watch]
firstgreen cancel RUN_ID [--task TASK_ID]
firstgreen report RUN_ID [--open]
firstgreen export RUN_ID --format json|csv
firstgreen benchmark simulate CONFIG
```

退出码：

- 0：命令成功；
- 2：配置/用法错误；
- 3：环境/doctor 错误；
- 4：run 完成但有未 green tasks；
- 5：内部错误。

## 12. 测试策略

### Unit

- state transitions；
- quantile；
- bucket fallback；
- hedge gates；
- AIMD；
- budget；
- path safety；
- event parser tolerance。

### Integration

- fake worker + real SQLite；
- real temporary git repo/worktrees；
- concurrent verifier pass race；
- process cancellation；
- restart reconciliation；
- malformed JSONL；
- stdout/stderr pressure。

### Property/fault injection

- 任意事件顺序不产生两个 winners；
- cleanup 永不越界；
- duplicate event 幂等；
- crash at every transition point 后可恢复；
- cancellation race 不改变已确定 winner。

### Real Codex smoke

必须由环境变量或 marker 显式启用，CI 默认跳过，避免费用：

```text
FIRSTGREEN_RUN_LIVE_CODEX_TESTS=1
```

## 13. 首轮实现顺序

1. 创建 repo、质量工具、ADRs；
2. domain models + state machine；
3. SQLite repository；
4. fake worker + simulator；
5. static scheduler；
6. worktree manager；
7. Codex Exec adapter；
8. verifier；
9. atomic winner/cancellation；
10. delayed hedge；
11. adaptive concurrency；
12. reports；
13. live benchmark；
14. packaging/docs。

不要把 7 提前到 2；先用 fake worker 把竞态和恢复做对。

## 14. Definition of Done

一个任务只有在以下全部满足时才算实现完成：

- 有 unit tests；
- 有必要的 integration tests；
- typecheck、Ruff、pytest 通过；
- error path 有用户可理解的信息；
- state change 和 decision 可观察；
- 文档/示例更新；
- 没有绕过安全 invariant；
- 不引入超出当前 milestone 的依赖或 UI。

## 15. Planning subsystem contract

Planning 与 execution 是两个状态域。只读 scanner 输出带 commit SHA/version 的 bounded
`RepositoryMap`；deterministic classifier 先决定 single/decompose；`PlannerAdapter` 最多提出
1–5 个 semantic work units，不能决定最终 edges、locks、risk 或 approval。

`compile_plan()` 依据 artifact produces/requires 建边，把 write overlap 表示为独立
`exclusive_write` constraints，并对人工边界造成的 cycle/高重叠做 deterministic merge。
`validate_plan()` 检查 DAG、artifact、verifier、path allow/deny、conflict representation 和大小。
失败时至多做确定性修复并安全回退 single task，不启动无界 LLM repair loop。

Approved plan 编译成既有 `Manifest`，冲突变成 capacity=1 resource keys；scheduler 的 keyed
semaphore 负责强制串行。Retries/hedges 使用相同 manifest 和 pinned plan cache key。CLI 增加
`scan`、`plan`、`validate-plan` 以及 `run ISSUE --plan none|auto`。Planning state、repo map、
candidate/approved plan、validation、tokens/cost/latency 独立持久化和报告。
