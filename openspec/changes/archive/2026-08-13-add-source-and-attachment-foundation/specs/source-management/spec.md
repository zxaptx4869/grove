## ADDED Requirements

### Requirement: Source 归属与 Workspace 隔离
系统 MUST 提供 `Source` 模型并归属到 Workspace；Source MUST 可未归属 Project，或最多归属同一 Workspace 内的一个 Project；跨 Workspace 的 Source MUST 不可见。

#### Scenario: 列出当前空间的 Source
- **WHEN** 已登录用户请求收集箱来源列表
- **THEN** 只返回该用户 Workspace 内的 Source

#### Scenario: 跨用户 Source 不可见
- **WHEN** 用户 B 尝试访问用户 A 的 Source（通过 ID）
- **THEN** 请求失败（404），不暴露 Source 信息

### Requirement: 附件与 Source 关系
系统 MUST 支持一个 Source 包含一个或多个 Attachment；Attachment MUST 属于一个 Source，类型为 image（图片）或 text（文字）；同一 Source 的多张图片 MUST 按采集顺序保存。

#### Scenario: 多图来源
- **WHEN** 用户一次上传多张图片采集
- **THEN** 创建一个 Source，其包含多个 image Attachment，并按提交顺序排列

#### Scenario: 文字来源
- **WHEN** 用户粘贴一段文字采集
- **THEN** 创建一个 Source，其包含一个 text Attachment

### Requirement: 图片采集
系统 MUST 支持批量上传图片创建 Source；一次采集的图片数量 MUST 不超过 5 张；采集时 MUST 可选填写所属项目与补充说明；未选择项目时 Source 保持未归属。

#### Scenario: 批量上传并指定项目
- **WHEN** 用户上传多张图片并选择项目
- **THEN** 创建 Source 归属该项目，图片作为附件保存，列表可看到该项目归属

#### Scenario: 上传不选项目
- **WHEN** 用户上传图片但不选择项目
- **THEN** 创建 Source 且未归属任何项目

#### Scenario: 补充说明
- **WHEN** 用户采集时填写补充说明
- **THEN** Source 保存该说明并在列表与详情中可见

#### Scenario: 超过数量上限
- **WHEN** 用户一次上传超过 5 张图片
- **THEN** 请求失败（400），不创建 Source

### Requirement: 文字采集
系统 MUST 支持粘贴文字创建 Source；粘贴图片时按图片处理，纯文字时作为 text Attachment 保存。

#### Scenario: 粘贴纯文字
- **WHEN** 用户粘贴纯文字并采集
- **THEN** 创建 Source 且包含一个 text Attachment

#### Scenario: 粘贴图片
- **WHEN** 用户粘贴图片并采集
- **THEN** 创建 Source 且包含对应的 image Attachment

### Requirement: 本地附件存储与访问
系统 MUST 把图片附件保存在本地文件系统，数据库只存相对路径；上传 MUST 校验文件为支持的图片类型且单张不超过 10MB；图片 MUST 可通过后端接口访问。

#### Scenario: 上传图片后可访问
- **WHEN** 用户上传一张图片
- **THEN** 图片保存到本地附件目录，数据库保存相对路径，前端可通过接口读取该图片

#### Scenario: 拒绝非图片类型
- **WHEN** 用户上传非图片文件
- **THEN** 请求失败（400），不创建 Source

#### Scenario: 拒绝超大图片
- **WHEN** 用户上传单张超过 10MB 的图片
- **THEN** 请求失败（400），不创建 Source

### Requirement: Source 列表
系统 MUST 支持列出当前 Workspace 的 Source，并按未归属或指定项目筛选；项目内来源列表 MUST 只返回该项目内的 Source。

#### Scenario: 收集箱未归属筛选
- **WHEN** 用户查看收集箱并筛选未归属
- **THEN** 只返回未归属项目的 Source

#### Scenario: 项目内来源
- **WHEN** 用户在项目内查看采集与来源
- **THEN** 只返回归属该项目的 Source

### Requirement: Source 详情
Source 详情 MUST 展示其附件（图片缩略图或文字预览）、采集说明、所属项目与创建时间。

#### Scenario: 查看详情
- **WHEN** 用户打开一个 Source 详情
- **THEN** 显示全部附件、采集说明、项目归属和创建时间

### Requirement: 项目归属修改
系统 MUST 支持把未归属 Source 归属到同一 Workspace 内的项目，或修改其所属项目；跨 Workspace 的项目 MUST 被拒绝。

#### Scenario: 选择项目
- **WHEN** 用户把未归属 Source 归属到某个项目
- **THEN** Source 更新为归属该项目

#### Scenario: 拒绝跨空间项目
- **WHEN** 用户尝试把 Source 归属到其他 Workspace 的项目
- **THEN** 请求失败（400），归属不改变

### Requirement: 删除 Source
系统 MUST 支持删除 Source 并级联删除其 Attachment 记录与本地附件文件。

#### Scenario: 删除清理附件
- **WHEN** 用户删除一个含图片的 Source
- **THEN** Source 及其 Attachment 记录被删除，本地图片文件也被清理

### Requirement: 标题自动生成
Source 标题 MUST 自动生成：图片 Source 取第一个图片附件的文件名，文字 Source 取正文首行；本轮 MUST NOT 依赖 AI 生成标题。

#### Scenario: 图片标题
- **WHEN** 用户上传图片创建 Source
- **THEN** Source 标题为第一个图片文件名

#### Scenario: 文字标题
- **WHEN** 用户粘贴文字创建 Source
- **THEN** Source 标题为正文首行
