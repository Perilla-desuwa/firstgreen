# FirstGreen（暂定代号）完整产品企划书与 PRD

> **一句话定位**：一个 repository-aware 系统，把 issue 转成可验证执行计划，再动态调度 coding agents，以降低 **time-to-verified-result** 和 **cost-per-verified-result**。
> **核心主张**：Codex 负责执行和任务内并行；FirstGreen 决定开几个、何时启动备份、谁先停，以及什么结果才算完成。  
> **文档用途**：可直接作为产品立项、工程实现、开源发布和首轮验证的主规格。  
> **状态**：Implementation-ready draft  
> **版本**：v0.1  
> **日期**：2026-07-12  
> **说明**：FirstGreen 仅为开发代号。公开发布前必须重新检查名称、商标、PyPI 包名、GitHub 组织名和域名。

---

## 1. 执行摘要

Coding agent 已经具备并行能力：Codex 可以在单次任务中生成 subagents，也可以通过 CLI、SDK 或 App Server 被外部程序启动和观察；OpenAI Symphony 已经把 issue tracker、隔离 workspace、并发上限、stall 检测和 retry 组织成一个常驻执行系统。与此同时，Bernstein、Agent Orchestrator、Tutti、GitHub Agent HQ 等项目也覆盖了多 Agent、worktree、质量门、供应商适配或统一控制台。

因此，FirstGreen **不做**以下已经拥挤的产品：

- 又一个可以同时打开多个 Codex 会话的界面；
- 又一个通用多 Agent 框架；
- 又一个仅显示 token、日志和 waterfall 的 profiler；
- 又一个从一开始固定启动 N 个候选、最后选优的 tournament runner；
- 又一个只会给任务配置固定 `max_concurrency` 的队列。

FirstGreen 的产品楔子是一个闭环优化器：

1. **Scheduler-owned verification contract**：Agent 自报“完成”不算成功，确定性 verifier 通过才算 green。
2. **Delayed hedging**：正常只跑一个 primary；仅当任务进入长尾时，才启动隔离的 backup attempt。
3. **First verified wins**：第一个通过 verifier 的 attempt 原子获胜，其余立即取消。
4. **Adaptive fleet concurrency**：在 root runs、Codex 内部 subagents、测试槽位、主机负载、供应商限流之间做全局 admission control，避免嵌套并行导致 oversubscription。
5. **Scaling profiler / autotuner**：跨运行学习某个 repo、任务类型和模型组合的耗时、成功率与成本，推荐并发度、hedge 阈值和 worker 策略。

新增的上游 planning layer 解决用户必须手写完整 DAG 的产品缺口。它只接受 issue-sized
engineering task，不接受模糊产品愿景或多月 roadmap。Repository scanner 只读生成有界 repo
map；确定性分类器允许“有效并行度 1”成为成功结果；需要语义拆分时默认至多一次 planner
调用；最终 edges、冲突、风险、资源、验证资格和批准全部由确定性软件决定。LLM proposal
永远不是 approved execution plan。

North-star objective：

\[
\min \; P95(T_{verified})
\]

约束为：

\[
\text{cost} \le B,\quad
\text{verification pass}=true,\quad
\text{safety policy}=true
\]

第一版采用 **Codex-first、local-first、CLI-first** 路线：使用 `codex exec --json` 作为最小可用 adapter；每个 attempt 在独立 git worktree 中执行；SQLite 持久化状态；确定性命令负责验证；生成本地 HTML/JSON 报告。随后再增加 Codex App Server adapter、远程 runner、多供应商 adapter 和团队控制面。

---

## 2. 产品愿景与产品论点

### 2.1 愿景

让 coding-agent fleet 像成熟的计算集群一样可调度、可验证、可复现、可比较，而不是“多开几个窗口然后祈祷”。

### 2.2 核心论点

Agent runtime 和 fleet scheduler 是两个不同层级：

- Codex 内部负责理解任务、调用工具、生成代码和按需使用 subagents；
- FirstGreen 外部负责工作队列、资源分配、重试、复制、验证、取消、预算和历史学习。

这个边界允许 FirstGreen 在不读取隐藏推理、不修改 Codex 内部实现、也不控制服务端 token scheduler 的前提下，仍然优化业务真正关心的结果：**多久得到一个经过验证、可以交付的变更**。

### 2.3 为什么现在适合做

- coding agent 的程序化接口已经足够：机器可读事件、线程生命周期、取消、恢复、配置覆盖和 OpenTelemetry 正在形成可用基础；
- 原生产品更关注单次交互体验和执行能力，跨任务 fleet-level policy 仍有空间；
- coding task latency 天然有长尾：环境安装、测试、错误路径、工具失败和探索分支会造成大幅波动；
- 多 Agent 并发既可能提升吞吐，也会放大 API 限流、测试争用、文件冲突和成本；
- 团队需要的不是“最大并行度”，而是“在预算和质量约束下的最佳并行度”。

---

## 3. 术语与核心指标

### 3.1 术语

- **Task**：用户希望完成的业务任务，例如修复一个 issue。
- **Attempt**：某个 Agent 对 Task 的一次独立执行。
- **Primary**：Task 的首个 Attempt。
- **Hedge / Backup Attempt**：Primary 进入长尾后启动的额外 Attempt。
- **Verifier**：由 scheduler 控制的确定性验证过程，例如测试、lint、类型检查和路径约束。
- **Green**：Attempt 完成并通过所有必需验证。
- **Winner**：第一个通过 verifier 并成功取得原子 winner lease 的 Attempt。
- **Fleet**：同一 FirstGreen 实例管理的所有 Agent runs、verifiers 和 workspaces。
- **Root concurrency**：外层同时运行的 Task Attempts 数量。
- **Nested concurrency**：每个 Codex root run 内部可生成的 subagent 数量。
- **Replay-safe**：从相同输入重新运行不会产生不可逆外部副作用的任务。

### 3.2 必须报告的指标

- `time_to_verified_result`：任务提交到 winner 验证通过的 wall-clock 时间；
- `p50/p90/p95 time_to_verified_result`；
- `verified_tasks_per_hour`；
- `tokens_per_verified_task`；
- `estimated_cost_per_verified_task`；
- `queue_wait_seconds`；
- `agent_runtime_seconds`；
- `verification_runtime_seconds`；
- `hedge_launch_rate`；
- `hedge_win_rate`；
- `wasted_attempt_seconds` 和可获得时的 `wasted_tokens`；
- `cancellation_lag_seconds`；
- `rate_limit_event_count`；
- `root_slot_utilization`；
- `verifier_slot_utilization`；
- `nested_parallelism_estimate`；
- `agent_self_reported_done_but_verifier_failed_rate`。

### 3.3 成本口径

不同认证方式或订阅方案未必能提供精确的逐任务美元成本。产品必须区分：

- **原始 token usage**：可从事件获得时记录；
- **估算费用**：由用户配置 price table 计算，明确标注 estimated；
- **实际账单费用**：仅当供应商提供可靠账单数据时使用；
- **本地资源成本**：第一版记录运行时间和可选 CPU/内存，不强行换算美元。

---

## 4. 目标用户、场景与 Jobs-to-be-Done

### 4.1 Primary persona：高频 coding-agent 用户

特征：

- 同时维护一个或多个 Git 仓库；
- 已经在使用 Codex CLI/App/SDK；
- 每周有一批 issue、重构、测试修复、升级或维护任务；
- 会同时启动多个 Agent，但缺少系统化并发策略；
- 关注等待时间、成功率和 token/预算。

核心 JTBD：

> 当我有一批可验证的 coding tasks 时，帮我在不盲目双倍烧钱的情况下，尽快得到通过测试的结果，并留下完整证据。

### 4.2 Secondary persona：AI developer tooling / platform 团队

核心 JTBD：

> 当团队升级模型、prompt、workflow 或并发配置时，帮我比较 time-to-green、成本和质量回归，并给出 fleet 配置建议。

