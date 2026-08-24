# 发布清单

本清单的目的不是把项目包装成“创业产品”，而是保证同一个版本的代码、数据、报告和
公开口径能够互相核对。任何一项证据失败都可以诚实发布；静默缺失、版本错配和夸大结论
不可以发布。

## 1. 冻结身份

- [x] 确认公开项目名、包名和商标风险；README 明确 FirstGreen 是 development codename。
- [x] 作者使用 GitHub 用户名 `Perilla-desuwa`；仓库 URL 已冻结，ORCID 和公开邮箱省略。
- [x] `CITATION.cff` 已填写作者、仓库、版本、日期和许可证，并通过 YAML 解析。
- [x] 版本号保留 `0.1.0-rc1`，作为后续施工锚点。
- [x] `pyproject.toml`、release notes、报告和 artifact metadata 使用同一 RC 版本。
- [x] 构建仅从 `git archive HEAD` 取 tracked source；私人企划书、视频草稿和本机目录不纳入。

## 2. 冻结证据

- [x] E0–E6 每项都有 observed、failed、invalid、interrupted 或 not-run 的显式状态。
- [x] Ramsey `1/2/4/8 × 2` 没有静默缺 cell；输入 hash 与 runbook 一致。
- [x] TinyShop 和 JavaScript 只支撑 end-to-end/product-path 结论，不混进 scaling 百分比。
- [x] stable/critical-path 只改变 ready-queue policy，三次重复均保留。
- [x] 所有失败、负加速、sequential extraction、timeout 和 verifier rejection 都保留。
- [x] 汇总可以从 append-only raw journal 重建，且重建结果一致。
- [x] README 表格、`results.tex`、图和 summary 中的数字逐项交叉核对。

## 3. 隐私与安全检查

- [x] 归档构建执行私人路径、邮箱线索和常见凭据形式扫描。
- [x] 不发布原始 prompts、隐藏 reasoning、完整 agent messages 或未过滤事件 payload。
- [x] JSON/trace 仅使用已审查的 sanitized public exports；不纳入本机 SQLite/HTML。
- [x] 不归档 worktree、`.git`、`.firstgreen`、credential store、缓存或进程日志全文。
- [x] `SECURITY.md` 和 known limitations 明确说明 worktree 不是容器安全边界。

## 4. 重建与质量门

- [x] clean clone 初始状态干净；wheel 安装、版本、Manifest 校验和一格 scripted evidence 通过。doctor 的 Codex 子进程权限阻断已记录。
- [x] Ruff check、Ruff format check、mypy、pytest 全绿；live tests 在正常 CI 中仍关闭。
- [ ] Windows CI 绿；至少再确认一个非 Windows CI 环境。
- [x] wheel 可在全新 target 中安装，版本为 `0.1.0rc1`，CLI `--help` 可运行；sdist 内容已展开审查。
- [x] 技术报告从 `technical-report.tex` 严格编译，五页逐页检查无溢出、空图或 placeholder。
- [x] README 所有本地相对链接目标存在；GitHub 实际渲染待远程发布后复核。

## 5. 口径审查

- [x] 逐行通过 `claim-evidence-matrix.md`。
- [x] 首页先说明 Parallelism Extraction + Scheduling，证据紧随其后但不冒充核心功能。
- [x] scripted 数据明确标为 orchestration/capacity evidence。
- [x] live 结论含 workload、model、host 和 repetition 范围。
- [x] 不声称普遍加速、成本下降、生产安全、集群能力或已同行评审。
- [x] negative result 和 threats to validity 在 README/报告中可见，而非藏在附录。

## 6. 发布资产

- [x] 生成 wheel、sdist、evidence zip、zip checksum 和 technical-report PDF。
- [x] evidence zip 内容符合 `artifact-manifest.md`，49 个内部文件哈希复核通过。
- [x] GitHub Release 正文由 `release-body.md` 填写，不含 placeholder，并附证据包 SHA-256。
- [ ] 创建不可变 tag，并确认 tag commit 等于报告与 metadata 中的 code commit。
- [ ] 下载已发布资产，在另一个临时目录复核 checksum 和最小重建命令。
- [ ] 发布后再制作项目页、视频或简历文案；它们统一链接到这一版 Release。
