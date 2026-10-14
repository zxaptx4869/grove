# 产品介绍页验证记录

日期：2026-10-13。实现与自动化验证完成，待用户审阅页面并批准归档。

## 自动化

- 登录页、注册页与 App 路由测试：3 个文件、15 项通过。
- 覆盖成功提交真实接口协议、等待时禁用、失败就近显示并恢复提交；公开示例切换不发请求；390/1023/1024px 与实时缩放边界、根路径及末尾斜杠兼容。
- `npm run lint`：0 错误，既有 DirectoryDraftDialog.tsx 的两条 Hook 依赖警告；本次未修改该组件。
- `npm run build`：TypeScript 与 Vite 构建通过。
- 前置与收尾 OpenSpec 全库严格校验：均为 68 项通过。

## 浏览器与视觉

使用本机 Chrome 独立无头实例，不使用用户浏览器资料；在实际开发页面上执行检查，无独立原型。登录错误场景采用拦截响应测试，不提交真实账号或写入用户数据。

| 视口 | 布局与样式 | 行为 |
|---|---|---|
| 1280 / 1440 / 1600 | 1200px 内容宽、72px 品牌栏、52px 主标题；360px 表单、36px 控件；无溢出遮挡 | 三能力切换、锚点、键盘跳到主内容通过 |
| 1024 | 944px 内容宽、38px 主标题，仍保留双列与完整表单 | 桌面边界可用 |
| 1023 | 单列介绍，不挂载表单；业务页显示电脑访问提示 | 根路径进入介绍，业务页无请求 |
| 390 / 360 | 内容宽 350 / 320px、64px 品牌栏、主标题 31.2 / 28.8px；案例和能力示意单列 | 只读介绍，能力切换及键盘跳转通过 |

- 六种宽度均无页面运行错误、非预期横向滚动或公开页面 API 请求。
- 1440px 主视口先收敛，再扩展验证；截图检查结构与重量，计算样式核对几何、字体、颜色、边框、圆角和阴影。
- 候选与目录草稿明确待确认，回答示例不标为正式知识；说明示意不提供伪造业务操作。
- 正文、次文字、品牌、AI 与已确认底色上的文字均达到 4.5:1；引用数量改用品牌文字以满足对比度，确认色用于装饰性边框和图标。键盘可见焦点与跳转主内容通过。
- 注册页原布局与登录错误就近反馈均检查通过。
- 没有待处理的本次验收缺陷。既有 lint 警告不属于本次变更。

截图和计算样式证据：`artifacts/product-introduction/`，仅本地保存，不在版本管理中。包含各视口整页、首屏、两类能力示意、登录错误、注册页、1023px 阻断页与 `visual-results.json`。

## 待验收与归档审查

用户审阅入口：`http://127.0.0.1:5173/login`。重点检查首屏文案、两个案例、三个 AI 示意与三端职责是否符合展示目标。

归档目标：`add-product-introduction-page`。

规格同步差异：新增 `product-introduction` 主规格；完整更新 `product-shell` 中「认证工作流与全局应用壳」「桌面端边界阻断」两个需求，保留原有认证错误、业务壳与桌面场景，新增公开介绍的小屏例外。其余主规格不变。无同步冲突，批准前保持 active change；归档和推送合并分别授权。

## 用户审阅后精简验证（2026-10-13）

- 删除底部登录引导、技术栈横条及重复的小标题、流程条、总结句和说明；能力区用单一「示例」标识保留静态边界。候选与目录草稿待确认、来源引用及真实多端体验状态保持明确。
- 相关 15 项测试、lint（0 错误，2 条既有警告）与构建重新通过；全库 OpenSpec 严格校验在提交前通过。
- 在 1440/1280/1600/1024/1023/390px 重新检查截图、计算样式、锚点、键盘焦点、三种示例切换和登录错误状态，均无溢出、页面运行错误或公开页面 API 请求。
- 1440px 首屏区高度由约 627px 降至 497px，整页由 3646px 缩短至 2343px；手机首屏区由约 593px 缩短至约 469px。截图确认无删减区块残留或多余间距。
- 最新证据：`artifacts/product-introduction/simplified/`（仅本地保存，不在版本管理中），旧证据保留用于对比。变更仍待最终用户验收和归档批准。

## 回到顶部缺陷修复（2026-10-13）

原因：底部链接指向品牌导航下方的正文 `intro-main`，回跳后桌面仍滚动 48px、手机仍滚动 40px，导致导航被裁切。修复为指向顶部品牌栏 `intro-top`，同时让键盘焦点落到品牌栏；原「跳到产品介绍」入口继续定位正文。

在 1440px 和 390px 下验证鼠标与键盘回跳：`scrollY=0`、品牌栏顶部为 0，桌面导航完整可见，下一次 Tab 可进入首页链接。lint 无错误（两条既有警告）、构建通过。截图证据位于 `artifacts/product-introduction/back-to-top/`，仅本地保存。无规格行为变化，不新建 change。