### 4.3 Later persona：企业内部 Agent 平台团队

核心 JTBD：

> 在客户 VPC 或自托管环境中，把不同 coding agents 作为 worker，统一执行策略、预算、审计、权限和容量规划。

### 4.4 非目标用户

第一版不服务：

- 只进行单次结对编程、没有批量任务需求的用户；
- 需要 token-level/GPU-level inference scheduling 的模型服务商；
- 需要跨供应商迁移“运行到一半的隐藏内部状态”的场景；
- 需要自动向生产环境执行不可逆操作的 Agent；
- 只想要一个多聊天窗口 UI 的用户；
- 无法提供确定性或半确定性验收条件的开放式创作任务。

---

## 5. 定位、品类与信息架构

### 5.1 品类定义

**Verified coding-agent fleet scheduler**  
中文可称：**可验证的 coding-agent 集群调度器**。

### 5.2 核心定位语

> Codex gives you parallelism. FirstGreen decides when parallelism is worth paying for.

中文：

> Codex 负责并行；FirstGreen 负责决定开几个、何时加备份、谁先停，以及什么才算完成。

### 5.3 结果导向话术

- “降低 coding agents 的 P95 time-to-green。”
- “只在任务真的进入长尾时，才为第二次尝试付费。”
- “第一个通过测试的结果获胜，不是第一个说自己完成的 Agent 获胜。”
- “自动寻找当前 repo、账户和测试环境的合理并发度。”

### 5.4 不应使用的主宣传语

- “支持多个 Codex 并行”；原生和竞品已经支持。
- “用 worktree 隔离 Agent”；这是基础设施，不是独特卖点。
- “支持质量门”；已有多个项目具备。
- “多模型统一控制台”；GitHub、Agent Orchestrator 等正在做。
- “AI 自动调度 AI”；过于模糊，无法体现可验证优势。

---

## 6. 市场与竞品现状

> 以下比较基于 2026-07-12 可见的公开文档和仓库。供应商功能变化很快，正式发布前应重新核验。

### 6.1 Codex 原生 subagents

公开能力包括：

- 在单个任务中生成多个 specialized subagents；
- 并行执行独立工作并收集结果；
- 配置最大线程数、嵌套深度和 worker runtime；
- 通过 CLI、SDK 或 App Server 启动和观察运行；
- 使用 worktree 处理并行任务。

原生强项：

- 与 Codex 上下文和工具循环深度集成；
- 适合单次任务内部的读、分析和探索型并行；
- 用户无需维护额外 scheduler。

公开文档可见的产品缝隙：

- subagent 并行主要属于单个 root run 的内部策略；
- write-heavy 并行存在冲突和协调开销；
- 固定线程上限不能解决多个 root runs 的全局 oversubscription；
- 不以跨任务历史数据优化 P95 time-to-verified-result；
- 不提供基于历史分位数的 delayed hedge policy；
- 不以 scheduler-owned deterministic verification 定义 fleet winner。

### 6.2 OpenAI Symphony

Symphony 是最接近 FirstGreen 的官方参照：它把 issue tracker、WORKFLOW policy、隔离 workspace、Codex session、固定并发限制、stall 终止、retry 和 observability 组合成常驻执行系统。

值得复用的设计：

- issue/task lifecycle；
- workspace lifecycle；
- Codex 集成方式；
- retry 和 reconciliation；
- 配置文件与运行状态分离；
- token/runtime/rate-limit telemetry。

FirstGreen 与其公开规格的差异化：

- Symphony 主要使用固定 global/per-state concurrency；FirstGreen 增加闭环自适应控制；
- Symphony stall 后 kill/retry；FirstGreen 在 tail threshold 到达时并行启动 backup，避免先等死再重跑；
- Symphony 不把 “first verifier pass wins” 作为 fleet-level primitive；
- Symphony 不以 policy comparison 和 scaling autotuning 为核心输出。

产品策略：第一版可以借鉴其生命周期和 adapter 模式，但不要把项目绑定到其内部实现；保持独立的 normalized worker contract。

### 6.3 Bernstein

Bernstein 已经覆盖：

- 多种 coding-agent CLI adapters；
- deterministic scheduler；
- git worktrees；
- quality gates；
- budgets；
- web UI、审计和 tournament；
- 从任务开始就 fan-out 多个 attempts，再用 evaluator 选胜者。

因此 FirstGreen 不能把 “multi-attempt + evaluator” 当作独特卖点。真正差异应表述为：

- **selective redundancy**：默认一个 primary，仅为长尾任务启动 backup；
- **first verified wins**：无需等待全部候选；
- **online concurrency autotuning**：根据实际 fleet 压力调节，而不是仅提供配置项；
- **scaling report**：比较 native、always-race、delayed hedge 和 auto policy 的成本—延迟 frontier。

### 6.4 Agent Orchestrator / Tutti / 同类工具

这些项目通常擅长：

- 跨供应商适配；
- worktree/session 生命周期；
- PR、CI、review 和 merge conflict 反馈；
- declarative workflow、角色、审批、审计与 dashboard。

FirstGreen 不与它们比 adapter 数量或 UI 丰富度。第一版聚焦 **调度策略是否能量化降低 tail latency，同时控制额外成本**。

### 6.5 GitHub Agent HQ / 原厂 mission control

原厂平台拥有天然分发、身份、仓库和 UI 优势。FirstGreen 不应赌“统一入口”会成为长期护城河，而应建立：

- 可独立复现的 benchmark protocol；
- repo-specific performance history；
- 可解释的 scheduling decisions；
- 多版本、跨模型的 time-to-green regression 数据；
- 可作为原厂之上的 policy layer 或本地工具运行的能力。

### 6.6 竞争矩阵

| 能力 | Codex 原生 subagents | Symphony | Bernstein | Agent Orchestrator / Tutti | FirstGreen MVP |
|---|---:|---:|---:|---:|---:|
| 单任务内部 subagent 并行 | 强 | 依赖 Codex | 依赖 worker | 依赖 worker | 依赖 Codex |
| 外部任务队列 / fleet | 有限 | 是 | 是 | 是 | 是 |
| Git worktree 隔离 | 可用 | 是 | 是 | 是 | 是 |
| Deterministic verification | 可由用户执行 | 可配置工作流 | 是 | 是 | **核心状态机** |
| 从开始固定多路竞赛 | 可手动 | 非核心 | 是 | 部分 | baseline only |
| Delayed hedge | 未见公开核心能力 | 未见公开规格 | 未见其核心策略 | 未见核心策略 | **核心** |
| First verified wins + cancel loser | 未见 fleet primitive | 未见公开规格 | 以 tournament/evaluator 为主 | 非核心 | **核心** |
| Adaptive fleet concurrency | 固定/局部配置 | 固定全局/状态限制 | 有调度但非本产品定位 | 非核心 | **核心** |
| Scaling profiler / policy comparison | 非核心 | observability | 部分指标 | observability | **核心** |
| 多供应商 | 否 | Codex-first | 强 | 强 | 后续 |
| 团队控制台 / 审计 | 原厂能力 | 基础 | 是 | 强 | 后续 |

### 6.7 竞争结论

第一版的可防守性不是某个单独 feature flag。Delayed hedging、auto concurrency 和 verification 都可能被原厂快速复制。长期资产应是：

1. repo/task-class 级别的历史分布和成功率；
2. 可解释的 scheduling policy 数据；
3. benchmark 与报告格式；
4. verifier 模板和 replay-safety policy；
5. 跨 Codex 版本、模型和配置的性能回归库；
6. 与团队工作流、CI 和远程 runner 的深度集成。

---

## 7. 产品原则

