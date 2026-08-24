# FirstGreen 可执行 Backlog

本文件按依赖顺序给 Codex 使用。每次只领取一个小批次，完成后运行测试并更新勾选项。不要同时展开所有 Epic。

## Batch 0 — Bootstrap

- [x] 初始化 Python 3.12 `pyproject.toml`
- [x] 添加 Typer、Pydantic、PyYAML、SQLAlchemy/Alembic、pytest、pytest-asyncio、Ruff、mypy/Pyright
- [x] 建立 `src/` layout
- [x] 添加 Apache-2.0 LICENSE（公开发布前由 owner 最终确认）
- [x] 添加 GitHub Actions：lint、typecheck、tests
- [x] 添加 `AGENTS.md`
- [x] 创建 ADR 目录和五个初始 ADR
- [x] `firstgreen --help` 可运行

**验收**：CI 绿；无业务功能。

## Batch 1 — Domain and persistence

- [x] 实现 typed IDs 和 UTC clock
- [x] 定义 Run/Task/Attempt/Verification/Event/Decision/Lease 模型
- [x] 实现集中式状态迁移表
- [x] 建立 SQLite WAL + migrations
- [x] repository interfaces 和 SQL implementation
- [x] append-only event writer
- [x] 测试非法迁移、事务回滚和唯一约束

**验收**：并发模拟写入不会产生重复 task/attempt；非法状态被拒绝。

## Batch P0 — Planning domain and schemas

- [x] Issue/planning lifecycle、RepositoryMap、Proposal、Candidate/ApprovedPlan schemas
- [x] Planning persistence tables and bounded configuration
- [x] Proposal、approval、execution plan 类型隔离

## Batch P1 — Repository scanner

- [x] 只读 bounded repo map
- [x] Python AST/import/API/test mapping
- [x] build/test commands、CODEOWNERS、有限 Git co-change history

## Batch P2 — Deterministic decomposition decision

- [x] small/local task bypass
- [x] single-task/decompose reason 与 recommended parallelism
- [x] 有效并行度 1 作为成功结果

## Batch P3 — Structured planner adapters

- [x] FakePlanner 与严格 structured adapter
- [x] 单次调用上限、压缩 prompt、cache key/result cache
- [x] 显式 opt-in Codex read-only planner 与默认跳过 live smoke

## Batch P4 — DAG compiler and conflicts

- [x] Artifact dependency edges 与必要 verification ordering
- [x] Write conflicts 独立 resource constraints
- [x] Scheduler keyed semaphore 强制冲突串行

## Batch P5 — Validation, merging and fallback

- [x] DAG/artifact/verifier/path/conflict/bounds validation
- [x] Artificial cycle/high-overlap deterministic merging
- [x] Malformed/unsafe proposal single-task fallback

## Batch P6 — Review and approval

- [x] Terminal plan review
- [x] YAML export/edit/re-import/re-validation
- [x] Human approval 与 low-risk-only policy auto-approval

## Batch P7 — Scheduler integration

- [x] `scan/plan/validate-plan`
- [x] `run ISSUE --plan none|auto` 与 approved plan→Manifest compilation
- [x] Existing manifest/backlog 保持兼容

## Batch P8 — Planning metrics and reports

- [x] Planning latency/tokens/estimated cost 独立持久化
- [x] Planning metrics 与 run/report snapshot
- [x] 未具备真实数据的 actual-overlap/parallelism 指标显式为空

## Batch 2 — Fake worker and static scheduler

- [x] WorkerAdapter protocol
- [x] FakeWorkerAdapter：可配置 latency、events、exit、usage
- [x] FakeClock
- [x] DAG parse/cycle detection
- [x] Ready queue
- [x] Static root semaphore
- [x] Task/Attempt lifecycle loop
- [x] `benchmark simulate` 最小版

**验收**：固定 seed 下可复现；run 重启后终态不重复。

