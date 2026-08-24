# FirstGreen HPC Runtime 执行清单

> 对应路线图：[ROADMAP.md](ROADMAP.md)
>
> 状态约定：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成，`[!]` 阻塞或降级
>
> 提交规则：每个可独立验收的批次完成质量门后更新本文件，并单独提交。

## 当前进度

- [x] 路线图收敛为 Parallelism Extraction + Agent Scheduling
- [x] 阶段 A：核心合同与基线
- [x] 阶段 B：Parallelism extraction
- [x] 阶段 C：Scheduling runtime
- [x] 阶段 D：scripted、Ramsey Luna 完整矩阵、两个 case study 与 CP ablation 均已完成
- [~] 阶段 E：本地 RC、发布正文与最终图已完成；clean-clone 归档、远端 CI、身份信息与 tag 待完成

## A. 核心合同与基线（D1–D2）

- [x] A-01 明确 `Goal → CandidatePlan → ApprovedPlan → Manifest → Run` 合同
- [x] A-02 明确 benchmark 只重放 frozen approved plan，不拥有平行模型
- [x] A-03 审计当前 dirty working tree，并形成可解释的基线提交
- [x] A-04 修复或确认 admission 前 workspace cancellation cleanup
- [x] A-05 修复或确认已有 metrics / verifier repair 改动
- [x] A-06 运行完整工程质量门（225 passed，1 skipped，11 live deselected）
- [x] A-07 同步 README、known limitations 和 release notes 的当前能力口径

## B. Parallelism Extraction（D3–D7）

- [x] B-01 标准化 repo + goal 产品入口，保留 authored-plan bypass
- [x] B-02 审核 bounded repository scan 与 semantic work-unit proposal
- [x] B-03 确认 deterministic artifact edges、cycles、paths 和 verifier eligibility
- [x] B-04 确认 write conflicts 编译为 capacity-one resources
- [x] B-05 为 work unit 增加 duration estimate 与 estimate source
- [x] B-06 计算并持久化 work、span、critical path、ready width
- [x] B-07 生成有上下界、可解释的 recommended root slots
- [x] B-08 在 plan view 中展示 parallelism analysis 后再审批
- [x] B-09 Python/JavaScript 两个 repo + goal 完成 vertical slice
- [x] B-10 sequential goal 明确报告 insufficient parallelism
- [x] B-11 worker handoff 明确 peer ownership boundaries 与实际 verifier commands

## C. Agent Scheduling Runtime（D8–D13）

- [x] C-01 统一 production ready loop 与 scheduler queue
- [x] C-02 保留 stable baseline policy
- [x] C-03 实现 critical-path / bottom-level rank policy
- [x] C-04 持久化 ready rank、selection 与 estimate source（ready-set event 留待 D-01）
- [x] C-05 统一 dependency、resource、root slot 与 thread admission
- [x] C-06 将 verifier slots 接为 service-wide shared capacity
- [x] C-07 记录 verifier queue wait（pressure feedback 留待 C-08/D-02）
- [x] C-08 校验 bounded AIMD、static fallback 和 decision log
- [x] C-09 分离 tail hedge、failure retry 与 repair 记账
- [x] C-10 launch_hedge 记录 ready work 与共享 root-slot competition
- [x] C-11 approved plan 完成 parallel run 与 final verified delivery
- [x] C-12 deterministic branch/join DAG 两槽快于一槽

## D. Runtime Observability 与 Evidence（D14–D17）