1. **Verified over declared**：Agent 的文字声明不是完成条件。
2. **Selective over maximal parallelism**：默认不复制，只在有证据时增加并行。
3. **Global over local optimization**：root runs、subagents、verifiers 和主机资源必须统一看待。
4. **Explain every decision**：每次 admission、hedge、cancel、backoff 都要留下原因。
5. **Local-first and reversible**：源码和凭据默认留在用户机器；MVP 不自动 merge。
6. **Deterministic core, probabilistic workers**：状态机、锁、预算和验证由确定性程序维护。
7. **Measure before claiming**：发布文案只使用 benchmark 实测结果，不预设“必然更快”。
8. **No hidden credential tricks**：使用正式程序化认证，不依赖抓取个人订阅凭据。
9. **Safe duplication only**：只有明确标记 replay-safe 的任务允许 hedge。
10. **Adapters are replaceable**：产品价值不绑死在某个 Agent 的私有内部状态。

---

## 8. MVP 范围

### 8.1 MVP 必须包含

- 单机、local-first daemon/CLI；
- macOS、Linux；Windows 通过 WSL2 best-effort；
- Codex CLI adapter：`codex exec --json`；
- Generic fake/simulation adapter，用于无 API 成本测试；
- Git worktree workspace isolation；
- YAML task manifest；
- 简单 DAG dependencies；
- 静态并发模式；
- 自适应 root concurrency 模式；
- 每 run 配置 Codex `agents.max_threads`，限制嵌套并发；
- deterministic verifier commands；
- primary + 最多一个 delayed backup；
- first-verified-wins；
- loser process cancellation；
- SQLite 持久化；
- crash/restart reconciliation；
- JSONL event log；
- JSON、CSV、静态 HTML 报告；
- policy benchmark：single、always-race、delayed-hedge、auto；
- `doctor`、`validate`、`run`、`status`、`cancel`、`report`、`benchmark` 命令。

### 8.2 MVP 明确不做

- 自动合并到 main；
- 自动推送 PR；
- SaaS 多租户；
- WebSocket 实时复杂 dashboard；
- 多供应商深度 adapter；
- 跨主机 remote execution；
- Kubernetes；
- 模型 token/KV/GPU 调度；
- 读取或存储隐藏 chain-of-thought；
- 运行中跨供应商迁移上下文；
- LLM 自动生成安全策略；
- 复杂 reinforcement learning scheduler；
- symbol-level 冲突预测；
- 不可逆外部副作用任务的 hedging。

### 8.3 MVP 发布门槛

产品必须能通过一个可复现 benchmark 展示：

- 在人为构造或真实观测的 heavy-tail workload 下，delayed hedge 相比 single-attempt 降低 P95 time-to-green；
- 相比 always-race，delayed hedge 使用更少额外 attempt-time/token；
- auto concurrency 在至少一个受限环境中避免固定高并发导致的吞吐或失败恶化；
- 所有结果包含置信区间或重复试验，不只展示单次案例；
- 没有数据就不宣称“节省 X%”。

---

## 9. 核心用户流程

### 9.1 首次安装

```bash
uv tool install firstgreen   # 暂定命令，发布前检查包名
firstgreen doctor
firstgreen init
```

`doctor` 检查：

- Python 版本；
- Git 版本和仓库状态；
- Codex CLI 是否存在、版本和登录状态；
- 是否可以运行 `codex exec --json`；
- worktree 创建权限；
- SQLite 可写目录；
- 可选价格表和默认模型配置；
- verifier command 环境依赖。

### 9.2 运行一批任务

```bash
firstgreen validate fleet.yaml
firstgreen run fleet.yaml
firstgreen status --watch
```

系统行为：

1. 固定 base commit SHA；
2. 检查 DAG 和 resource keys；
3. 将 ready tasks 放入队列；
4. 根据 policy 申请 root slot；
5. 为 primary 创建 worktree；
6. 启动 Codex subprocess，持续读取 JSONL；
7. 如果 primary 完成，进入 verifier；
8. 如果 primary 超过 hedge threshold 且满足条件，启动 backup worktree；
9. 任一 attempt 通过 verifier 后原子 claim winner；
10. 取消其余 attempts；
11. 释放资源并解锁依赖任务；
12. 写入 metrics 和 decision log。

### 9.3 查看结果

```bash
firstgreen report <run-id> --open
firstgreen export <run-id> --format json
```

报告首页展示：

- verified / failed / cancelled task 数；
- P50/P95 time-to-green；
- verified tasks/hour；
- token/cost estimate；
- hedge launch/win rate；
- wasted attempt time；
- current/recommended concurrency；
- 每个 task 的 timeline；
- 每次调度决策及原因；
- winner worktree、branch、diff summary、verifier logs。

### 9.4 保留结果

MVP 中，winner 保留为独立 branch/worktree，由用户手动 review、cherry-pick、commit、push 或创建 PR。失败或 loser worktree 的清理策略可配置：立即清理、保留 N 小时或永远保留。

---

## 10. 功能需求

### FR-1：任务清单与 DAG

- YAML schema 有版本号；
- task id 在 run 内唯一；
- 支持 `dependencies`；
- 提交时检测环；
- 依赖未 green 的任务不可进入 ready；
- 依赖失败时，后续任务进入 blocked，除非配置 `continue_on_failure`；
- base commit 在 run 创建时解析并固定为 SHA。

### FR-2：Workspace 管理

- 每个 Attempt 使用独立 worktree 和 branch；
- 目录结构可预测、可恢复；
- 不能直接修改主工作目录；
- attempt 的工作区从同一 base SHA 创建，保证 hedge 公平；
- 创建失败必须释放 leases；
- 清理操作幂等；
- winner 默认不自动 merge；
- 记录最终 diff stats、changed paths 和 git status。

建议路径：

```text
.<product>/
  state.db
  runs/<run-id>/events.jsonl
  worktrees/<run-id>/<task-id>/<attempt-id>/
  reports/<run-id>/report.html
```

### FR-3：Codex Exec Adapter

Adapter 必须支持：

- 检查二进制与版本；
- 启动 `codex exec --json`；
- 设置 cwd 为 attempt worktree；
- 传入 task prompt；
- 通过 `-c` 覆盖允许的配置，例如 `agents.max_threads`；
- 显式使用最小所需 sandbox；代码修改任务默认 `workspace-write`，不得默认为 `danger-full-access`；
- 捕获 stdout JSONL、stderr、exit code、start/end time；
- 提取 thread id、turn/item events 和 usage（若提供）；
- 使用 process group 进行可控取消；
- 超时后 SIGTERM，再在 grace period 后 SIGKILL；
- 事件解析失败不能拖垮 scheduler；未知事件的 envelope 和非敏感原始行必须保留；
- 默认过滤 `reasoning`、prompt、agent-message 等可能含敏感内容的 payload，仅保留类型、时间和必要元数据；只有用户显式开启本地 sensitive capture 时才保存完整 payload；
- 不依赖、不分析 hidden reasoning。

后续 App Server adapter 再支持：

- `thread/start`、`thread/resume`、`thread/fork`；
- `turn/start`、`turn/interrupt`；
- 更丰富的 streamed events；
- rate limit snapshot；
- graceful cancellation。

### FR-4：Normalized Worker Contract

所有 adapter 归一化为：

```python
class WorkerAdapter(Protocol):
    async def doctor(self) -> DoctorResult: ...
    async def start(self, request: StartAttemptRequest) -> AttemptHandle: ...
    async def events(self, handle: AttemptHandle) -> AsyncIterator[WorkerEvent]: ...
    async def cancel(self, handle: AttemptHandle, reason: str) -> CancelResult: ...
    async def inspect(self, handle: AttemptHandle) -> AttemptStatus: ...
```

`WorkerEvent` 至少包括：

- `worker.started`；
- `worker.raw_event`；
- `worker.activity`；
- `worker.usage`；
- `worker.completed`；
- `worker.failed`；
- `worker.cancelled`。

### FR-5：Scheduler-owned verification

Verifier 配置必须由 task manifest 或可信项目配置提供，而不是由 Agent 运行时任意修改。

支持：

