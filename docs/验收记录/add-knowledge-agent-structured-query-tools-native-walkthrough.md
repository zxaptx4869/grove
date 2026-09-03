# 知识 Agent 结构化查询工具原生端三视口走查记录

来源 change：`add-knowledge-agent-structured-query-tools`（任务 7.2）

走查日期：2026-09-03

> 状态：本 change 的 React Native 界面三视口、真实 API、历史恢复与交互走查已完成。
> 当前机器没有 Xcode `simctl`、Android `adb` 或连接设备，本轮载体为移动端正式实现
> （`mobile/`）的 React Native Web 渲染；这不替代 iOS/Android 的系统键盘、安全区和
> 读屏验证，设备差异列在文末。

## 环境与数据

- 前端：Expo / React Native 正式代码，`EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8031`，
  Web 预览监听 `127.0.0.1:8081`；
- 后端：任务 7.1 的隔离 SQLite 库，迁移到 `e9f0a1b2c3d4`，结构化查询开关开启；
- 夹具：只写入 `/private/tmp/grove_structured_accept_20260902.db`，覆盖 v1、v2、空结果、
  长分组、partial、8 条分页、恢复快照和 Entry 当前态；未修改开发库；
- 浏览器：Codex 内置浏览器，分别设置 360×800、390×844、412×915；截图接口按
  逻辑视口尺寸输出 JPEG。

## 截图路径

- `docs/验收记录/structured-query-walkthrough/360x800-v1-list.jpg`
- `docs/验收记录/structured-query-walkthrough/360x800-exact-statistics.jpg`
- `docs/验收记录/structured-query-walkthrough/390x844-semantic-limited.jpg`
- `docs/验收记录/structured-query-walkthrough/390x844-empty.jpg`
- `docs/验收记录/structured-query-walkthrough/390x844-partial.jpg`
- `docs/验收记录/structured-query-walkthrough/390x844-pagination-loaded.jpg`
- `docs/验收记录/structured-query-walkthrough/390x844-entry-current-changed.jpg`
- `docs/验收记录/structured-query-walkthrough/412x915-long-group-expanded.jpg`
- `docs/验收记录/structured-query-walkthrough/360x800-entry-unavailable.jpg`

## 三视口矩阵

每个视口均重新加载历史 Conversation，再逐项检查文案、分页和当前 Entry 弹层。三轮
结果相同：

| 场景 | 360×800 | 390×844 | 412×915 | 验收点 |
|---|---|---|---|---|
| 纯列表 / v1 | 通过 | 通过 | 通过 | 继续显示“找到 1 条相关知识”，不要求 v2 字段 |
| 精确统计 + 列表 | 通过 | 通过 | 通过 | 显示“共 3 条”，与有界 2 张 Entry 卡相互独立 |
| limited 语义统计 | 通过 | 通过 | 通过 | 显示“本次匹配到 2 条”“仅覆盖本次匹配集合”，未声明全集 |
| 长分组 / 桶截断 | 通过 | 通过 | 通过 | 首屏 4 桶；可展开其余 2 组；保留服务端截断与有限边界 |
| 空结果 | 通过 | 通过 | 通过 | 显示“共 0 条”和独立空态，不从卡片数量推导 |
| 聚合完成、列表 partial | 通过 | 通过 | 通过 | 精确 count 为 9；列表超时、partial 和“不由卡片数量反推”可见 |
| 历史恢复 | 通过 | 通过 | 通过 | 重新加载后 v1/v2、精确统计和恢复 Run 均从持久化快照恢复 |
| 分页 | 通过 | 通过 | 通过 | 首屏 6/8，点击“加载更多”后显示第 8 条与“已显示 8 条” |
| Entry 当前状态变化 | 通过 | 通过 | 通过 | 打开快照对象后读取当前 Entry，显示“结果生成后已更新”和当前来源 |

另在 360×800 与 412×915 打开已不存在的历史 Entry，均显示“该知识当前不可用”，
同时保留生成时快照，没有把 404 当作整组结果失败。

## 布局与可访问性

- 三个视口的 `innerWidth`、`documentElement.scrollWidth` 与 `body.scrollWidth` 分别为
  360、390、412；遍历可布局元素得到的横向越界数均为 0；
- Entry 当前态弹层在三个视口的页面横向溢出差值均为 0；
- 长分组按钮具有“展开按信息性质其余 2 组”辅助名称；加载按钮具有“加载更多结果”
  辅助名称；Entry 行包含序号、正式知识、标题和归属；
- 结果保持既有“知识列表”顶层形态，只包含范围、完整性、统计、排序和只读 Entry 卡，
  未出现 Citation、勾选、批量或知识写入动作。

## 控制台结果

使用干净页面重新执行三视口矩阵后：

- `error`：0；
- `warn`：仅 React Native Web 开发构建重复报告既有的
  `"shadow*" style props are deprecated. Use "boxShadow".`；
- API 登录、Conversation/消息页、结果分页和当前 Entry 请求均成功，没有未解释的
  401、404、500 或 `Failed to fetch`。

该警告来自通用 UI 样式在 Web 开发渲染层的弃用提示，不由本 change 新增，也不影响
iOS/Android 原生样式语义；本 change 不借机全面改造共享样式。

## 剩余设备差异

当前机器执行 `xcrun simctl list devices available` 返回找不到 `simctl`，执行
`adb devices` 返回找不到 `adb`，因此未覆盖：

1. iOS/Android 原生字体度量、系统安全区与底部导航实际高度；
2. 系统键盘弹出/收起时 Composer 避让和滚动保持；
3. VoiceOver/TalkBack 的真实焦点顺序与弹层关闭后的焦点归还。

本轮未发现结构化统计信息层级、分页、历史恢复或当前 Entry 读取方面的界面差异。
设备相关项属于验收环境覆盖差异，不在未经用户确认的情况下写入后续优化清单。
