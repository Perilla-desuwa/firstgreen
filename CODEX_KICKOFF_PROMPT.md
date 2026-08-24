# 可直接粘贴给 Codex 的启动指令

你现在要实现一个名为 **FirstGreen（开发代号）** 的开源项目：一个 Codex-first、local-first 的 verified coding-agent fleet scheduler。

请先完整阅读当前目录中的：

1. `01_PRODUCT_PLAN_AND_PRD.md`
2. `02_TECHNICAL_SPEC.md`
3. `03_IMPLEMENTATION_BACKLOG.md`
4. `examples/fleet.yaml`
5. `AGENTS.md`

## 产品核心，不得偏离

- Codex 负责执行；本项目负责 fleet-level 调度。
- Agent 自报完成不算成功，scheduler-owned deterministic verifier 通过才算 green。
- 默认只启动一个 primary；只有 replay-safe 任务超过 threshold 时才 delayed hedge。
- 第一个 verifier pass 的 attempt 原子获胜，其余 attempts best-effort cancel。
- 必须同时控制 root concurrency、verifier slots 和 Codex `agents.max_threads` 上限。
- 所有自动决策必须有 hard limits、static fallback 和 structured decision log。
- MVP 不自动 merge/push，不做 SaaS，不做多供应商，不做 React dashboard。

## 你的第一轮工作

只完成 **Batch 0 — Bootstrap**，不要提前实现真实 Codex adapter 或完整 scheduler。

具体要求：

1. 检查当前目录，如果还不是仓库则初始化项目结构；
2. 创建 Python 3.12 `src/` layout 和 `pyproject.toml`；
3. 配置 Typer、Pydantic v2、PyYAML、SQLAlchemy/Alembic、pytest、pytest-asyncio、Ruff 和静态类型检查；
4. 创建主包 `src/firstgreen/`；
5. 创建 `firstgreen --help` 的最小 CLI；
6. 创建 `docs/adr/`，写入以下 ADR：
   - local-first；
   - Codex Exec first, App Server later；
   - SQLite WAL；
   - deterministic verification；
   - no auto-merge in MVP；
7. 添加 GitHub Actions 执行 lint、typecheck、tests；
8. 添加最小单元测试；
9. 不要添加任何 UI、云服务、GitHub App 或其他 Agent adapter；
10. 完成后运行所有检查，修复到全绿。

## 工作方式

- 先输出你理解的架构边界和本批次文件变更计划；然后直接实施，不要等待确认。
- 每次只做当前 batch；不要用“顺手”扩展 scope。
- 遇到文档冲突时，优先保证安全 invariant：no double winner、no workspace corruption、verification-owned truth、replay-safe-only hedge。
- 不要硬编码尚未验证的 Codex CLI flags；真实 adapter 阶段必须先运行本机 `codex exec --help` 并对照官方文档。
- 代码必须可测试；时间、worker、数据库和文件系统边界应可注入或封装。
- 不读取、不记录、不依赖隐藏 chain-of-thought。
- 对任何不确定的外部 API，先建立 interface 和 fake，不要猜测实现。

## 本批次完成时的输出

- 变更摘要；
- 项目树；
- 执行过的命令及结果；
- 尚未实现的内容；
- 下一批次 `Batch 1 — Domain and persistence` 的建议起点，但不要开始 Batch 1。
