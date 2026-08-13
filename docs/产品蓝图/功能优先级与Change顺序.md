# 功能优先级与 Change 顺序

[返回产品蓝图索引](../产品蓝图.md)

> 权威范围：功能阶段、明确非目标、验证指标、OpenSpec change 顺序与待验证问题。

## 功能清单与优先级

优先级定义：

- P0-A：可信整理闭环，没有它无法验证产品价值。
- P0-B：整理效率闭环，没有它可能技术可用但用户会被确认成本劝退。
- P1：形成 Grove 的目录共创与回忆差异化。
- P2：提高知识质量、媒介覆盖和通用性。
- P3：主动发现与平台化。

### 已有基础能力

当前仓库已经具备或已归档规格覆盖：

- 账号注册、登录、退出和会话；
- 默认个人 Workspace 与隔离；
- 项目创建、列表、重命名和删除；
- 多级目录节点创建、编辑、删除和排序；
- 前后端工程基础、AI Provider 抽象与 Demo Provider。

注意：当前“创建项目时选择 149 节点装修模板”的实现与本蓝图冲突，后续应改为默认空目录，并保留手建或 AI 共创入口。

### P0-A：可信整理闭环

- [ ] 项目说明可选字段；项目生命周期增加进行中、暂停、已完成、已归档。
- [ ] 默认空目录创建，移除装修模板作为产品默认路径。
- [ ] 图片批量上传、图片粘贴和文字粘贴采集。
- [ ] Source、Attachment、Processing Task 与版本化 Extraction。
- [ ] OCR 或多模态解析 Provider 评测与接入。
- [ ] Project Context Snapshot 初始版本：基于项目说明与正式目录生成，支持异步更新、失败回退、展示和纠正。
- [ ] Organizing Agent 基于 PydanticAI 输出结构化 Candidate。
- [ ] 语义拆分、推荐候选、其他发现和证据定位。
- [ ] 按 Source 审阅，逐条确认、编辑、拒绝和暂缓。
- [ ] 当前 Source 内多选确认或拒绝。
- [ ] 确认后创建 Entry，并保留 Candidate 与 Source 证据关系。
- [ ] Entry 卡片与列表两种视图。
- [ ] 按目录浏览，区分节点直接知识与子树知识。
- [ ] Entry 详情、来源查看、后续编辑和移动目录节点。
- [ ] 项目内与全局关键词搜索。
- [ ] Processing Task 进度、失败原因和幂等重试。
- [ ] 小屏访问统一显示电脑访问提示，不加载业务工作台或提供继续访问入口。

### P0-B：整理效率闭环

- [ ] 全局收集箱中 AI 推荐 Source 所属项目。
- [ ] 每条 Candidate 推荐真实目录 node_id、备选和理由。
- [ ] 推荐明确、需要确认、暂无合适位置三档路由状态。
- [ ] 确认 Candidate 时一次接受内容、类型、项目和目录。
- [ ] 新增节点并归档的原子操作。
- [ ] 跨 Source 批量处理视图。
- [ ] 按推荐目录分组确认、批量改目录和批量拒绝。
- [ ] 高风险 Candidate 自动退出批量快审。
- [ ] 与已有 Entry 的基本相似检索。
- [ ] 新建、疑似重复、补充、可能冲突的归档建议。
- [ ] 重复时只为已有 Entry 补充新 Source 证据。
- [ ] Project Context Snapshot 增强：纳入已确认 Entry、知识覆盖和近期主题，并记录上下文版本。
- [ ] 记录用户接受、修改和拒绝推荐的行为，为后续个性化提供信号。

P0-A 与 P0-B 都完成后才视为 MVP 验证版本。实施时分开做小 change，避免一次交付过大。

### P1：目录共创与知识回忆

- [ ] Directory Agent 从零起草目录并进行必要澄清。
- [ ] 可视化 Directory Draft、内联编辑和确认应用。
- [ ] 与 AI 对话调整草稿，使用结构化增量操作。
- [ ] 对任意节点进行 AI 拓展。
- [ ] 对现有目录提出新增、改名、移动、更新说明和建议删除。
- [ ] 目录差异展示、受影响 Entry 数量与安全合并。
- [ ] 语义搜索和相似知识推荐。
- [ ] Reader Agent 节点范围与项目范围问答。
- [ ] 回答引用 Entry 和 Source，知识不足与冲突可见。
- [ ] 回答内容转 Candidate 的确认流程。
- [ ] 思维导图目录浏览、聚焦、高亮和节点知识侧栏。
- [ ] Entry 基础版本历史与 AI 修订建议。

