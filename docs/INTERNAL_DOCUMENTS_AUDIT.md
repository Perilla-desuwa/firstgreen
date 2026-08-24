# FirstGreen 内部文档盘点与治理建议

> 审计日期：2026-08-13
>
> 审计范围：仓库内 Markdown/TXT 文档、测试规格、示例、生成报告、视频草稿与对外企划书
>
> 审计性质：事实盘点，不代表公开发布声明
>
> 版本状态：当前为未跟踪 draft，需由 owner 确认后纳入版本治理
>
> 后续执行纲领：[ROADMAP.md](ROADMAP.md)

> 叙事校正（2026-08-13）：本文的实现事实与文档治理结论继续有效；旧版关于“history-driven hedge 是下月唯一 scheduler feature”的优先级判断已被 HPC-first 路线图取代。FirstGreen 的产品主线现为 `repo + goal → parallelism extraction → Agent scheduling → verified delivery`；strong-scaling benchmark、work/span 图和 runtime trace 是验证与展示层。Verification 与 winner invariants 保留为正确完成和有效计时的边界。

## 1. 结论

FirstGreen 目前不缺文档，缺的是清晰的事实层级。

仓库里同时存在：

- 早期创业型产品 PRD；
- 初始技术规格和一次性 Codex 构建提示词；
- 已基本完成的工程实施台账；
- 当前 README 和安全边界；
- 合成 simulator/testbed 证据；
- 尚未闭合的真实 Codex 实验；
- 多个版本的视频脚本；
- 一份对外企划书。

这些材料各自有价值，但现在混合承担“设计愿景、当前事实、历史记录、未来计划和宣传素材”五种职责，导致部分未接通能力被写成已完成，部分候选发布被写得像正式发布。

本次整理采取两个原则：

1. 先建立一份新的权威路线图，不在脏工作区中批量移动旧文件。
2. 以后所有对外声明以代码、测试和可复现实验为准，不以 backlog 勾选或企划书表述为准。

## 2. 审计时的仓库状态

- 当前分支：`main`。
- 当前提交：`b808388`。
- 没有 Git tag，也没有配置远端仓库。
- 有 25 个已跟踪文件处于修改状态；另有未跟踪的代码、测试、视频稿和 Word 企划书。
- 当前未提交改动包含 verifier-failure repair、planner/path hardening、线程预算修正等重要行为，尚不能视为已发布能力。
- 2026-08-13 当前审计 working tree 的本地质量门为 237 collected：225 passed、12 skipped；其中 11 个是显式 opt-in live cases，1 个是 Windows 平台特定 skip。baseline commit 后必须重新生成，并保留 `pytest -rs` 的逐项原因；skipped 不能计作通过。
- `dist/` 中的 0.1.0 构建早于最新提交和当前工作区，不是可发布构建。

因此，本轮不移动、删除或重命名现有文档。先冻结代码基线，再做独立的纯文档重组提交。

## 3. 文档事实优先级

出现冲突时，按以下顺序判断事实：

1. 选定 commit/tag 的代码、数据库 schema、测试结果和 `AGENTS.md` 不变量；
2. 未提交 working tree 只算 `Draft`，形成可审查 checkpoint 前不是发布事实；
3. README、Known Limitations、Security、Release Notes；
4. ADR 和架构说明；
5. 当前 `ROADMAP.md` 与 evaluation protocol；
6. 历史 PRD、旧 backlog、启动提示词、企划书和视频脚本。

建议以后给非显然文档增加状态标签：

- `Normative`：当前必须遵守的工程合同；
- `Current`：当前实现或用户说明；
- `Planned`：已批准但未实现；
- `Historical`：历史设计，不代表当前能力；
- `Generated`：可由代码重新生成，不是人工事实源；
- `Draft`：尚未定稿的传播材料。

## 4. 最重要的文档—实现偏差

### 4.1 历史驱动 hedge 尚未接入生产路径

文档中已有历史分位数、runtime bucket 和 empirical quantile 的完整设计，backlog 也把它们标为完成。代码中确实存在：

- `runtime_samples` 表和读写接口；
- `RuntimeBucket`；
- `choose_threshold()`；
- `HedgePolicy`；
- 对应单元测试。

但生产 `SchedulerService` 仍直接读取 `fallback_after_seconds`，再把这个静态秒数交给 race coordinator。全仓没有生产代码写入 runtime sample，也没有生产调用 `choose_threshold()`。

