# 视觉基线（任务 1.5）

> 依据：`docs/prototypes/grove-mobile-agent-prototype.html` 的 `.knowledge-card`、对话消息卡、Sheet、Composer 与主题令牌；当前原生组件 `ui.tsx`、`AnswerCard.tsx`、`ModeSheet.tsx`、`Composer.tsx`、`CitationSheet.tsx`。

## 主视口与固定区域

- 主验收视口：390 × 844；扩展：360 × 800、412 × 915。
- 顶栏：`min-height 58px`，左侧品牌 34×34（radius 8），中间范围按钮（min-height 40，max-width 220），右侧 44×44 图标按钮。
- thread：`paddingHorizontal 16 / top 18 / bottom 18`，消息区独立滚动。
- Composer：`min-height 50`、radius 13、边框 `theme.border`、阴影 0 8 24；工具与发送按钮 40×40（radius 9）；输入 14/20，maxHeight 96。
- 键盘避让：iOS/Android 唯一负责人为 `useKeyboardHeight` + Composer 容器 `paddingBottom`；底栏在输入聚焦时隐藏；Sheet 内 `SafeAreaView edges=["bottom"]`。

## 原型知识行基线（knowledge-card）

| 元素 | 原型值 | 说明 |
|---|---|---|
| 行容器 | `padding: 13px 2px`；`border-bottom: 1px solid var(--g-border)` | 扁平列表行，不是卡片套卡片 |
| 首行 | `display:flex; gap:7px` | Badge + 归属/时间 caption |
| Badge | `min-height:21px; padding:2px 6px; radius:4; font-size:10px; line-height:16px; font-weight:650` | 正式知识使用 `confirmed`（#187C72 / #E7F5F2） |
| caption | `font-size:11px; line-height:17px; color:var(--g-muted)` | 项目 / 目录定位 |
| 标题 h3 | `margin-top:7px; font-size:14px; line-height:21px` | 单行可截断 |
| 摘要 p | `margin-top:4px; font-size:11px; line-height:18px; color:var(--g-muted)` | 两行左右 |

## 当前组件基线（需对齐并保持）

- Card：radius 10、边框 `theme.border`、`cardShadow`；`CardBody` padding 13。
- Eyebrow：11/16 muted；answerTitle：16/23 weight 700；正文 14/23；要点 13/21。
- Citation chip：min-height 40、radius 7、maxWidth 230、11/600 muted。
- Scope stamp：10/16 muted，上边框分隔。
- ModeSheet：分组标签 10/700；选项 min-height 52、标题 13/600、详情 11、radio 20。
- Sheet：maxHeight 84%、顶部 radius 18、handle 36×4、head min-height 52（标题 17/700）、关闭按钮 40×40（radius 8、soft 背景）。
- 触控：主要按钮与行 min-height 44（`AppButton` 44）；纯图标控件提供 `accessibilityLabel`。

## 有意偏离

- **结果列表容器**：原型 `.knowledge-card` 用于知识栏目；对话内结果采用一个 `EntryResultsCard`（沿用 Card 的 radius 10/边框/阴影）作为容器，内部 `EntryResultRow` 是带 `border-bottom` 分隔线的扁平行（对齐原型行 padding 13/2 与间距），不复制原型 HTML/CSS，也不做卡片套卡片。
- **行内顺序**：正式知识 Badge → 标题 → 项目/目录 → 摘要 → 类型/来源数/更新时间 → 可选匹配线索；Workspace 范围逐项显示项目归属。
- **匹配线索**：仅服务端可验证的字段命中或受限正文片段；纯语义召回无可靠命中时省略，不显示伪相关度。
- **Sheet 关闭按钮**：现有组件为 40×40；为满足 44×44 有效触控，新增/复核时对关闭等 40px 控件补 `hitSlop`（或提升到 44），并在验收记录中说明。
- **ModeSheet 高度**：新增「结果形式」组后 Sheet 必须可滚动，并在 360×800 + 系统键盘/动态字体下走查，不把三维度挤成单行控件。