- [x] D-01 补齐 ready/admit/run/verify/integrate lifecycle events
- [x] D-02 计算 utilization、agent-seconds 与诊断性 idle-reason observations
- [x] D-03 导出 sanitized Perfetto/Chrome Trace
- [x] D-04 实现 frozen-Manifest 薄 matrix driver
- [x] D-05 append-only raw journal 与可重建 summary
- [x] D-06 scripted 1/2/4/8/16 accounting/trace checks
- [x] D-07 历史 Luna S3 2-way controlled-live 已保留；原定 1/4/8 对照由冻结 Ramsey 矩阵取代，不属于 v1 protocol
- [x] D-07a Ramsey v2 frozen contract、preflight、`1/2/4/8 × 2` raw journal 与 verified delivery 已完成
- [x] D-08 stable / critical-path scheduler 单元与 production selection 对照
- [x] D-09 Python/JavaScript 两个 end-to-end extraction demos
- [x] D-10 fixed-delay hedge / bounded AIMD targeted tests 已保留
- [x] D-11 live maximum parallelism 从 persisted attempt intervals 计算，不再依赖 fake counter
- [x] D-12 冻结个人项目最小公开 evidence protocol，禁止结果后调参
- [x] D-13 冻结独立 JavaScript idempotent-checkout 案例设计、source/base SHA 与 issue hash
- [x] D-14 冻结 stable / critical-path 非对称 scripted ablation Manifests
- [x] D-15 运行 TinyShop S3 Luna 两槽 end-to-end case study；两次完整观察均交付 verified，但均为 ready width 1 的负 extraction 结果
- [x] D-16 运行 stable / critical-path scripted ablation，各三次；固定 2 root / 1 verifier，critical-path median wall 低 13.56%
- [x] D-17 独立 JavaScript source/base、Luna candidate、审批与 Manifest hashes 已冻结
- [x] D-18 运行独立 JavaScript Luna end-to-end case study 一次；ready width 2、实际并行、9/9 final tests
- [x] D-19 TinyShop S3 Luna 完整 live launcher 已准备并有双重 opt-in
- [x] D-20 JavaScript source/issue/base preflight 与 staged planner/worker launcher 已准备
- [x] D-21 Ramsey、TinyShop、JavaScript 统一 no-live readiness preflight 已准备
- [x] D-22 Ramsey v2 Luna `1/2/4/8 × 2` 已完成，8/8 cells 与 final delivery 均 verified

## E. Release（D18–D20）

- [x] E-01 README 首屏先展示产品闭环，再展示 scripted scaling evidence
- [x] E-02 30 秒 quickstart 运行 planning + scheduling
- [x] E-03 benchmark 复现作为第二条命令
- [x] E-04 methodology/invalid/negative protocol 已公开；Ramsey 与两个 case study 的 sanitized live evidence 已记录
- [x] E-05 Apache-2.0、`0.1.0rc1` 与 release notes 对齐
- [x] E-06 clean clone 重建 scripted summary、wheel 与 sdist
- [!] E-07 仓库未配置 remote，无法确认远端 CI
- [!] E-08 已降级并构建 `0.1.0rc1`；tag/push 由 owner 发布
- [x] E-09 冻结公开作品的发布形态：repo → tagged Release → evidence bundle → technical report
- [x] E-10 完成 technical report LaTeX 正文、集中式结果宏与 figure naming contract
- [x] E-11 完成 claim/evidence matrix、artifact manifest、reproducibility 与 release checklist
- [x] E-12 Ramsey、case study 与 CP ablation 数据、README、trace 与主结果图已回填
- [ ] E-13 从 clean clone 编译报告、打 evidence zip，并复核全部 checksum/link/TBD
- [ ] E-14 填写作者与远端地址，把 `CITATION.cff.template` 定稿为 `CITATION.cff`

## 每批提交前检查

- [x] `git diff --check`
- [x] `uv run ruff check .`（本机等价 `.deps/bin/ruff.exe`）
- [x] `uv run ruff format --check .`（本机等价 `.deps/bin/ruff.exe`）
- [x] `uv run mypy src tests`（本机 repo-local dependency runtime）
- [x] `uv run pytest`（最近完整门禁：247 passed，12 skipped）
- [x] 清单勾选与实际证据一致
- [x] 提交只包含当前批次及必要依赖