## Batch 3 — Git worktrees

- [x] Repo discovery/base SHA pinning
- [x] Worktree naming/marker
- [x] Safe create/inspect/cleanup
- [x] Winner retention policy
- [x] Path traversal and deletion boundary tests
- [x] Temporary git repo integration tests

**验收**：主工作区不变；重复 cleanup 幂等；未知路径不删。

## Batch 4 — Codex Exec adapter

- [x] `doctor` 检查 Codex binary/version/auth smoke
- [x] 命令 builder，使用 argv
- [x] async subprocess + process group
- [x] stdout/stderr concurrent readers
- [x] tolerant JSONL parser
- [x] raw artifact persistence
- [x] usage/thread id extraction（best effort）
- [x] timeout/cancel/hard-kill
- [x] `agents.max_threads` override snapshot
- [x] Live smoke test opt-in

**验收**：demo repo 单 task 完成；未知 JSON event 不崩溃；取消不留活动子进程（在 OS 可控制范围内）。

## Batch 5 — Verification and winner

- [x] Verification schema
- [x] Async command runner
- [x] Output cap/timeouts
- [x] Changed-path policy
- [x] Verifier semaphore
- [x] Atomic winner claim
- [x] Supersede/cancel losers
- [x] Task dependency unlock
- [x] Simultaneous-pass race test

**验收**：1000 次并发 race 测试无双 winner；Agent done + tests fail 不 green。

## Batch 6 — Hedging

- [x] Runtime sample storage
- [x] Bucket key/fallback
- [x] Empirical quantile
- [x] HedgePolicy gates
- [x] Fallback threshold
- [x] Budget check
- [x] Create backup from same base SHA
- [x] First verified wins
- [x] Hedge metrics
- [x] Always-race baseline

**验收**：replay_safe=false 不复制；simulator 中输出 latency/cost frontier。

## Batch 7 — Adaptive concurrency

- [x] PressureSignal interface
- [x] Host metrics
- [x] Queue/verifier metrics
- [x] Provider/error signal normalization
- [x] AIMD controller
- [x] Cooldown/hard limits
- [x] Nested thread budget
- [x] Decision persistence
- [x] Static/auto benchmark

**验收**：压力下降并发、健康 backlog 缓慢上升；无振荡测试失败；所有改变有解释。

## Batch 8 — UX and reporting

- [x] `init/validate/run/status/cancel/report/export`
- [x] Rich/plain terminal status（避免强依赖可选）
- [x] JSON/CSV export
- [x] Static HTML report
- [x] Task timeline
- [x] Policy comparison charts/tables
- [x] README quickstart
- [x] Example manifests
- [x] Demo script

**验收**：干净机器按文档可完成 fake demo；有 Codex 的机器可完成 live demo。

## Batch 9 — Release hardening

- [x] Fault injection suite
- [x] Restart/orphan reconciliation
- [x] Security review checklist
- [x] Data redaction settings
- [x] Packaging/PyPI dry run
- [x] macOS/Linux CI matrix
- [x] Docs site
- [x] Benchmark raw data bundle
- [x] Known limitations
- [x] Release notes

**验收**：Go/No-Go 标准全部过，或明确 No-Go。

## Batch U1 — WorkRequest CLI and foreground TUI

- [x] 以 `WorkRequest` 统一 inline、file、stdin、clipboard 输入
- [x] `fg` 无参数进入多行需求输入，`fg "..."` 直接进入规划执行流
- [x] `fg plan/run/clip/status/logs` 复用正式 planning、scheduler 和 persistence 接口
- [x] TUI 展示 validated plan、依赖、路径、verifier 和推荐并行度
- [x] 前台运行面板只读取 scheduler-owned SQLite 状态
- [x] Repository scanner 仅纳入 tracked/non-ignored 文件，排除本地 state/worktree 噪声
- [x] 交互支持执行、导出编辑、强制单任务和取消
- [x] v0.1 `issue` plan YAML 可继续读取；新 plan 使用 `request` 命名
- [x] 同时发布 `firstgreen` 与 `fg` console scripts
- [x] README、ADR、单元和集成测试

