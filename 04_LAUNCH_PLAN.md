# FirstGreen 发布与市场验证计划

## 1. 首发目标

首发不是追求“大而全”，而是验证三个命题：

1. 用户是否真的在意 coding-agent 的 P95 time-to-green；
2. selective delayed hedge 是否比 always-race 更容易被接受；
3. 用户是否愿意把多个任务交给外层 scheduler，而不是手动管理 Codex sessions。

## 2. 首发版本叙事

**标题**：Codex 已经会并行，为什么还需要一个调度器？

**副标题**：FirstGreen 只在任务进入长尾时启动 backup，并让第一个通过测试的结果获胜。

**三张核心图**：

1. Single vs Always-race vs Delayed hedge 的 P95 time-to-green；
2. P95 improvement vs extra attempt-time/token；
3. Fixed concurrency vs Auto concurrency 的 verified throughput。

## 3. 资产清单

- GitHub repo；
- README；
- 90 秒 demo GIF/视频；
- 完整 8–12 分钟技术视频；
- 可复现 benchmark config；
- raw JSON/CSV 数据；
- HTML report 示例；
- 架构图；
- 安全边界；
- 竞品对比；
- roadmap；
- issue templates；
- contributing guide。

## 4. README 首屏结构

1. 一句话价值；
2. 一张真实 benchmark 图；
3. 30 秒安装运行；
4. delayed hedge timeline；
5. “Why not native Codex subagents?”；
6. 安全与限制；
7. Roadmap。

## 5. 发布平台顺序

1. GitHub + PyPI + GitHub Pages；
2. Bilibili / YouTube 技术视频；
3. Show HN；
4. X / LinkedIn；
5. OpenAI developer / coding-agent 社区；
6. Reddit 合适版块；
7. Product Hunt 作为第二波。

## 6. 早期用户访谈问题

- 你同时跑过多少个 coding-agent tasks？
- 哪一类任务最常卡在长尾？
- 你如何定义“完成”？
- 你会为降低 P95 等待多付多少 token/attempt？
- 你现在如何限制 root sessions 和内部 subagents？
- 最痛的是 API rate limit、测试资源、冲突、失败还是人工 review？
- 你愿意写 YAML verifier contract 吗？
- 你更需要本地工具、GitHub App 还是团队 dashboard？

## 7. 不应做的营销承诺

- 不声称普遍节省固定百分比；
- 不声称首个多 Agent scheduler；
- 不声称替代 Codex/Symphony/Bernstein；
- 不声称可以完全停止供应商侧计费；
- 不声称 verifier 等于代码正确；
- 不声称支持所有 Agent；
- 不把 simulator 结果当真实生产结果。

## 8. 反馈到 roadmap 的判定

- 大量用户只需要任务队列：优先 Symphony/issue tracker adapter；
- 用户已有多供应商需求：加 Generic subprocess，再加 Claude；
- 用户最痛是 CI/test contention：深化 resource leases 和 test scheduler；
- 用户最痛是 merge conflicts：加 conflict-aware admission；
- 用户愿意共享匿名历史：建设公共 scaling corpus；
- 用户不愿写 verifier：做模板检测和 human-confirmed generation，但不自动信任 LLM。
