# Grove 产品原型

## 当前版本

- 文件：[grove-product-prototype.html](grove-product-prototype.html)
- 确认日期：2026-08-13
- 定位：桌面 Web 产品总览原型，用于页面布局、信息层级和关键交互参考。
- 小屏边界：低于 1024px 只展示电脑访问提示，不提供手机 Web 业务流程。

## 覆盖页面

- 项目列表与项目首页；
- 全局收集箱与项目内采集来源；
- 确认台的按采集审阅和批量处理；
- 知识空间的目录、卡片、列表和思维导图；
- 知识全景原型（旭日图全局视图 + 目录大纲联动阅读）；
- 项目首页全景卡原型（紧凑旭日图 + 进度指标 + 收敛后的文字区）；
- 目录共创草稿；
- AI 阅读与引用；
- 全局搜索、账户和小屏阻断状态。

原型覆盖页面不代表对应功能已经实现，也不代表它们处于同一开发阶段。当前能力以 `openspec/specs/` 和正式代码为准，开发顺序以[功能优先级与 Change 顺序](../产品蓝图/功能优先级与Change顺序.md)为准。

## 本地访问

在仓库根目录执行：

```bash
python3 -m http.server 8899 --bind 127.0.0.1
```

访问：`http://127.0.0.1:8899/docs/prototypes/grove-product-prototype.html`

原型包含用于图标展示的外部脚本，离线时部分图标可能缺失；正式前端不依赖原型文件运行。

## 权威边界

1. 产品蓝图决定产品方向、对象与阶段。
2. OpenSpec 主规格和当前 change 决定可验收的业务行为与本次范围。
3. 本原型决定已确认的视觉、信息层级和交互参考，但静态数据、模拟反馈和未进入 change 的页面不是正式功能。
4. 正式 React 代码描述当前实现状态。

发生冲突时，不直接用原型覆盖蓝图或 OpenSpec。涉及产品行为的变化先更新对应产品专题和 change；纯视觉调整可以在 change 的 `design.md` 记录有意偏离。

## 与正式开发衔接

每个涉及前端的 OpenSpec change：

1. 只打开本次涉及的原型页面，不要求通读或实现整个原型。
2. 在 `design.md` 写明对应页面、采用的布局与有意偏离项。
3. 使用正式技术栈重新实现，不复制原型的内联样式、包装 iframe、演示脚本和静态状态。
4. 只实现 change 规格要求的 loading、empty、error、partial、retry、disabled 等状态。
5. 完成后在 1280px、1440px 和 1600px 对照原型截图验收；端侧边界相关 change 另需验证低于 1024px 的阻断页。

常见对应关系：

| 原型页面 | 后续 Change |
|---|---|
| 项目首页 | `add-project-lifecycle-and-empty-structure`、`add-project-context-snapshot` |
| 收集箱、采集与来源 | `add-source-and-attachment-model`、`add-processing-task-pipeline` |
| 确认台 | `add-source-review-workbench`、`add-batch-candidate-review` |
| 知识空间 | `add-entry-and-provenance`、`add-knowledge-browse-and-search` |
| 目录共创 | `add-directory-agent-drafting`、`add-directory-agent-node-expansion` |
| AI 阅读 | `add-reader-agent-with-citations` |
| 思维导图 | `add-directory-mind-map-view` |
| 知识全景（旭日图 + 大纲） | 探索性原型，未排期；如确认方向再创建 change |

> `grove-knowledge-overview.html` 是展示型探索原型：以旭日图呈现目录结构与知识密度，
> 点击扇区或大纲节点联动阅读。纯前端单文件、无外部依赖、使用静态示例数据，不代表正式功能。
>
> `grove-project-home-overview.html` 是项目首页改版探索原型：把紧凑旭日图放进项目首页主区域，
> 右侧配进度指标（节点/知识/待确认/最近整理），文字摘要收敛为一行与折叠项。静态示例数据，不代表正式功能。