**验收**：无需先创建 issue 文件即可完成 request → plan → approval → production scheduler
dry-run/fake-run；TUI 不拥有状态迁移、verification 或 winner 逻辑。

## Batch U2 — Live runner reliability

- [x] `fg run/request` 支持显式 worker model、reasoning effort 与 Codex binary
- [x] resolved worker 配置写入不可变 manifest 与 attempt snapshot
- [x] `doctor` 与 run preflight 同时检查 binary、`exec --help` 和必需参数
- [x] 默认显式关闭开发中的 `code_mode` 与缺少 sidecar 时不可用的 `code_mode_host`
- [x] agent 未完成、verifier 失败和 verifier 通过路径均写入 attempt `finished_at`
- [x] 当前进程取消时终态化 run/task/attempt，并等待 worker cancellation/安全 cleanup
- [x] `verification_runs` 持久化命令状态、退出码和时间戳
- [x] verifier 输出仅保存大小与 SHA-256 元数据，不落盘原始 stdout/stderr
- [x] status/report JSON 包含 verifier 记录；敏感 worker event 过滤保持不变
- [x] Windows Git/worktree、失败 verifier、取消 cleanup 与 CLI override 回归测试

**验收**：非 live 测试 159 collected、0 failures、0 errors、11 live skipped；真实历史仓库
post-fix smoke 仍需用户显式启动，不能在修复验证前宣称 live E2E 通过。

## Batch U3 — Deterministic verifier recovery

- [x] 裸 verifier executable 在启动前按 `PATH` 显式解析为绝对路径，规避 Windows host Python 抢占
- [x] `--verifier-python` 可将 `python/python3` 固定到目标仓库解释器并写入 resolved manifest
- [x] launch failure 仅持久化 resolved executable 与结构化错误类型，不保存原始敏感输出
- [x] SQLite v2 migration 为 verification 增加 round，旧审计行无损迁移为 round 1
- [x] `fg reverify` 只重跑 verifier，不启动 worker，不调用 Codex
- [x] reverify 要求原 manifest 字节哈希、数据库身份、专属 root、marker 与 Git 注册全部匹配
- [x] reverify 仅支持无 winner 的失败单任务 run，并限制最多三轮
- [x] 通过的 reverify 仍使用原子 winner 事务；重复调用不能产生第二个 winner
- [x] manifest 篡改、marker 篡改、重复重验、迁移和 CLI 路径均有回归测试

**验收**：真实 Codex worker 已在隔离 worktree 产生满足回归测试的补丁；历史 run 因 Windows
将裸 `python` 解析到不含 pytest 的 Codex runtime 而被正确拒绝 winner，随后同 attempt 的
round-2 reverify 已通过并由原子事务提交 winner。该批次 checkpoint 的 credential-free 完整
套件为 170 collected、159 passed、11 opt-in live skipped。

## Batch U4 — Approval and final-evidence UX

- [x] 计划审阅页展示原始请求、任务边界、allowed write paths、DAG、conflict locks 与逐条 verifier
- [x] 审批文案明确 worker 尚未启动，并保留 approve/edit/single/cancel 四个显式分支
- [x] 运行结束页只使用 persisted scheduler state、verification rows 与事务 winner，不信任 agent 自报
- [x] 结束页展示全部 attempt/worktree、验证轮次与 exit code、changed/disallowed paths 和后续命令
- [x] 失败 run 输出可复制的原 attempt `reverify` 命令；成功 run 明示 main working tree 未 merge
- [x] Codex filtered events 汇总 token usage；fake/未上报 adapter 明示 unavailable
- [x] 每个 run 自动生成 static HTML，并保留非交互 CLI 的稳定 JSON 结果
- [x] CLI/TUI、report aggregation、自动报告与失败恢复提示均有单元/集成回归测试