正确口径是：

> 静态 delayed hedge 已接入；history-driven hedge 已有脚手架和单测，但尚未形成生产闭环。

它仍是有价值的 straggler-mitigation 后续能力，但不再是下一个月唯一新增的 scheduler 能力，也不阻塞 v0.1。P0 先闭合 parallelism extraction，并在调度侧实现 critical-path-aware ready queue；history/P90 hedge 降为 P1。

### 4.2 AIMD 已接入，但证据和信号范围有限

生产 ready-loop 会调用 AIMD controller，并持久化 old/new/reason。当前主要有效信号是 backlog、完成样本和主机 load/memory；provider rate limit、spawn error、verifier queue wait 和 cancellation backlog 尚未形成完整生产信号链。

因此可以称为“基础 AIMD admission control”，不应称为成熟 autotuner。当前 simulator 的 `auto` 与 `delayed-hedge` 使用相同逻辑，并没有模拟 AIMD。

### 4.3 金额预算是 schema，不是可靠的硬预算

金额字段存在，但安装的 Codex CLI 如果不提供可预检的 billable cost，FirstGreen 无法在运行前或运行中可靠按美元硬停。目前可强制执行的是任务数、attempt 数、并发、nested threads 和 timeout。

README 对这一点相对诚实；PRD 和示例 manifest 的表述更像完整预算能力。公开文档必须把 `null` 成本和不可硬执行的金额上限写清楚。

### 4.4 当前 benchmark 不是公开实证

- `benchmark simulate` 是固定 seed 的合成 workload。
- TinyShop testbed 证明 planning、worktree、verification、winner 和 failure invariant，但 fake worker 不实现真实语义任务。
- 已提交的 testbed 报告中 live planner/live coding 均为 `not_requested`。
- 本地历史记录能说明单 worker Codex 路径曾跑通，但没有可公开复现的多策略、真实任务、重复实验。
- `benchmarks/simulator-baseline.json` 只有配置和免责声明，没有数值结果。
- simulator 的 `auto` 不包含 AIMD，且当前 `wasted_attempt_seconds` 对 backup 获胜场景的口径需要修正。

因此现在首要缺口不是继续堆可靠性 feature，也不是把项目改造成 benchmark harness，而是把现有 repo-aware planning 提升为正式 parallelism extraction，把 approved DAG 的 work/span/criticality 接入 production scheduler，再用薄的 Scaling Bench 和 timeline 证明加速。P0 的两项核心能力是 parallelism extraction 与 critical-path-aware scheduling。

### 4.5 0.1.0 仍是候选，不是正式发布

- `pyproject.toml` 版本为 0.1.0；
- release notes 标为 MVP candidate；
- 仓库没有 tag 和 remote；
- 当前 wheel/sdist 已过时；
- macOS/Linux CI 配置存在，但当前本地 Windows 运行不能代替远端 CI 事实；
- 包名、项目名和商标尚未确认。

正式毕业时应从 clean tagged commit 重建，而不是复用当前 `dist/`。

### 4.6 开源法律和文档站尚未闭合

- 当前 `LICENSE` 是简化文本，不是完整 Apache License 2.0 标准正文；正式公开前需要替换并复核版权主体。
- `docs/index.md` 很短，`mkdocs.yml` 仅导航少量页面，不能把“docs site 已完成”理解为可对外浏览的完整文档站。
- `CONTRIBUTING.md` 只有最小工程要求，尚缺安装、PR、benchmark contribution 和安全报告流程。

### 4.7 `network_access=false` 不是已执行的网络隔离

`AgentDefaults` 和示例 manifest 有 `network_access=false`，但当前 Codex adapter 没有消费该字段，宿主上的 verifier subprocess 也没有网络隔离。Worktree 只隔离 Git 文件状态，不是容器或 VM。

因此公开文档只能把它写成配置意图。正式 live benchmark 必须核对确切 Codex CLI 能力，并用 sandbox + throwaway VM/防火墙做负向探针：Codex 控制面可连接 provider，但 repository/tool command 和 verifier 不得任意出网。否则不能声称已隔离 future fix 或不可信代码。

### 4.8 当前 hedge path 混合了长尾复制与失败重试