- 顺序执行多个 command；
- 每个 command 独立 timeout；
- `all_must_pass`；
- stdout/stderr 捕获和大小上限；
- exit code；
- optional changed-path allow/deny list；
- optional max changed files / lines；
- optional clean git status rules；
- verifier slots 与 Agent slots 分开；
- verifier 结果不可被 Agent 文本覆盖。

状态：

```text
agent_completed
  -> verification_queued
  -> verification_running
  -> verification_passed | verification_failed | verification_timed_out
```

### FR-6：Winner arbitration

- 每个 Task 最多一个 winner；
- verifier pass 后在单个数据库事务中 claim；
- 使用唯一约束或 compare-and-set 防止两个 verifier 同时获胜；
- claim 成功者进入 `verified`；
- claim 失败者进入 `superseded`；
- winner 产生后向所有非终态 attempts 发出 cancellation；
- cancellation 是 best-effort，必须记录 lag；
- winner branch/worktree 不能被 loser 清理逻辑删除。

### FR-7：Delayed hedging

启动 hedge 前必须同时满足：

- task `replay_safe=true`；
- 没有 winner；
- primary 仍在非终态；
- elapsed time 大于 threshold；
- 未达到 `max_replicas`；
- 有 root slot 和 workspace capacity；
- task/token/daily budget 仍允许；
- 未命中禁止复制的 resource 或 side-effect policy；
- scheduler 未处于 rate-limit backoff。

Threshold 选择：

1. 若该 bucket 样本数达到 `min_samples`，采用历史分位数；
2. 否则回退到 task-configured `fallback_after_seconds`；
3. bucket key 从精确到宽泛逐级回退：
   - repo + task_class + adapter + model + verifier_profile；
   - repo + task_class + adapter + model；
   - repo + adapter + model；
   - global adapter + model；
4. 只用成功或所有终态样本应作为可配置策略；默认使用从 start 到 terminal/verified 的完整分布并另行标记 censored runs。

MVP 使用 nearest-rank empirical quantile；后续再引入生存分析或在线 quantile sketch。

### FR-8：Adaptive concurrency

MVP 同时支持：

- `static`：用户明确指定 root slots；
- `auto`：AIMD 风格的透明控制器。

控制对象：

- global root run slots；
- verifier slots；
- optional resource-key semaphores；
- 每个 root run 的 Codex `agents.max_threads`；
- total nested thread budget。

建议 invariant：

```text
active_root_runs * configured_subagent_threads <= total_agent_thread_budget
```

该式是保守估算，因为并非每个 root 都会用满 subagents；报告必须区分“配置上限”和“观测活动量”。

AIMD 初版策略：

- backlog > 0；
- 最近健康窗口无 rate limit、spawn error 或高 verifier backlog；
- host load、内存、文件描述符和 test slots 未越界；
- 则 root concurrency `+1`，不超过 max；
- 遇到 rate limit、高失败率、持续 verifier queue、主机压力或取消积压，root concurrency 减半，最低为 min；
- 每次变更记录 signals、old value、new value 和 reason；
- 允许用户锁定 static 模式进行基线比较。

### FR-9：资源租约

Task 可以声明 resource keys：

```yaml
resources:
  - key: repo:auth
    capacity: 1
  - key: test:unit
    capacity: 2
```

MVP 提供：

- 全局或 run 级 semaphore；
- lease 有 owner、created_at、expires_at；
- crash 后可 reconciliation；
- hedge attempt 与 primary 可以共享只读资源，但不能违反独占资源策略；
- 默认不尝试自动预测文件冲突。

### FR-10：预算

支持：

- 每 task 最大 attempts；
- 每 task runtime 上限；
- 每 run token 上限（usage 可得时）；
- 每 run estimated cost 上限；
- 每日 estimated cost 上限；
- hedge 专属额外预算；
- 预算不足时不启动 backup，但 primary 可按 policy 继续；
- 预算决策必须在报告中可见。

### FR-11：持久化与恢复

- SQLite 使用 WAL；
- 每个 state transition 事务化；
- daemon 重启后扫描 nonterminal attempts；
- Codex Exec 子进程若无法可靠重新附着，状态置为 `orphaned`，执行保守策略：检查 process pid/cmdline/worktree，决定继续观察、取消或标记失败；
- 不得重复 claim winner；
- 不得重复释放已释放 lease；
- event log append-only；
- 数据库 schema 有迁移版本。

### FR-12：报告与解释

每个 scheduler decision 结构化记录：

```json
{
  "decision": "launch_hedge",
  "task_id": "issue-418",
  "attempt_id": "a2",
  "signals": {
    "elapsed_seconds": 912,
    "threshold_seconds": 900,
    "sample_count": 23,
    "root_slots_free": 1,
    "budget_remaining_estimated_usd": 3.4
  },
  "policy_version": "hedge-v1",
  "timestamp": "..."
}
```

报告不得只展示结论；要允许用户追溯为什么启动或没有启动 backup、为什么缩减并发、为什么某个 attempt 输掉。

---

## 11. 非功能需求

### 11.1 可靠性

- 所有取消、清理、lease release 操作幂等；
- state transitions 有显式合法迁移表；
- winner arbitration 在并发 verifier 下安全；
- 原始 Agent event 不因 parser bug 丢失；
- 报告可从数据库和 event log 重建；
- unexpected exception 不应删除 worktree。

### 11.2 性能

- scheduler 本身不应成为分钟级 Agent workload 的明显瓶颈；
- event ingestion 使用有界队列和 backpressure；
- 报告生成可离线；
- SQLite 单机并发足以覆盖 MVP，超过边界后再引入 PostgreSQL。

### 11.3 可测试性

- 所有 policy 输入为显式 clock、metrics 和 repository interfaces；
- 支持 fake clock；
- fake worker 可配置延迟、失败、usage 和 verification outcome；
- deterministic random seed；
- 不需要真实 Codex 即可完成绝大多数状态机测试。

### 11.4 可移植性

- Python 3.12+；
- macOS 和 Linux 为正式支持；
- 路径和 signal 逻辑隔离到 platform layer；
- WSL2 文档说明限制；
- 不承诺原生 Windows MVP。

### 11.5 可观测性

- structured logging；
- run/task/attempt correlation ids；
- JSONL raw events；
- 可选 OpenTelemetry exporter；
- prompts、agent messages、reasoning events、diff、stdout 是否写入本地 artifact 或 telemetry 必须有独立开关；
- 默认不保存 reasoning payload，不上传源码、prompt、diff、stdout 或 secrets。

---

## 12. 技术路线

### 12.1 总体架构

```text
                 Task Manifest / CLI
                         |
                         v
+--------------------------------------------------+
| FirstGreen daemon / process                      |
|                                                  |
|  Config + DAG       Scheduler + Policy Engine    |
|       |                    |                      |
|       v                    v                      |
|  State Store <---- Decision/Event Log            |
|       |                    |                      |
|       +------> Resource / Budget Manager          |
|                            |                      |
|              +-------------+-------------+        |
|              v                           v        |
|       Worker Adapter                 Verifier     |
|       (Codex Exec)                   Pool         |
+--------------|---------------------------|--------+
               v                           v
      isolated git worktrees       test/lint/typecheck
               |
               v
        Codex service / tools
```

### 12.2 技术选型

- **语言**：Python 3.12+
- **CLI**：Typer
- **配置和 schema**：Pydantic v2 + YAML
- **并发**：`asyncio`
- **数据库**：SQLite WAL；SQLAlchemy 2 + Alembic，或在最早原型使用 `aiosqlite`，但正式 MVP 应有迁移机制
- **HTTP（后续 local dashboard）**：FastAPI
- **HTML report**：Jinja2 + 静态 JS/CSS；MVP 不依赖前端构建链
- **系统指标**：psutil
- **测试**：pytest、pytest-asyncio、Hypothesis（状态机/属性测试可选但推荐）
- **质量**：Ruff、mypy 或 Pyright
- **打包**：`pyproject.toml`，uv/pipx 安装
- **文档**：MkDocs Material + GitHub Pages