**验收**：credential-free 完整套件 178 collected、167 passed、11 opt-in live skipped；Ruff
format/check 与 mypy 全绿。TUI 不拥有状态迁移、verification 或 winner 逻辑。

## Batch R1 — Turnkey launcher and local defaults

- [x] Windows source launcher `fg.ps1`/`fg.cmd` 可直接进入正式 CLI/TUI
- [x] 用户级安装脚本安装 wheel 并创建 Start menu shortcut
- [x] `fg configure` 持久化非 secret 的 binary/model/reasoning/planner/state defaults
- [x] Codex discovery 优先使用 explicit/config/env/`CODEX_HOME/.sandbox-bin`，最后才查 PATH
- [x] `--auto-codex` 只运行 version/help preflight，不产生认证 turn 或 API 费用
- [x] 无参数交互入口在读取 prompt 前完成 Codex preflight，并复用缓存避免重复探测
- [x] 用户配置使用 strict schema、atomic replace，明确拒绝未知 secret 字段
- [x] source launcher、配置 round-trip、默认值应用、候选顺序和 early preflight 有回归验证

**验收**：本机 source launcher 返回版本；`--auto-codex` 跳过 ACL 拒绝的 WindowsApps binary，
成功选择 `D:\ProgramData\CodexHome\.sandbox-bin\codex.exe`，未启动 live turn。

## Batch R2 — Multilingual and inspectable planning

- [x] deterministic classifier 与 fake semantic planner 识别常见中文 schema/service/API/mail/test/docs 概念
- [x] 中文复杂请求生成 bounded work units、artifact edges、DAG、conflict locks 与 verifier
- [x] 显式 `--planner-provider codex` 在 auto mode 始终进行一次 bounded read-only proposal call
- [x] planner 与 worker 复用 selected Codex binary；plan/run/clip 均传递 planner model 与 binary
- [x] planner process launch/timeout/schema failure 只记录安全 error type，并明确显示 fallback
- [x] 失败 fallback 不写入成功 cache，后续相同请求仍可重试 planner
- [x] TUI edit action 打开本地编辑器，关闭后重新 scan/validate/persist 并回到审批页
- [x] edited plan 不得改变 repo/base SHA；审批前再次执行 deterministic validation

**验收**：中文示例在本仓库生成 3-task DAG（data-model → service-logic → api-layer）；Codex
binary/model 贯通由无费用 adapter test 验证，真实 planner turn 保留到最终显式额度验收。

## Batch R3 — Repository view consistency

- [x] 默认阻止脏仓库，错误中给出有界的 changed-path 摘要和显式恢复选项
- [x] `--dirty-mode head` 在 FirstGreen 状态目录创建固定 SHA 的干净 clone
- [x] `--dirty-mode snapshot` 只在 managed clone 内捕获 tracked/untracked/deleted 改动并提交
- [x] ignored 文件不进入 snapshot；变更的 symlink、非普通文件和仓库内部 state root 被拒绝
- [x] 原仓库的 working tree、index、HEAD 和 `.git` 在 snapshot 前后保持不变
- [x] planner、scheduler、attempt worktree 和 verifier 使用同一 execution repo/base SHA
- [x] source/execution repository、mode、dirty entries 和 base SHA 进入 plan/manifest/policy snapshot
- [x] fake scheduler E2E 验证 managed snapshot 可创建 winner 且原仓库状态不变

**已知限制**：managed repository views 当前作为审计和 winner worktree 的上游被保留，尚无带
marker 双确认的独立回收命令；用户需留意 `STATE_DIR/repository-snapshots` 的磁盘增长。

## Batch R4 — Deterministic verifier environment discovery