当前 delayed coordinator 在 primary 于 threshold 前 terminal-unverified 时也会立即启动 backup。这是 failure-triggered second attempt，不是 tail hedge。当前未提交 repair 又与 hedge 共用 `max_attempts`，直接拿四个 policy 比较会混入不同的 retry 机会。

另外，backup workspace 在获得 root slot 前就可能被创建；如果等待 admission 时被取消，存在留下无 attempt row worktree 的风险。两项都必须在基线冻结/Bench 阶段修正并加生产路径测试：主实验只允许“threshold 时 primary 仍 active”触发 backup，failure retry/repair 仅进入单独 demo。

## 5. 文件盘点与处置建议

### 5.1 根目录产品与工程文档

| 文件 | 当前角色 | 结论与处置 |
|---|---|---|
| `README.md` | 最接近真实实现的公开入口 | 保留；发布周压缩首页，把详细 CLI/reference 下沉 |
| `01_PRODUCT_PLAN_AND_PRD.md` | 初始产品/商业/技术总设计 | 标记 `Historical`，基线冻结后移入 archive |
| `02_TECHNICAL_SPEC.md` | 初始工程合同 | 提炼现行架构后归档原稿 |
| `03_IMPLEMENTATION_BACKLOG.md` | M0–R6 实施台账 | 保留为历史 ledger，不再承担未来 roadmap |
| `04_LAUNCH_PLAN.md` | 初始创业型发布计划 | benchmark 资产清单迁入新路线图，其余归档 |
| `04_PLANNING_SUBSYSTEM.md` | repository-aware planning 紧凑规格 | 暂保留，随后迁入 `docs/architecture/` |
| `AGENTS.md` | 工程宪法和不变量 | `Normative`，必须保留 |
| `CODEX_KICKOFF_PROMPT.md` | Batch 0 一次性提示词 | 已完成，归档 |
| `CODEX_AUTONOMOUS_MVP_PROMPT.md` | 一次性 MVP 构建合同 | 已完成，归档 |
| `CONTRIBUTING.md` | 最小贡献说明 | 保留，发布周扩写 |
| `FirstGreen_项目企划书.docx` | 未跟踪的对外沟通快照 | 当前不处理；由 owner 决定是否纳入 archive，不作为当前路线图或能力证明 |
| `src/firstgreen/db/migrations/README.md` | SQLite migration 约定 | 准确，原位保留 |

### 5.2 当前 `docs/`

| 文件 | 当前角色 | 结论与处置 |
|---|---|---|
| `docs/index.md` | 文档站首页 | 发布周重写为完整导航 |
| `docs/known-limitations.md` | 当前限制 | 保留；修正 empirical hedge 暗示 |
| `docs/release-notes.md` | 0.1.0 candidate 摘要 | 保留；tag 时补日期、commit 和 evidence 状态 |
| `docs/security-review.md` | 安全检查表 | 保留；公开前补 threat model/报告方式 |
| `docs/ROADMAP.md` | 下一阶段唯一执行纲领 | 新增，`Current` |
| `docs/INTERNAL_DOCUMENTS_AUDIT.md` | 本次文档审计 | 新增，作为重组依据 |

### 5.3 ADR

以下决策仍有效，应全部保留：

- `docs/adr/001-local-first.md`
- `docs/adr/002-codex-exec-first.md`
- `docs/adr/003-sqlite-wal.md`
- `docs/adr/004-deterministic-verification.md`
- `docs/adr/005-no-auto-merge.md`
- `docs/adr/006-work-request-terminal-shell.md`

ADR-001 至 ADR-005 公开前可补 Context、Alternatives、Consequences，但无需在 evidence sprint 前扩写。

### 5.4 Testbed 文档、fixture 与生成报告

应保留为系统正确性证据：

- `tests/firstgreen_testbed_package/README.md`
- `tests/firstgreen_testbed_package/TESTBED_SPEC.md`
- `tests/firstgreen_testbed_package/IMPLEMENTATION_MAP.md`
- `tests/firstgreen_testbed_package/tinyshop/README.md`
- `issues/S1_*.md` 至 `issues/S6_*.md`
- `golden/S1.yaml` 至 `golden/S6.yaml`
- `fakes/*.json`、`fakes/*.yaml`
- `schemas/*.json`

应标记为历史构建提示词：

- `tests/firstgreen_testbed_package/CODEX_AUTONOMOUS_TESTBED_PROMPT.md`

应视为 `Generated`、在 clean commit 上重新生成：