### P2：知识质量与媒介扩展

- [ ] 网页链接采集与正文提取。
- [ ] PDF、Word 等文档解析。
- [ ] 浏览器扩展；移动端系统分享入口随原生 App 单独规划。
- [ ] Review：重复、冲突、缺少条件、缺少来源和过期风险。
- [ ] 组合筛选、标签管理和更完整的批量管理。
- [ ] 多 Source 证据比较与来源可信度辅助判断。
- [ ] Knowledge Gap 对象和用户维护的待研究问题。
- [ ] 目录与知识覆盖分析。
- [ ] 跨项目引用或复制知识的受控能力。
- [ ] 数据导入、导出与彻底删除。

### P3：主动发现与平台化

- [ ] Discovery Agent 识别目录和知识缺口。
- [ ] 用户批准研究问题、范围、信源和频率。
- [ ] 联网搜索、来源质量判断和多来源比较。
- [ ] 发现结果先创建 Source，再生成 Candidate。
- [ ] 发现报告、定期检查和知识变化提醒。
- [ ] “仅我的知识库”与“知识库 + 外部发现”双模式。
- [ ] 视频和音频处理评估。
- [ ] 原生移动 App、截图直采和发现报告推送。
- [ ] 多 Workspace、多人协作和复杂权限，仅在真实需求出现后评估。

## 明确不做或暂缓

以下内容不进入 P0：

- 视频和音频理解；
- 各平台收藏自动同步；
- 通用知识图谱；
- 多 Agent 自主协商；
- 无需授权的后台主动研究；
- 自动写入或覆盖正式 Entry；
- 自动修改正式目录；
- 决策、预算和待办等垂直对象；
- 多人协作和社区分享；
- 每种 Entry 类型的专属结构；
- 原生移动客户端；
- 149 节点装修模板作为默认创建方式。

## 验证计划与指标

### 真实数据集

首轮使用 50 至 100 条真实装修截图和文字，覆盖：

- 单条与多条知识；
- 事实、个人体验、建议和推测；
- 有明确采集意图与无备注采集；
- 多候选归入不同节点；
- 重复、补充和冲突；
- OCR 困难、长图、水印和低质量截图。

旅行场景补充一小组以验证系统不会把主观体验错误降级为低价值。

### 核心指标

- Source 到第一条 Candidate 的时间；
- 每条 Source 产生的推荐候选数与其他发现数；
- Candidate 直接确认率；
- 用户修改率及主要修改字段；
- 项目推荐接受率；
- 目录推荐接受率和错误节点率；
- 单条和单批确认耗时；
- 每条 Source 最终产生的有效 Entry 数；
- 放弃确认的 Source 和 Candidate 比例；
- 处理失败率与重试成功率；
- 一周后通过目录或搜索重新找到知识的比例；
- Entry 来源查看和知识实际使用情况。

### MVP 成功判断

必须同时回答两个问题：

1. 用户是否愿意确认 AI 生成和推荐归类的内容？
2. 用户整理完成后是否会回来查找、阅读或使用这些知识？

只提高提取数量、模型调用次数或上传数量，不代表产品成立。

## 建议的 OpenSpec Change 顺序

每个 change 都应小到可以独立验证，禁止直接创建一个覆盖全部 P0 的巨大 change。

### 产品基线修正

1. `revise-project-lifecycle-and-empty-start`
   - 项目说明；
   - 生命周期；
   - 默认空目录；
   - 归档与恢复；
   - 修正旧装修模板默认路径；
   - 实现小屏统一电脑访问提示。

### P0-A 整理闭环

2. `add-source-and-attachment-foundation`
   - Source、Attachment；
   - 图片与文字采集；
   - Workspace 和 Project 归属；
   - Source 列表与详情。

3. `add-processing-task-pipeline`
   - 状态机、异步处理、失败重试和幂等；
   - Demo 与真实 Provider 边界。

4. `add-project-context-snapshot`
   - 基于项目说明和正式目录的初始概要；
   - 更新触发、防抖、失败回退、展示和纠正；
   - Agent 公共上下文接口。