- [x] 从原 source repository 自动检测 `.venv`/`venv`，managed snapshot 不丢失 ignored 环境
- [x] repository environment 优先于 PATH；`--verifier-python` 保持最高优先级
- [x] virtualenv interpreter symlink 保留其逻辑路径，不因 `resolve()` 丢失 `pyvenv.cfg` 语义
- [x] 所有非 shell 裸 verifier executable 在 worker 启动前绑定到绝对路径
- [x] 缺失 verifier 直接阻止 run，数据库中不会产生已启动 worker 的假象
- [x] pyproject dependencies/dependency groups 与常见配置文件可生成 pytest/Ruff/mypy 命令
- [x] environment mode、root、resolved executable 和 warning 写入 manifest/policy snapshot

**已知限制**：环境检测不会自动创建 venv 或安装依赖，也不会执行 Poetry/Pipenv 等可能改变
环境的命令；显式 `shell: true` verifier 只能在实际运行时由 shell 解析。

## Batch R5 — Unified final delivery worktree

- [x] 多任务 DAG 完成后从同一 base SHA 创建专属、带 marker 的 delivery worktree
- [x] 仅组合 verified DAG sink snapshots；共同祖先的相同内容自动去重
- [x] 多 sink 对同一路径产生不同内容时安全失败，不按复制顺序静默覆盖
- [x] delivery 使用全任务 verifier 的确定性去重并集，并执行 allowed-path 合集约束
- [x] aggregate verifier 未通过时 run 不得标记 completed，即使所有 task winner 已产生
- [x] delivery 状态、workspace、diff hash、验证行和安全 error kind 持久化到 SQLite
- [x] terminal/status/JSON/HTML report 显示唯一 final delivery；CLI compact JSON 返回路径
- [x] delivery 失败时 workspace 与全部 task winner 均保留；主 working tree 不被修改

**已知限制**：delivery 是未自动提交的专属 worktree，仍需用户检查后手工 commit/cherry-pick；
当前不提供跨 run 自动回收或自动 merge。

## Batch R6 — Bounded live multi-task acceptance

- [x] Live planner and coding modes reject `all`; one explicit allowed scenario is mandatory
- [x] Paid coding requires an explicit model and acknowledged `--max-live-tasks` ceiling
- [x] Live manifests enforce `workspace-write`, one primary attempt per task, one nested agent
  thread, disabled hedging, and a bounded 60–1800 second per-attempt timeout
- [x] Codex binary, model, reasoning effort, task count/limit, timeout, usage, cost, attempts, wall
  time, and final-delivery verification are retained in acceptance evidence
- [x] S2/S3 multi-task acceptance uses the production scheduler and requires the aggregate delivery
  worktree to verify; it does not use a test-only scheduling path
- [x] Direct live pytest selection requires one exact scenario so a single environment variable
  cannot accidentally run the whole paid matrix
- [x] Missing credentials/opt-in truthfully skip live tests; failed live workspaces are preserved
- [x] Local `codex exec --help` was checked against the command builder before this batch
- [x] Managed repository, worktree, and Git ref names use short collision-resistant identifiers so
  ordinary long Windows state paths do not fail at the legacy Git path boundary

**Known limitation**: this batch did not spend quota on an authenticated model turn. The installed
CLI does not expose a reliable preflight price or billable-cost limit, so monetary spend cannot be
hard-enforced locally; reported usage/cost remains `null` when the CLI omits it. Scenario, task,
attempt, nested-thread, concurrency, and timeout limits are the enforceable safeguards.

## 当前已知限制（2026-07-22）

- WindowsApps Codex binary 可发现但被本机 ACL 拒绝执行。App 提供的 `.sandbox-bin` CLI 在
  默认关闭不完整 code-mode features 后，已在三个本地历史任务中完成认证编辑、deterministic
  verifier 与 winner 提交；其中一例通过同 attempt 的 round-2 reverify 恢复。该结果不是远端
  CI 或所有 CLI bundle/model 的普遍保证。