### 12.3 为什么 MVP 先用 `codex exec --json`

优点：

- 接入最小；
- JSONL 适合流式持久化；
- 可以在任意 worktree 设置 cwd；
- 可以使用进程组取消；
- 可以读取事件、thread id 和 usage（可用时）；
- 不必先实现长连接 JSON-RPC 客户端。

限制：

- graceful interrupt 和恢复能力弱于 App Server；
- rate limit telemetry 可能不完整；
- daemon 重启后进程重附着较复杂；
- process kill 不保证供应商服务端计算立即停止。

因此 adapter interface 必须从第一天允许替换，第二阶段实现 App Server adapter。

### 12.4 建议仓库结构

```text
firstgreen/
├── AGENTS.md
├── README.md
├── LICENSE
├── pyproject.toml
├── src/firstgreen/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── ids.py
│   ├── clock.py
│   ├── db/
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── migrations/
│   ├── domain/
│   │   ├── task.py
│   │   ├── attempt.py
│   │   ├── events.py
│   │   ├── policy.py
│   │   └── state_machine.py
│   ├── scheduler/
│   │   ├── engine.py
│   │   ├── admission.py
│   │   ├── hedging.py
│   │   ├── concurrency.py
│   │   ├── resources.py
│   │   └── budgets.py
│   ├── adapters/
│   │   ├── base.py
│   │   ├── fake.py
│   │   ├── codex_exec.py
│   │   └── codex_events.py
│   ├── workspace/
│   │   └── git_worktree.py
│   ├── verifier/
│   │   ├── runner.py
│   │   └── constraints.py
│   ├── reporting/
│   │   ├── metrics.py
│   │   ├── export.py
│   │   └── html.py
│   ├── telemetry/
│   │   ├── logging.py
│   │   └── otel.py
│   └── doctor.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── property/
│   └── fixtures/
├── examples/
│   ├── fleet.yaml
│   └── demo_repo_tasks.yaml
├── benchmarks/
│   ├── simulator.py
│   ├── policies.py
│   └── analyze.py
└── docs/
```

---

## 13. 数据模型与状态机

### 13.1 主要实体

#### Run

- id
- manifest hash
- repo path
- base SHA
- policy snapshot
- status
- created/started/finished timestamps
- aggregate budgets

#### Task

- id
- run id
- prompt/objective
- task class
- priority
- dependencies
- replay_safe
- resource requirements
- verifier profile
- status
- winner attempt id nullable

#### Attempt

- id
- task id
- ordinal
- role: primary/hedge/retry
- adapter/model/config snapshot
- worktree/branch
- process/thread identifiers
- status
- start/end/cancel timestamps
- token/usage fields
- error classification

#### VerificationRun

- id
- attempt id
- command index
- command
- exit code
- stdout/stderr artifact refs
- start/end timestamps
- status

#### SchedulerDecision

- id
- run/task/attempt ids
- decision type
- signals JSON
- policy version
- timestamp

#### ResourceLease

- key
- owner attempt/task
- capacity unit
- acquired/expires/released timestamps

#### Event

- monotonic sequence
- correlation ids
- normalized type
- raw payload ref
- timestamp

### 13.2 Task 状态

```text
queued -> ready -> running -> verifying -> verified
                    |            |          
                    |            +-> failed
                    +-> failed
                    +-> cancelled
queued/ready -> blocked
```

### 13.3 Attempt 状态

```text
created -> starting -> running -> agent_completed -> verifying -> passed
              |          |             |               |          
              +-> failed +-> cancelled +-> failed      +-> failed
                                                     
passed -> winner | superseded
```

状态迁移必须集中定义，不允许各模块随意写 status 字段。

---

## 14. 调度算法设计

### 14.1 Ready queue

MVP 排序键：

1. 用户优先级；
2. 估算 critical path（可先用 remaining descendant count 近似）；
3. 等待时间；
4. 稳定 task id tie-break。

不使用 LLM 直接维护队列。

### 14.2 Primary 启动

伪代码：

```python
while scheduler_running:
    reconcile_state()
    update_concurrency_controller()
    for task in ready_tasks_ordered():
        if admission_allowed(task):
            acquire_resources(task)
            create_primary_attempt(task)
            start_worker(task)
    evaluate_hedge_candidates()
    collect_events()
```

### 14.3 Hedge candidate score

MVP 不需要复杂 ML。候选满足阈值后按以下优先级排序：

- elapsed / threshold 比值；
- task priority；
- estimated critical path impact；
- historical hedge win probability（有数据后）；
- estimated additional cost。

第一版只需要确定性评分，公式和权重写入 policy snapshot。

### 14.4 First-verified-wins

```python
async def on_verification_pass(attempt_id):
    task_id = lookup_task(attempt_id)
    async with db.transaction():
        won = compare_and_set_task_winner(task_id, expected=None, new=attempt_id)
        if won:
            mark_attempt_winner(attempt_id)
            mark_task_verified(task_id)
        else:
            mark_attempt_superseded(attempt_id)
    if won:
        cancel_other_attempts(task_id)
```

### 14.5 Retry 与 hedge 的区别

- **Retry**：前一次 attempt 已终态失败后再启动；
- **Hedge**：前一次 attempt 仍在运行时启动并行 backup；
- 两者必须在 metrics 中分开；
- `max_attempts` 和 `max_replicas` 分开控制；
- verifier failed 可以触发 repair retry，但 MVP 可先采用全新 attempt；
- 不允许无限 retry。

### 14.6 冷启动

没有历史数据时：

- 默认 `hedge.enabled=false`，除非 manifest 提供 fallback threshold；或
- demo/benchmark profile 明确配置 `fallback_after_seconds`；
- `min_samples` 达到后再切换到 quantile mode；
- UI/报告明确标注当前 threshold 来源：configured fallback / historical quantile。

为了让首版可展示，示例配置可以启用 fallback；生产默认应保守。

### 14.7 自适应并发控制器

初版控制窗口建议为固定若干秒或事件批次，使用以下 signals：

- provider rate-limit / retryable errors；
- Agent spawn failures；
- host CPU/load/memory pressure；
- verifier queue length 与 wait time；
- cancellation backlog；
- workspace creation latency；
- recent task throughput。

决策：

```text
healthy + backlog -> additive increase
pressure/error    -> multiplicative decrease
otherwise         -> hold
```

必须设置 cooldown，避免频繁振荡。用户可通过报告查看每次变化。

---

## 15. 配置规格

参考示例见 `examples/fleet.yaml`。核心 schema：

```yaml
version: 1
project:
  repo: /absolute/path/to/repo
  base_ref: main

scheduler:
  objective: p95_time_to_verified
  concurrency:
    mode: auto
    min_root: 1
    max_root: 6
    initial_root: 2
    total_agent_thread_budget: 12
    verifier_slots: 2
  hedge:
    enabled: true
    quantile: 0.90
    min_samples: 10
    fallback_after_seconds: 900
    max_replicas: 1
    cancel_loser: true
  budgets:
    max_run_estimated_usd: 50

agent_defaults:
  adapter: codex_exec
  sandbox: workspace-write
  network_access: false
  capture_sensitive_events: false
  max_subagent_threads: 2
  timeout_seconds: 3600

verification_defaults:
  command_timeout_seconds: 900
  all_must_pass: true

tasks:
  - id: issue-418
    task_class: bugfix
    prompt: Fix the OAuth callback race condition. Do not change public APIs.
    replay_safe: true
    dependencies: []
    resources:
      - key: repo:auth
        capacity: 1
    verify:
      commands:
        - pytest -q tests/auth
        - ruff check src/auth tests/auth
      allowed_changed_paths:
        - src/auth/**
        - tests/auth/**
```

Schema 原则：