- `reports/summary.md`
- `reports/results.jsonl`
- `reports/plans/*.yaml`
- `reports/timelines/*.json`

重新生成时必须记录 FirstGreen commit、环境、策略、生成日期、复现命令以及 synthetic/live 标签，并去除本机绝对临时路径。

### 5.5 示例与 benchmark 资产

应保留：

- `examples/fake.yaml`
- `examples/live.yaml`
- `examples/simulator.yaml`
- `examples/issue.md`
- `examples/fleet.yaml`
- `benchmarks/simulator-baseline.json`

但发布前需要：

- 明确 `fleet.yaml` 中 quantile、金额预算等字段哪些已接通，哪些只是完整 schema 示例；
- 将 simulator baseline 明确标为 synthetic metadata，不把它当性能结果；
- benchmark 只重放正式 approved ExecutionPlan；新增薄的 suite/result schema 和版本化 raw data，不另建平行 job model。

### 5.6 视频材料

当前未跟踪材料包括：

- `docs/video/episode-01-storyboard-v0.md`
- `docs/video/episode-01-storyboard-v1.md`
- `docs/video/episode-01-voiceover-v0.md`
- `docs/video/episode-01-voiceover-v1.md`
- `docs/video/episode-01-tts-v2.txt`
- `docs/video/episode-01-tts-v3.txt`
- `docs/video/episode-01-tts-v4.txt`

版本号和实际时间顺序已有混乱。benchmark 结束后，先由 owner 确认哪些版本需要纳入仓库；若决定版本化，再收敛为：

- 一份 final storyboard；
- 一份 final TTS；
- 一份素材来源/事实核对说明；
- 经确认需要保留的旧版本移入 `docs/archive/media/`。

视频是 distribution layer，不应阻塞 Bench、真实实验或 v0.1。

### 5.7 临时与构建产物

- `.tmp/firstgreen_proposal/` 是企划书制作过程，不应公开。
- `.tmp/`、pytest 临时目录和 live replay 目录不是版本化证据。
- `dist/` 在毕业 release 时从 clean tag 重建。
- 仓库中没有需要整理的 RST 或 TeX 内部文档。

### 5.8 发布与治理配置

这些不是叙事文档，但决定公开仓库的事实边界：

| 文件 | 作用 | 发布前动作 |
|---|---|---|
| `LICENSE` | 法律许可 | 换成完整 Apache License 2.0 标准正文并确认版权主体 |
| `pyproject.toml` | 版本、依赖、构建和命令入口 | 与 clean tag 对齐，重建发行物 |
| `mkdocs.yml` | 文档站导航 | 补入 architecture、evaluation、ADR 和 reference |
| `.github/workflows/ci.yml` | macOS/Linux 质量门 | 以远端实际运行结果为准 |
| `.gitignore` | 临时、状态和构建物边界 | Bench 上线时复核 raw/public 与 local/private 目录 |

## 6. 目标文档结构

基线冻结后，另开一次只移动文档、不改代码的提交，逐步收敛为：

```text
README.md
AGENTS.md

docs/
  index.md
  ROADMAP.md

  architecture/
    overview.md
    planning.md
    scheduler.md
    verification-and-delivery.md

  adr/
    001-...

  evaluation/
    benchmark-protocol.md
    execution-plan-replay.md
    dataset-card.md
    runtime-tracing.md
    results/
      latest-summary.md
      raw/

  reference/
    cli.md
    configuration.md
    security.md
    known-limitations.md
    release-notes.md

  contributing/
    development.md
    benchmark-contributions.md

  media/
    episode-01/
      final-storyboard.md
      final-tts.txt
      sources.md

  archive/
    2026-07-initial-prd.md
    2026-07-technical-spec.md
    2026-07-implementation-ledger.md
    2026-07-launch-plan.md
    prompts/
    media/
```

## 7. 文档迁移顺序

1. 先完成当前工作区的 baseline audit、质量门和 checkpoint。
2. 更新 README/known limitations 中与真实实现冲突的表述。
3. 新建 architecture/evaluation/reference 目录及导航。
4. 只对已跟踪的历史文档使用 `git mv` 归档，同时一次性修复链接；未跟踪媒体和企划书需 owner 单独确认。
5. 在 clean commit 上重新生成 testbed 报告。
6. benchmark 完成后再收敛视频稿和发布材料。

任何物理移动都应在独立提交中完成，以便审查和回滚。