## AI 案例调整（2026-10-13）

按用户要求：AI 提取推荐和知识 Agent 统一使用闭水试验，项目为「新房装修」、推荐目录为「施工与验收 → 防水 → 闭水试验」；目录共创以新房装修为主题，展示需求预算、设计选材和施工验收框架。保留「示例」与「待确认」标识，替换原 React 技术案例。

案例只用渗漏检查、水位与影像记录等说明性内容，相关背景参考[北京市住建委关于加强工程质量影像追溯管理的通知](https://www.beijing.gov.cn/zhengce/gfxwj/sj/202102/t20210208_2279629.html)的防水工程段落，不将示例表述为现场验收结果。

登录页相关 4 项测试通过；lint 无错误（两条既有警告），构建通过。1440px 与 390px 下检查三个示例的文本、切换与溢出，无页面错误或业务请求。截图证据位于 `artifacts/product-introduction/renovation-examples/`，仅本地保存。

## 固定导航与标签页验收（2026-10-13）

- 顶部栏滚动时保持固定，右侧登录跳转移除。区块锚点标题位于导航下方，底部回到顶部恢复 scrollY=0，键盘返回、跳过正文与焦点行为正常。
- AI 示例改为 radix-ui 标签页，选中项为品牌绿底白字；移除箭头，用共同浅底容器表达切换关系。ARIA 标签、选中态、内容面板关联与单一 Tab 停留一致，左右方向键、Home、End 及 Tab 进入内容面板通过。
- 相关 3 文件、16 项测试通过；lint 无错误（两条既有警告）；TypeScript 与 Vite 构建通过。
- 1440px 主视口及 1280/1600/1023/1024/390px 检查通过：header position=sticky、top=0，桌面高 72px/手机高 64px；无横向溢出或页面错误，无公开页面业务请求。导航、标签与正文没有遮挡。
- 手机标签采用平衡换行与统一文字区域，避免末字单独成行；局部调整后复核手机交互和构建均通过。
- 选中背景 rgb(35,103,72)、文字 rgb(255,255,255)，正文对比度满足 4.5:1。截图与计算样式、锚点几何结果在 `artifacts/product-introduction/tabs-sticky/`（仅本地保存，不入 Git）。无本次未修复缺陷，仍待用户最终验收和归档批准。

本次新增归档同步范围：公开介绍规格补充固定导航、回到顶部及标签页交互场景；其余同步目标延续已有记录。

## 登录注册统一区域验收（2026-10-13）

- `/login` 与 `/register` 共用 AuthPage 和右侧认证卡片，顶部统一「欢迎来到 Grove」，使用登录/注册标签。删除独立 AuthLayout 与表单底部互跳文字，保留原有校验、API、Cookie、注册即登录与错误恢复。
- 鼠标点击或键盘 Enter/Space 激活模式；方向键只移动认证标签焦点。修复自动焦点激活导致重复写入浏览器历史的问题。提交期间禁用认证标签，失败后恢复；两种模式的表单与错误不串用。
- 相关 3 个文件、22 项测试通过，覆盖注册密码确认、重复账号、注册成功导航、等待禁用、模式切换、历史恢复、AI 示例状态保留与小屏公开边界。lint 无错误（两条既有警告），TypeScript 与 Vite 构建通过。
- 1440/1280/1600/1024px 下：两种模式卡片顶部均为 148px、宽 410px，内容输入宽 360px/高 36px；左侧介绍顶部保持 148px。URL、前进后退、键盘操作和当前 AI 示例保留通过，无溢出或页面错误。
- 1023/390px 下：直接访问两个地址均只读介绍，无登录注册表单；工作台仍阻断。公开访问与模式切换无业务请求。浏览器注册错误检查拦截为模拟 409，无真实账号创建。
- 最新截图和几何记录：`artifacts/product-introduction/unified-auth/`（仅本地保存，不入 Git），包括两种模式、全页注册、等待和错误状态。无本次遗留缺陷，仍待最终用户验收与归档批准。

最新归档同步范围更新：`product-introduction` 的两条公开入口；`product-shell` 的统一认证卡片、URL/历史切换、注册成功场景和两个公开地址的小屏只读例外。端侧专题已同步本次授权的边界。

## 恢复登录样式与底部链接切换（2026-10-13）

按用户最新反馈去掉认证标签和统一欢迎标题。登录恢复「登录 / 进入你的知识工作台」与原表单样式，下方「没有账号？去注册」；注册使用「创建账号」，下方「已有账号？去登录」。底部链接在同一卡片切换，URL、历史与当前 AI 示例保留；提交期间链接不可激活，失败后恢复。

相关 3 文件、22 项测试、构建通过，lint 无错误（两条既有警告）。1440/1280/1600/1024/1023/390px 浏览器检查通过：桌面卡片顶部均为 148px，鼠标与键盘互切、浏览器前后退正常；小屏不挂载认证表单；没有公开业务请求、溢出或运行错误。模拟注册 409 场景通过，无真实账号创建。

最新证据：`artifacts/product-introduction/auth-links/`（仅本地保存，不入 Git）。当前归档规格以底部链接互切为准，不包含顶部认证标签；仍待用户最终验收与归档批准。
## 三端界面示意验证（2026-10-13）

- 按用户选择以 React/CSS/Lucide 绘制简化示意图，统一新房装修／闭水试验案例：扩展框选并发送收集箱、App 的知识 Agent 问答与来源、Web 的原文与待确认候选对照。区块统一标识「界面示意」，各图使用中文图像替代说明，无可交互业务控件及业务请求。
- 浏览器检查 1440/1280/1600/1024/1023/390px。桌面三列、手机单列；图区域均高 320px，1440px 图宽约 373px、1024px 为 288px、390px 为 350px。截图及计算样式确认无水平溢出、文字截断、控制区遮挡或控制台错误。手机逐项实际视口截图避免长元素截图中的 sticky 合成干扰。
- 相关三个测试文件 22/22 通过。原有全页面唯一文本查询改为在 AI 标签面板内查询，避免示意图使用同一候选文字导致测试歧义。lint 无错误，保留既有 DirectoryDraftDialog 的两条依赖警告；build 通过。
- 本地证据：`artifacts/product-introduction/device-illustrations/`（不入版本管理），包含桌面区块截图、手机实际视口截图及计算样式 `results.json`。全库 OpenSpec 严格校验在规划后与收尾执行。
- 页面与自动化验证完成，等待用户视觉审阅；当前 change 尚未归档或推送。

## 真实截图与 App 去调试图标（2026-10-13）

- 用户最新反馈覆盖此前示意图方案。每个端独立成行，扩展展示框选与快采面板，App 并排展示对话与收集箱，Web 使用可键盘切换的三个截图标签展示 Agent、收集箱、确认台。所有图片支持点击放大，截图内部的业务控件只属于图片。
- 展示资源位于 `frontend/src/assets/introduction/`：用户提供的 `extension-capture.png`、`extension-panel.png`、`web-inbox.png`、`web-review.png`；从已登录演示账号实际取得的 `web-agent.jpg`；去齿轮后的 `mobile-agent-clean.png`、`mobile-inbox-clean.png`。App 编辑非覆盖原图，最终输出尺寸分别为 862×1824、860×1828；人工逐项核对正文、标签、卡片和底部导航，未发现文字改写或缺失。
- 主视口 1440px：左右列 240px/912px、间距 48px；App 图片约 238×504/506px，Web 图区约 910×475px；图片圆角 12px、语义边框与主题卡片阴影。浏览器检查 1280/1600/1024/1023/390px，390px 改为纵向端介绍、App 两图并排；图片均加载成功，无横向溢出。小屏不挂载认证输入。截图通过明确尺寸及 lazy 加载保留布局。
- 验证 Web 标签的 End/Home/方向键、图片放大、Esc 与关闭按钮、焦点归还。1440px Web 对话框约 1392×787px；390px App 对话框宽 366px、两侧各 12px，图片完整可见，没有溢出。浏览器错误日志为空，测试覆盖认证、路由边界与新截图交互，23/23 通过。lint 无错误，保留 DirectoryDraftDialog 既有两条依赖警告，build 通过。
- 本地走查证据位于 `artifacts/product-introduction/screenshot-gallery/`（不入版本管理），含各视口图片、App 与 Web 放大界面、`app-gallery-final.jpg` 及 `results.json`。全库 OpenSpec 严格校验收尾通过；用户视觉审阅与归档批准仍待完成。

### 内置 imagegen 编辑提示词

使用内置图片编辑工具，不使用 CLI/API。两张原图均只要求移除灰色齿轮；完整调用提示词如下，供复核：

**收集箱：**

> Use case: precise-object-edit. Edit target: the attached real Grove mobile App inbox screenshot. Remove ONLY the floating grey circular debugging gear at the TOP RIGHT near the 收集箱 heading. Fill its entire circle and soft grey shadow with the same flat very light grey background as the surrounding header. Preserve exact image framing, original portrait aspect ratio, all Chinese text, all cards, icons, colors, borders, spacing, bottom navigation, and all other pixels unchanged. This is surgical retouching of a real screenshot, not a redesign. Do not remove the refresh icon under the header; remove only the large floating grey gear. No new elements, no text rewriting, no cropping.

**对话：**

> Use case: precise-object-edit. Edit target: the attached real Grove mobile conversation screenshot. Remove ONLY the large floating grey circular debugging gear at the lower right, in the blank grey area BETWEEN the AI answer card and the composer input. Fill the circle and its shadow with exactly the surrounding flat very light grey background. Preserve original full portrait framing, aspect ratio, ALL Chinese text and typography exactly, all cards, logos, icons, UI spacing, colors and bottom navigation unchanged. This is surgical screenshot retouching, not a redesign. Do not alter the top-right conversation icon, question, answer text, input field or bottom toolbar. No new elements, no text rewriting, no cropping.

## 扩展截图顺序与尺寸调整（2026-10-14）

- 按用户要求，快采面板在左、带发送按钮的框选预览在右；DOM、键盘与小屏纵向顺序一致。1440/1280/1600px 下图片区域宽 240px/480px、间距 24px，预览图从约 648px 缩小约 26%；1024px 为 200px/477px，390px 纵向为 200px/335px。原图与放大交互不变。
- 截图及计算样式确认上述视口无横向溢出，图片完整。局部证据：`artifacts/product-introduction/extension-layout/`（本地，不入 Git），含截图与 `results.json`。
- 构建发现上一轮新增测试使用了 Testing Library 不支持的 `getByRole` 参数 `exact`。移除三处多余参数，字符串名称查询保持相同匹配行为。相关三个测试文件 23/23 通过，包含截图切换、放大与焦点归还；TypeScript 与 Vite 构建通过。lint 无错误，既有两条依赖警告保持不变；全库 OpenSpec 严格校验通过。

## 首屏文案定稿（2026-10-14）

- 用户选择方案 1：标题为「让收藏的知识用得上，让想学的领域有方向。」；说明逐字采用用户提供的文案，保留 grove 的小写及 Agent助手 的写法。仅替换文字与既有标题测试断言。
- 浏览器核对 1440/1024/390px，标题均为两行，无横向溢出，说明与用户原文一致。LoginPage 相关 6 项测试通过，lint 无错误（既有两条警告），TypeScript 与 Vite 构建通过。本次纯文案调整没有改变规格行为，不重复截图矩阵或全库规格校验。

## 大标题去标点（2026-10-14）

- 按用户要求移除首屏两行末尾逗号与句号，并检查各区块大标题。AI 能力、三端和设计原则标题的标点也移除，内部停顿以空格表达；场景区块标题与认证标题本来无标点。正文与场景引用文案不改。
- 同步既有标题测试断言；LoginPage 6 项测试、TypeScript 与 Vite 构建通过，lint 无错误（两条既有警告）。纯文案调整不新增规格行为或测试。

## 首屏说明再次调整（2026-10-14）

- 按用户提供的完整文案替换小字体说明，突出碎片知识的归属与找回、新领域共创项目目录及针对性积累知识经验。保留用户指定的 grove、助手AGENT 与结尾表达，经全文匹配确认一致。
- 仅变更说明文字，LoginPage 6 项测试及 TypeScript/Vite 构建通过，lint 无错误（两条既有警告）；不新增规格行为或测试。

## 分支审查缺陷修复（2026-10-14）

- 审查复现：App.test 的六个小屏用例仍断言旧标题，因此相关 23 项测试中 6 项失败；390px 的 Web 预览图宽 333px，旧弹窗图宽 332px，没有实际放大。
- 小屏测试改为验证 main 区域及一级、二级标题结构，保留无认证表单、无业务查询的核心断言，避免耦合营销文案；宽度恢复放入 act，消除相关清理警告。
- 截图弹窗增加 100%～400% 缩放、50% 步长与适应窗口重置。使用独立滚动视口和明确图片尺寸，鼠标 Pointer Capture 拖动、原生触屏滑动与键盘滚动均有入口，关闭与焦点归还保留。ResizeObserver 根据实际视口更新适应比例，不新增依赖或业务查询。
- 浏览器实际测量 390px：适应宽 330px，200% 宽 660px，内部 scrollWidth 为 660px；拖动后 scrollLeft 为 282px。400% 可产生横纵滚动，适应窗口恢复图片宽 330px 与 scrollLeft/Top 为 0。关闭后焦点返回截图入口。1440/1280/1024/390px 均确认实际图片尺寸增长、内部滚动与键盘左右滚动，外部页面无横向溢出。
- 新测试使用 333×500px 查看区域验证图片实际宽度增长、缩放上下限与重置。相关三个测试文件 24/24 通过，TypeScript/Vite 构建通过，lint 无错误（两条既有依赖警告），OpenSpec 全库严格校验 68/68 通过。
- 本地证据：`artifacts/product-introduction/zoom-fix/`，包含不同视口 200% 截图及 `results-390.json`、`matrix.json`，不入版本管理。两处审查缺陷已修复并完成自动化及浏览器验证；当前 change 仍待最终视觉审阅与归档批准。