- unknown fields 默认报错，避免拼写错误被静默忽略；
- secrets 不允许直接写进 manifest；
- manifest hash 写入 Run；
- policy version 和有效配置快照必须持久化；
- CLI override 要在报告中展示。

---

## 16. 安全、隐私与合规

### 16.1 威胁模型

coding agent 会执行仓库中的命令，仓库本身可能不可信；verifier 同样会执行代码。FirstGreen 不是完整沙箱，MVP 必须明确安全边界。

主要风险：

- 恶意仓库读取环境变量和凭据；
- Agent 或测试命令执行任意 shell；
- 日志泄露 prompt、源码、token 或 secrets；
- hedge 对有副作用任务造成重复操作；
- loser 取消不及时继续消耗资源；
- worktree 路径/清理 bug 删除用户文件；
- 自动 merge 引入未经审查的代码。

### 16.2 MVP 安全措施

- 使用官方程序化认证；不抓取或转售个人订阅凭据；
- 凭据只存在于本机进程环境，默认不持久化；
- 对 job-level secrets 使用显式 allowlist；
- 提示用户不要把高权限通用 API key 暴露给不可信 repo；
- manifest 中 `replay_safe` 默认 false；
- 未标记 replay-safe 的任务禁止 hedge；
- verifier command 来自可信配置，不接受 Agent 动态覆盖；
- 默认不自动 push、merge、发布或调用生产 API；
- 所有 worktree 必须位于产品专属根目录并进行路径边界检查；
- 删除前检查 `.git` worktree registration、run id 和 marker file；
- stdout/stderr 设大小上限并支持 redaction；
- telemetry 默认只本地；
- 提供 `--dry-run`；
- 报告中明确 cancellation 是 best-effort。

### 16.3 后续安全路线

- Docker/Podman sandbox runner；
- seccomp/network policy；
- VPC/self-hosted remote runner；
- secret broker；
- signed policy bundles；
- SSO/RBAC/audit log；
- verifier image pinning 和 SBOM。

---

## 17. Benchmark 与科研验证方案

### 17.1 为什么必须先做 simulator

真实 Codex runs 成本高、噪声大、迭代慢。Simulator 用于验证状态机、取消竞态和 policy trade-off，不用于替代真实产品结果。

Simulator 参数：

- task arrival process；
- runtime distribution：lognormal、Pareto、mixture；
- failure probability；
- verification latency；
- primary/backup correlation；
- provider capacity/rate-limit；
- nested subagent pressure；
- cancellation lag；
- token/cost rate；
- replay-safety proportion。

要求：

- 固定随机种子；
- 可重复运行；
- 输出原始事件和汇总；
- 覆盖 single、always-race、delayed hedge、auto policies；
- 支持 parameter sweep。

### 17.2 真实 benchmark

首轮建议：

- 选择 2–3 个小型开源仓库或专门构造的 demo repos；
- 每个 repo 固定 base commits；
- 设计 20–40 个有确定性测试的 bugfix/maintenance tasks；
- 任务分为短、中、长尾倾向；
- 每个 policy 重复多次；
- 使用相同 Codex 配置和总预算；
- 记录供应商限流、模型版本和运行时环境；
- 所有失败和排除样本都公开说明。

Policy baselines：

- A：single attempt + static concurrency；
- B：single attempt + high fixed concurrency；
- C：always-race two attempts；
- D：delayed hedge + fixed concurrency；
- E：delayed hedge + adaptive concurrency。

### 17.3 评价图表

- P50/P95 time-to-green；
- cost/tokens per green；
- verified throughput vs concurrency；
- extra attempt-time vs P95 improvement；
- hedge quantile vs latency/cost Pareto frontier；
- task-level Gantt/timeline；
- root concurrency 与 verifier queue；
- rate limit events 与 throughput；
- CDF 或 survival curve；
- bootstrap confidence intervals。

### 17.4 发布声明规则

- 只在可复现 benchmark 上给百分比；
- 使用“在该 workload、模型、日期和预算下”；
- 不把 simulator 结果宣传为现实节省；
- 不使用单个 cherry-picked task；
- 报告原始数据、配置、commit SHA 和版本。

---

## 18. 产品分析与成功指标

### 18.1 North Star

**Verified tasks completed within user-defined SLO and budget per week**。

早期本地工具难以自动收集用户指标，因此默认不做遥测；可通过自愿匿名 telemetry 或用户研究获得。

### 18.2 Activation

- `doctor` 通过；
- 成功执行第一个 task；
- 得到第一个 deterministic green result；
- 生成第一份 report。

### 18.3 Product value metrics

- 相比用户 static baseline 的 P95 time-to-green 变化；
- 相比 always-race 的额外成本变化；
- verified tasks/hour；
- verifier failure interception rate；
- 推荐并发被采用后的实际收益；
- 30 天内重复运行同一 repo 的用户比例（仅在用户同意 telemetry 时）。

### 18.4 Reliability metrics

- state recovery success；
- winner double-claim incidents，目标为 0；
- workspace corruption incidents，目标为 0；
- cancellation success 和 lag；
- event parser error rate；
- orphaned attempts；
- report generation failure rate。

---

## 19. 开源与商业模式

### 19.1 推荐开源策略

Core 采用 Apache-2.0：

- 本地 scheduler；
- Codex Exec adapter；
- simulator；
- verification；
- delayed hedge；
- adaptive concurrency；
- local report；
- benchmark protocol。

原因：

- developer tooling 需要信任和可审计；
- 本地源码和凭据场景更适合 open core；
- 需要真实社区数据和 adapter 贡献；
- 与 Symphony 等开放生态更容易组合。

### 19.2 潜在付费层

不是 MVP 承诺，而是验证方向：

**Team**

- PostgreSQL/shared history；
- remote runners；
- GitHub App / issue tracker；
- team policy 和 verifier templates；
- shared dashboard；
- scheduled benchmarks；
- notifications。

**Enterprise / Self-hosted**

- SSO/RBAC；
- VPC/on-prem runners；
- centralized audit；
- secret broker；
- policy enforcement；
- compliance retention；
- SLA/support。

### 19.3 护城河假设

- repo-specific runtime/failure models；
- 任务类型到最佳 Agent/config 的 routing data；
- scaling regression history；
- verifier template ecosystem；
- policy benchmark credibility；
- 与 CI/issue/remote runner 的工作流粘性。

---

## 20. 发布平台与 GTM

### 20.1 分发平台

第一优先级：

- GitHub 开源仓库；
- GitHub Releases；
- PyPI，通过 `uv tool install` / `pipx install`；
- MkDocs + GitHub Pages；
- 预构建示例配置和 demo repo。

第二优先级：

- Homebrew tap；
- GHCR Docker image（为远程 runner 做准备）；
- VS Code extension 仅作为状态入口，不把核心塞进编辑器；
- GitHub App/Actions integration。

### 20.2 首发内容

必须准备：

1. 60–90 秒 terminal/GIF demo；
2. “single vs always-race vs delayed hedge” 图；
3. 一份可复现实验报告；
4. `uv tool install` 到首个 green 的快速开始；
5. 架构图和安全边界；
6. 与 Codex native、Symphony、Bernstein 的诚实差异说明；
7. 视频：《Codex 已经会并行，为什么还需要一个调度器？》；
8. 技术文章：《用 delayed hedging 降低 coding-agent 的 P95 time-to-green》。

### 20.3 发布渠道

- GitHub；
- Hacker News / Show HN；
- X / LinkedIn；
- Reddit 的 coding-agent、LLM engineering、self-hosted 等相关社区，遵守社区规则；
- OpenAI developer 社区和 issue/discussion；
- Bilibili、YouTube；
- 中文技术社区与 HPC/系统方向社区。

Product Hunt 可作为第二波曝光，不应替代早期技术用户反馈。

### 20.4 Demo 叙事