5. `add-organizing-agent-extraction`
   - PydanticAI 接入；
   - OCR 文本输入；
   - 语义拆分、候选筛选和证据定位；
   - Extraction 与 Candidate。

6. `add-source-review-workbench`
   - 按 Source 审阅；
   - Candidate 编辑、确认、拒绝、暂缓；
   - Source 派生处理状态。

7. `add-entry-and-provenance`
   - Entry、主类型、目录归档；
   - 多 Source 证据；
   - 来源详情和基础修改。

8. `add-knowledge-browse-and-search`
   - 目录下卡片与列表；
   - 直接知识与子树知识；
   - 项目内和全局关键词搜索。

### P0-B 效率闭环

9. `add-project-and-node-routing-suggestions`
   - 全局 Source 项目推荐；
   - Candidate 真实 node_id 推荐；
   - 推荐状态与一次确认。

10. `add-create-node-and-archive`
   - 新节点建议去重；
   - 新增节点并归档原子操作；
   - 无合适节点的处理分支。

11. `add-batch-candidate-review`
    - 跨 Source 批量视图；
    - 按节点分组、批量操作与精审分流。

12. `add-entry-relation-suggestions`
    - 相似 Entry 检索；
    - 新建、重复、补充与冲突建议；
    - 补充来源和修订草稿。

13. `enhance-project-context-with-entries`
    - 将已确认 Entry、知识覆盖和近期主题纳入上下文；
    - 保存上下文版本和更新原因；
    - 为归类、关系判断和后续 Agent 提供稳定快照。

### P1 差异化能力

14. `add-directory-agent-drafting`
15. `add-directory-agent-node-expansion`
16. `add-semantic-retrieval`
17. `add-reader-agent-with-citations`
18. `add-directory-mind-map-view`

每个 change 必须完整执行：proposal → specs → design → tasks → validate → 实施 → sync specs → archive → commit。推送与合并仍需用户明确确认。

## 仍需通过真实使用验证的问题

以下问题不阻塞蓝图，但不能靠讨论永久定死：

- 一条 Source 的理想推荐候选数量；
- “其他发现”的默认折叠策略是否会漏掉用户真正想保存的内容；
- 四种主类型是否足够，用户是否真的使用类型筛选；
- 目录推荐需要节点说明到什么程度才能稳定；
- 批量确认的安全阈值与高风险分流规则；
- Entry 补充与新建之间最容易理解的交互；
- 项目上下文快照的更新频率和用户纠正方式；
- 卡片、列表、思维导图和 AI 阅读的真实使用占比；
- 何时具备进入主动发现阶段的证据。

这些问题应通过真实数据集、交互日志和用户实际使用逐步回答，不应提前扩张数据模型。

## 后续实现代理使用说明

将本专题交给 DeepSeek、Codex 或其他实现代理时，应同时提供仓库内 `AGENTS.md` 与产品蓝图索引，并使用以下约束：

1. 产品蓝图专题是产品决策输入，不是一次性实施任务。
2. 每次只选择“建议的 OpenSpec Change 顺序”中的一个 change，不得同时展开后续 change。
3. 先读取当前主规格与代码现状，再创建完整 proposal、specs、design、tasks。
4. `openspec validate --all --strict` 通过后才允许修改业务代码。
5. change 的 Non-Goals 必须明确列出同阶段尚未选择的其他能力。
6. 不得因为底层模型预留了字段，就提前实现 P1、P2 或 P3 界面与流程。
7. 每个 change 完成后独立运行后端、前端与 OpenSpec 验证，再归档和提交。
8. 推送和合并必须等用户真实体验并明确确认。

建议每次给实现代理的任务模板：

```text
请先阅读 AGENTS.md 和 docs/产品蓝图.md，再按索引只读取本次任务相关的 1 至 2 份专题、当前 openspec/specs 与相关代码。
本次只处理“建议的 OpenSpec Change 顺序”中的 <change-name>，不要实施后续 change。
严格执行 proposal → specs → design → tasks；运行 openspec validate --all --strict
通过后再开始实施。遇到蓝图未锁定的产品分歧，先记录并询问，不要静默扩展范围。
实现完成后验证、归档并本地提交；不要 push 或 merge。
```