- macOS/Linux CI matrix 已配置但只能由远端 GitHub Actions 实际执行；本机验证为 Windows best-effort。
- one-shot CLI 的跨进程 `cancel` 只持久化取消状态；没有 daemon 时无法保证附着并终止另一个 CLI 的在途子进程。
- delayed hedge/always-race 已接入 one-shot manifest runner；fake E2E 覆盖 backup 获胜、primary
  取消清理和 winner 保留。真实 Codex 已验证 single worker 的编辑与 winner 路径；真实多 worker
  hedge 仍需要独立、显式的额度 opt-in。
- AIMD controller 已接入 one-shot ready-loop，按 host/queue/provider 快照在线调整 batch admission；root semaphore、hard limits、nested thread cap 和每次 old/new/reason 决策均持久化。短 run 可能因 cooldown/样本不足保持 initial limit。
- 原生 Codex client 取消不等于服务端计算立即停止；报告必须将 cancellation 标为 best-effort。
- FirstGreen 不是容器/VM 沙箱；不可信仓库及 verifier 仍可能读取进程环境中的凭据。
- Repository scanner 是 bounded heuristics，不是 compiler-grade analyzer；Python 为首个 language profile。
- `--repo-map-cache` 预留但 shared repo-map cache、GitHub issue fetching 和 automatic replanning 尚未实现。
- Codex planner adapter 已实现但 live smoke 未运行；默认 fake planner 不产生凭据或 API 费用。
- Fake worker 只产生确定性事件并运行真实 workspace/verifier/scheduler 路径，不会语义实现用户的
  编码请求；它不能替代 live coding 质量验证。
- 前台 TUI 已可监视当前进程启动的 run；`--detach`、daemon、跨进程实时控制和浏览器面板尚未实现。
- `WorkRequest` 已是产品输入边界；SQLite v0.1 planning 表仍保留 `issue_text/issue_hash` 列名以避免破坏性迁移。
- `reverify` 目前只恢复终态 single-task run；它不会恢复并继续执行部分完成的多任务 DAG。

## Synthetic planning/scheduling testbed status（2026-07-14）

- [x] T0 — 将全部 fixture 要求映射到 FirstGreen 正式接口。
- [x] T1 — TinyShop baseline 的 37 个测试与 Ruff 通过；分页零值 bug 按要求尚未被
  baseline 测试覆盖。
- [x] T2 — issue、golden、candidate、hedge、metadata 与 JSON Schema 严格 loader。
- [x] T3 — S1–S6、F1、F2 语义规划校验；S6 保持人工审批阻塞。
- [x] T4 — S1–S3 通过 SchedulerService、Git worktree、verified dependency overlay、
  CommandVerifier 与 SQLite winner arbitration 执行；S4 冲突串行有测试。
- [x] T5 — scheduler-level delayed hedge、hedge 验证失败、重复完成 winner race、重复取消、
  重复 cleanup 与 replay-unsafe fallback。
- [x] T6 — opt-in live planner matrix 与 keyed cache；没有显式凭据时不运行。
- [x] T7 — opt-in live coding 仅限 S1–S3 且关闭 hedge；没有显式凭据和预算时不运行。
- [x] T8 — JSONL、Markdown、plan YAML、timeline JSON 报告与复现文档。

已知 testbed 限制：H1 使用缩短的确定性时间；live Codex 结果依赖本机环境；当前原生
Windows 验证不代替配置中的 macOS/Linux CI。失败与 winner worktree 有意保留在忽略的
testbed runtime root 内。

## 明确禁止的 scope creep

在 Batch 0–8 完成前，不做：

- Web SaaS；
- React dashboard；
- GitHub App；
- 自动 PR/merge；
- Claude adapter；
- Kubernetes；
- remote runners；
- LLM task planner；
- ML/RL scheduler；
- symbol-level conflict predictor；
- 自动修改用户 verifier；
- token-level inference proxy。
