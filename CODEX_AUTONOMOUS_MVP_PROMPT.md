# 可直接粘贴给 Codex 的自主 MVP 构建指令

你现在要在当前目录实现 **FirstGreen（开发代号）**。这是一项真实工程任务，不是只生成示例代码或设计稿。

先完整阅读：

- `01_PRODUCT_PLAN_AND_PRD.md`
- `02_TECHNICAL_SPEC.md`
- `03_IMPLEMENTATION_BACKLOG.md`
- `AGENTS.md`
- `examples/fleet.yaml`

## 目标

按 `03_IMPLEMENTATION_BACKLOG.md` 的依赖顺序，逐批完成可运行 MVP。每个 Batch 都必须独立通过测试后才能进入下一 Batch。不要把所有模块先写成空壳，也不要为了展示效果跳过状态机、事务、验证或 workspace safety。

优先完成的可用纵切面是：

```text
manifest -> static scheduler -> isolated worktree -> Codex Exec worker
         -> deterministic verifier -> atomic winner -> report
```

随后再加入：

```text
delayed hedge -> first verified wins -> loser cancellation
              -> adaptive concurrency -> policy comparison
```

## 自主工作规则

1. 先输出你对产品边界、主要风险和实施顺序的理解，然后直接实施，不等待确认。
2. 一次只处理一个 Batch；每个 Batch 完成后：
   - 运行 Ruff format/check；
   - 运行 typecheck；
   - 运行 unit/integration tests；
   - 更新 backlog 勾选状态和已知限制；
   - 输出简短 checkpoint，再继续下一 Batch。
3. 如果当前环境没有真实 Codex CLI、认证或不适合产生 API 费用：
   - 不要停工；
   - 完成 fake adapter、simulator、Codex command builder 和 opt-in live tests；
   - 将真实 smoke test 标为环境阻塞，不伪造通过结果。
4. 对外部 Codex CLI 参数，先执行本机 `codex exec --help` 并对照官方文档；不要靠记忆猜测。
5. 编辑型任务使用最小权限 `--sandbox workspace-write`；不要默认 `danger-full-access`。
6. 默认过滤 reasoning、prompt、agent message 和 secrets 等敏感 event payload；不得依赖或存储隐藏 chain-of-thought。
7. 不做自动 merge、push、deploy 或不可逆外部操作。
8. 不增加 SaaS、React、Kubernetes、GitHub App、remote runner、多供应商 adapter、LLM planner 或 ML scheduler。
9. 若发现规格存在实现矛盾：
   - 优先满足 `AGENTS.md` 的 invariants；
   - 记录 ADR；
   - 采用最小、安全、可逆方案；
   - 继续实现，不要用无关问题阻塞整个项目。
10. 对需要用户凭据、付费 API 或危险 shell 权限的步骤，保留明确 opt-in，不伪造执行。

## Repository-aware planning extension

在完整 DAG scheduler 前按 P0–P8 实现 planning subsystem：planning schemas → read-only repo
scanner → deterministic decomposition → fake/structured planner → DAG compiler/conflicts →
validation/merge/fallback → terminal approval/YAML edit → scheduler integration → metrics/report。
LLM 只提出 semantic work units；最终 DAG、路径、风险、locks、批准和执行资格必须由确定性代码
决定。MVP depth=1、tasks<=5、默认每 issue 最多一次 planner call，普通 retries/hedges 复用
approved plan。Planning failure 安全回退 single task 或等待用户，不能无界重试。

## 必须守住的正确性条件

- Task 最多一个 winner，数据库事务保证。
- Agent 自报完成永远不能绕过 verifier。
- `replay_safe=false` 时绝不 hedge。
- Primary 和 backup 从同一个 base SHA、不同 worktree 启动。
- Winner worktree 不被 loser cleanup 删除。
- 所有 cleanup 路径都在专属 workspace root 内并具备 marker 双重确认。
- 所有自动并发和 hedge 决策有 hard limits、static fallback、policy snapshot 和 decision log。
- 未知 JSONL event 不使 scheduler 崩溃；敏感 payload 默认过滤。
- Live Codex tests 默认在 CI 跳过，并由显式环境变量开启。

## 完成定义

当且仅当以下条件满足，才可以称为 MVP：

- `doctor/init/validate/run/status/cancel/report/export/benchmark simulate` 可用；
- fake workload 可重复运行；
- 真实 Codex adapter 已实现，或仅真实认证 smoke test 被明确标为环境阻塞；
- worktree 隔离、deterministic verifier、winner arbitration、delayed hedge 和 adaptive concurrency 均有测试；
- static HTML/JSON/CSV report 可生成；
- single、always-race、delayed-hedge、auto policies 可在 simulator 中比较；
- macOS/Linux 的非 live CI 全绿；
- README 清楚说明安装、快速开始、安全边界和已知限制。

## 最终输出

- 实现摘要和项目树；
- 各 Batch 完成情况；
- 所有测试/检查命令和真实结果；
- 未运行的 live tests 及原因；
- 已知风险和下一步建议；
- 一个可以复制运行的 fake demo 命令；
- 一个需要用户已有 Codex 认证才能运行的 live demo 命令。