```text
一个任务正常 8 分钟完成，另一个偶尔卡到 35 分钟。
Always-race 每次烧两份成本。
FirstGreen 先只跑一份；超过历史 P90 才启动 backup；
第一个通过测试的结果获胜，另一份被取消。
最后展示 P95、成本和 wasted compute 的对比。
```

---

## 21. 实现计划与工程里程碑

> 不按日历承诺；按依赖和 exit criteria 推进。每个 milestone 必须可运行、可测试、可回滚。

### M0：仓库骨架、领域模型与 ADR

复杂度：S

交付：

- `pyproject.toml`、lint/type/test；
- AGENTS.md；
- domain entities 和 state transition table；
- adapter/verifier/repository protocols；
- architecture decision records：
  - ADR-001 local-first；
  - ADR-002 Codex Exec first；
  - ADR-003 SQLite WAL；
  - ADR-004 deterministic verification；
  - ADR-005 no auto-merge；
- CI。

Exit criteria：

- `uv run pytest`、Ruff、typecheck 通过；
- illegal state transition 有测试；
- 不调用真实 Codex。

### M1：Simulator + 持久化 scheduler

复杂度：M

交付：

- fake worker；
- SQLite schema/migrations；
- run/task/attempt/event persistence；
- static concurrency；
- fake clock；
- crash/restart reconciliation 基础；
- CLI `benchmark simulate`。

Exit criteria：

- 固定种子结果可复现；
- 并发状态机无 double winner；
- restart 后不会重复启动已终态 attempt；
- 可导出 JSON/CSV。

### M2：真实 Codex Exec + worktree

复杂度：M

交付：

- `doctor`；
- `codex exec --json` adapter；
- JSONL parser 与 raw event persistence；
- process group cancellation；
- git worktree manager；
- 单 task 单 attempt 端到端。

Exit criteria：

- 在 demo repo 中完成一个真实任务；
- 主工作目录不被修改；
- 失败和 Ctrl-C 后 worktree 可恢复/清理；
- raw event parser 面对未知事件不崩溃。

### M3：Verifier + winner arbitration

复杂度：M

交付：

- command verifier；
- changed-path constraints；
- verifier slots；
- atomic winner claim；
- loser cancellation；
- task DAG 解锁。

Exit criteria：

- 两个 attempts 几乎同时通过时只有一个 winner；
- Agent 自报完成但测试失败时 task 不 green；
- winner worktree 永不被 loser cleanup 删除。

### M4：Delayed hedging

复杂度：M

交付：

- history buckets；
- empirical quantiles；
- fallback threshold；
- replay-safety gate；
- hedge budget；
- first-verified-wins timeline；
- single / always-race / delayed policy benchmark。

Exit criteria：

- simulator heavy-tail 中 delayed hedge 可测量降低 P95；
- 额外 attempt-time 低于 always-race；
- 任务不 replay-safe 时绝不启动 backup；
- benchmark 结果不硬编码，测试验证 invariant 而非具体收益百分比。

### M5：Adaptive concurrency

复杂度：M–L

交付：

- root/verifier/nested thread budgets；
- AIMD controller；
- host load 与 queue signals；
- rate-limit/error signal adapter；
- decision log；
- static/auto comparison。

Exit criteria：

- 高压力信号触发 multiplicative decrease；
- 健康 backlog 触发 additive increase；
- cooldown 防止振荡；
- 所有变更有可解释 reason；
- 配置硬上限永不突破。

### M6：Report 与产品体验

复杂度：M

交付：

- `init/validate/run/status/cancel/report/export`；
- 静态 HTML report；
- task timeline；
- policy comparison；
- doctor remediation 文案；
- example manifest；
- demo recording script。

Exit criteria：

- 新用户按 README 能完成 demo；
- report 可以脱离 daemon 打开；
- 所有关键指标有单位、口径和来源；
- estimate 与 actual 明确区分。

### M7：硬化与首发

复杂度：M

交付：

- packaging；
- GitHub Actions matrix；
- security review；
- fault injection；
- benchmark dataset/config；
- docs site；
- release notes；
- optional anonymous telemetry 设计，默认关闭；
- Apache-2.0 license 和贡献指南。

Exit criteria：

- macOS/Linux smoke test；
- 完整 benchmark 可复现；
- 公开已知限制；
- 没有未处理的 worktree deletion 或 double-winner 高危 bug；
- 首发 claims 与数据一致。

### M8：第二阶段候选

- Codex App Server adapter；
- Symphony-compatible tracker adapter；
- Claude Agent SDK adapter；
- generic HTTP/subprocess worker；
- GitHub issues/PR integration；
- remote runners；
- PostgreSQL；
- team dashboard；
- task classifier/router；
- conflict-aware admission；
- container sandbox；
- survival-analysis hedge policy。

---

## 22. Codex 实现任务拆分

### Epic A：Foundation

- A1 初始化 Python 包和 CI；
- A2 定义 IDs、Clock、domain models；
- A3 定义合法状态迁移；
- A4 定义 repository、adapter、workspace、verifier protocols；
- A5 建立 SQLite schema 和 migration；
- A6 structured logging/correlation IDs。

### Epic B：Scheduler core

- B1 DAG validation；
- B2 ready queue；
- B3 resource leases；
- B4 static admission；
- B5 budget checks；
- B6 reconciliation loop；
- B7 fake worker 与 fake clock。

### Epic C：Codex + Git

- C1 doctor；
- C2 worktree create/inspect/cleanup；
- C3 Codex subprocess start；
- C4 JSONL parsing；
- C5 usage/event storage；
- C6 timeout/cancel；
- C7 nested subagent config override。

### Epic D：Verification

- D1 command runner；
- D2 timeout/output cap；
- D3 changed-path constraints；
- D4 verifier queue；
- D5 atomic winner；
- D6 cancel/supersede losers。

### Epic E：Hedging

- E1 runtime samples；
- E2 quantile buckets；
- E3 replay-safe policy；
- E4 hedge candidate evaluator；
- E5 backup worktree/attempt；
- E6 metrics；
- E7 always-race baseline。

### Epic F：Adaptive concurrency

- F1 pressure signal interface；
- F2 host signals；
- F3 provider/error signals；
- F4 AIMD state；
- F5 nested thread budget；
- F6 decision log and tests。

### Epic G：UX/reporting

- G1 CLI；
- G2 manifest schema/errors；
- G3 status table；
- G4 JSON/CSV export；
- G5 static HTML；
- G6 benchmark comparison；
- G7 documentation/demo。

---

## 23. 验收测试清单

### 23.1 核心正确性

- [ ] DAG cycle 被拒绝；
- [ ] 同一 task 只能有一个 winner；
- [ ] verifier failure 不能标记 green；
- [ ] loser cancellation 不影响 winner；
- [ ] winner branch/worktree 被保留；
- [ ] replay-safe=false 永不 hedge；
- [ ] budget 不足时不 hedge；
- [ ] hard concurrency cap 永不突破；
- [ ] process crash 后 lease 可恢复；
- [ ] cleanup 幂等且不越过产品 workspace 根目录。

### 23.2 Codex adapter

- [ ] 找不到 Codex 时 doctor 给出可执行修复提示；
- [ ] JSONL 未知 event 被保留；
- [ ] stderr 不阻塞 stdout ingestion；
- [ ] timeout 触发 graceful cancel + hard kill fallback；
- [ ] exit code、usage 和 thread id 可得时持久化；
- [ ] `agents.max_threads` override 在事件/配置快照中可见。

### 23.3 Hedging

- [ ] threshold 来源明确；
- [ ] min_samples 未达到时使用 fallback；
- [ ] primary 在 threshold 前完成不会启动 backup；
- [ ] backup 通过后 primary 被取消；
- [ ] primary 通过后 backup 被取消；
- [ ] 两者都失败时按 retry policy 处理；
- [ ] cancellation lag 被记录。

### 23.4 Adaptive concurrency

- [ ] 健康窗口只增加 1；
- [ ] 压力触发减半；
- [ ] cooldown 生效；
- [ ] min/max 生效；
- [ ] verifier backlog 可压低 root concurrency；
- [ ] 每个 decision 有 reason 和 signals。

### 23.5 报告

- [ ] P50/P95 口径正确；
- [ ] failed/cancelled/censored runs 处理明确；
- [ ] token 与 estimated cost 分离；
- [ ] single/always-race/delayed policy 可比较；
- [ ] 原始 run/config/commit/version 可追溯。

---

## 24. 风险登记与应对

| 风险 | 影响 | 概率 | 应对 |
|---|---|---:|---|
| OpenAI 快速加入同类功能 | 差异缩小 | 高 | 建立跨版本 benchmark、repo history、跨供应商路线和政策数据 |
| Bernstein 等开源项目迭代 | 功能重叠 | 高 | 不拼 adapter 数；用 delayed selective redundancy、autotuning 和数据证明差异 |
| coding task 验证不可靠 | 优化错误目标 | 高 | deterministic contracts；开放式任务不进入核心 benchmark |
| primary/backup 错误高度相关 | hedge 收益低 | 中 | 记录相关性；后续使用 prompt/model diversity；不预设收益 |
| 复制产生副作用 | 严重安全问题 | 中 | replay-safe 默认 false；MVP 禁止外部副作用任务 hedge |
| 取消不及时仍产生费用 | 成本不确定 | 高 | 记录 cancellation lag；报告 best-effort；App Server adapter 提升 graceful interrupt |
| API 限流主导结果 | benchmark 失真 | 高 | 记录 rate-limit；控制 root/nested 并发；同配置重复实验 |
| 订阅/计费成本不可精确归因 | ROI 难算 | 中 | token、estimated cost、actual invoice 分开 |
| worktree cleanup bug | 数据损失 | 低但严重 | 专属根目录、marker、dry-run、路径边界、保守不删 |
| 不可信 repo 窃取凭据 | 安全事故 | 中 | local-first、最小权限、明确警告、后续 sandbox/secret broker |
| SQLite 达到并发极限 | 扩展受限 | 低（MVP） | repository abstraction；团队版 PostgreSQL |
| 用户没有批量任务 | 使用频率低 | 中 | 面向有 backlog/CI 的高频用户；视频和 benchmark 验证需求 |
| “auto”不稳定或不可解释 | 用户不信任 | 中 | 简单 AIMD、hard limits、decision log、static fallback |

---

## 25. 关键产品决策（已定）

1. 第一版 **Codex-first**，但 adapter interface 独立。
2. 第一版 **CLI/local-first**，不先做 SaaS。
3. 第一版以 `codex exec --json` 集成，App Server 为第二阶段。
4. Agent 完成后必须经过 scheduler-owned verifier。
5. Winner 是 first verified，不是 first response。
6. Hedge 默认仅一个 backup，且 task 必须 replay-safe。
7. 不自动 merge/push。
8. 不做复杂 ML scheduler，先使用透明 quantile + AIMD。
9. SQLite 足够 MVP，但 schema/repository 为 PostgreSQL 预留。
10. 先做 simulator 和 fake adapter，再花真实模型成本。
11. 工作代号不作为最终品牌承诺。
12. 发布时不声称任何收益，除非 benchmark 支持。

---

## 26. 尚待验证的问题

这些不阻塞 M0–M3，但决定后续产品方向：

- 用户最在意 P95 latency、verified throughput 还是 cost per green？
- Codex Exec 事件对“活动/停滞”的可观察度是否足够，还是应尽快切 App Server？
- 用户是否愿意显式写 verifier contract？哪些模板可以自动生成但由人确认？
- 对真实 coding tasks，backup 与 primary 的失败相关性有多高？
- P90、P95 或基于 hazard rate 的 hedge threshold 哪个更合适？
- root concurrency 与 `agents.max_threads` 的最佳预算如何分配？
- 用户愿不愿意将匿名、去源码化性能统计贡献给公共 benchmark？
- 与 Symphony 做兼容插件，还是保持独立 runner，哪个 adoption 更快？
- open-source core 的早期付费意愿来自 remote runners、team history、policy，还是 GitHub integration？

---

## 27. 发布前的 Go / No-Go 标准

### Go

- 真实 Codex 端到端稳定；
- no double winner；
- no workspace corruption；
- benchmark 可复现；
- delayed hedge 在至少一种真实或严格仿真 heavy-tail workload 中显示合理延迟—成本 trade-off；
- docs 可以让外部用户独立运行；
- 安全边界和限制写清楚；
- 竞品对比没有虚假“首创”表述。

### No-Go

- 只能展示多开 Codex 窗口；
- verifier 仍依赖 Agent 自报；
- 无法可靠取消/隔离 attempts；
- benchmark 只有单次 cherry-picked demo；
- cleanup 有删除非产品目录风险；
- 需要用户交出不合规凭据；
- auto concurrency 无 hard cap 或无解释日志。

---

## 28. 参考资料与事实依据

以下链接供实现时核对，文档和接口可能更新：

1. OpenAI Codex Subagents：<https://developers.openai.com/codex/subagents/>
2. OpenAI Codex Non-interactive mode (`codex exec --json`)：<https://developers.openai.com/codex/noninteractive/>
3. OpenAI Codex App Server：<https://developers.openai.com/codex/app-server/>
4. OpenAI Codex Configuration Reference：<https://developers.openai.com/codex/config-reference/>
5. OpenAI Codex Advanced Configuration / OpenTelemetry：<https://developers.openai.com/codex/config-advanced/>
6. OpenAI Codex Authentication：<https://developers.openai.com/codex/auth/>
7. OpenAI Symphony announcement：<https://openai.com/index/open-source-codex-orchestration-symphony/>
8. OpenAI Symphony repository/spec：<https://github.com/openai/symphony>
9. Bernstein：<https://github.com/sipyourdrink-ltd/bernstein>
10. Agent Orchestrator：<https://github.com/ComposioHQ/agent-orchestrator>
11. Tutti：<https://github.com/nutthouse/tutti>
12. GitHub Agent HQ / Mission Control：<https://github.blog/ai-and-ml/github-copilot/how-to-orchestrate-agents-using-mission-control/>
13. Google Research, The Tail at Scale：<https://research.google/pubs/the-tail-at-scale/>
14. USENIX, When to Hedge in Interactive Services：<https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/dean>

---

## 29. 给实现者的最后约束

- 先实现正确、可恢复的状态机，再接真实 Agent。
- 不要为了 demo 绕过 verifier、winner transaction 或 workspace safety。
- 不要把 LLM 放进调度核心；LLM 可以做 worker，不能拥有资源锁和真相状态。
- 不要一开始写 dashboard、GitHub App、远程 runner 或多供应商 adapter。
- 每个 milestone 完成后运行 unit、integration、typecheck、lint，并更新已知限制。
- 所有“自动”策略必须有 static fallback、hard limits 和 decision log。
- 任何无法安全复制的 task 都不得 hedge。
- 任何无法通过数据证明的产品收益都不得写进首页数字。

---

## 30. Repository-aware planning layer

最终产品流程：

```text
Natural-language issue → read-only repo scan → decomposition decision
→ optional one structured planner call → deterministic DAG compiler
→ validation/conflict analysis → human or low-risk policy approval
→ existing verified scheduler
```

支持三种模式：`--plan none` 保持一个 execution task；`--plan auto` 决定单任务或小 DAG；
既有 YAML/GitHub issue backlog 作为 top-level tasks，避免无意义重规划。MVP 最大 decomposition
depth 为 1，最多 5 tasks，普通 retry/hedge 必须复用同一个 approved plan。

Planning 的正确性目标不是制造更多 tasks，而是改善 time/cost-to-verified-result，同时控制
plan validation failure、用户编辑率、重复工作、write overlap 和 merge conflicts。完整规格见
`04_PLANNING_SUBSYSTEM.md`。
