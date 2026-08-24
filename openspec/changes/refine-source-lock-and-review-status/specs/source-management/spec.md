## MODIFIED Requirements

### Requirement: Source 处理状态与触发

Source MUST 有处理状态（等待处理 / 处理中 / 提取完成 / 失败）；采集后 MUST 默认为等待处理；来源列表 MUST 展示状态，并对等待处理提供「开始处理」、对失败提供「重试」。

#### Scenario: 采集后等待处理
- **WHEN** 用户采集一个 Source
- **THEN** Source 状态为等待处理

#### Scenario: 展示状态
- **WHEN** 用户查看来源列表
- **THEN** 每条 Source 展示其处理状态，提取完成状态文案为「提取完成」

#### Scenario: 开始处理
- **WHEN** 用户对等待处理的 Source 点击「开始处理」
- **THEN** Source 进入处理流程，状态变为处理中

#### Scenario: 失败重试
- **WHEN** 用户对失败的 Source 点击「重试」
- **THEN** Source 重新进入处理流程

### Requirement: Source 审阅状态

系统 MUST 根据 Source 当前候选的决策结果派生审阅状态，并在来源列表以副徽标展示：有待确认候选时显示「待确认 N 条」，已有正式知识且仍有待确认时显示「部分确认」，已产生正式知识且无待确认时显示「N 条正式知识」，无待确认且无正式知识时显示「已处理」；`SourceOut` MUST 返回 `pending_candidate_count`（待确认候选数）；确认台待处理来源 MUST 只展示仍有待采纳候选的来源。

#### Scenario: 待确认副徽标
- **WHEN** 提取完成且存在 N 条待确认候选、无正式知识
- **THEN** 来源行显示「待确认 N 条」，可改归属与删除

#### Scenario: 部分确认副徽标
- **WHEN** 提取完成且已有正式知识、仍有待确认候选
- **THEN** 来源行显示「部分确认」，并锁定改归属与删除

#### Scenario: 正式知识副徽标
- **WHEN** 提取完成且已产生 N 条正式知识、无待确认候选
- **THEN** 来源行显示「N 条正式知识」，并锁定改归属与删除

#### Scenario: 已处理副徽标
- **WHEN** 提取完成、候选全部拒绝且无正式知识
- **THEN** 来源行显示「已处理」，可改归属与删除

#### Scenario: 确认台仅展示待确认来源
- **WHEN** Source 处理成功并产生候选，且候选都未决策
- **THEN** 该来源出现在待处理来源列表，审阅状态为待确认

### Requirement: 项目归属修改

系统 MUST 支持把未归属 Source 归属到同一 Workspace 内的项目，或修改其所属项目；跨 Workspace 的项目 MUST 被拒绝；已产生正式知识（存在已确认候选或 Entry 证据）的 Source MUST 禁止改归属；处理中（`processing`）的 Source MUST 禁止改归属。

#### Scenario: 选择项目
- **WHEN** 用户把未归属 Source 归属到某个项目
- **THEN** Source 更新为归属该项目

#### Scenario: 拒绝跨空间项目
- **WHEN** 用户尝试把 Source 归属到其他 Workspace 的项目
- **THEN** 请求失败（400），归属不改变

#### Scenario: 已产生正式知识禁止改归属
- **WHEN** 用户尝试修改已产生正式知识的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

#### Scenario: 处理中禁止改归属
- **WHEN** 用户尝试修改处理中（`processing`）的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变

#### Scenario: 提取完成未确认可改归属
- **WHEN** 用户尝试修改提取完成但候选尚未确认、且未产生正式知识的 Source 的所属项目
- **THEN** 归属修改成功，待确认候选随之重新路由

### Requirement: 删除 Source

系统 MUST 支持删除 Source 并级联删除其 Attachment 记录、来源证据、候选与本地附件文件；已产生正式知识（存在 Entry 来源证据）的 Source MUST 禁止删除；处理中（`processing`）的 Source MUST 禁止删除；存在待确认候选时，前端 MUST 在删除前二次确认并提示将连带删除候选。

#### Scenario: 删除未处理来源
- **WHEN** 用户删除一个含图片的未处理 Source
- **THEN** Source 及其 Attachment 记录被删除，本地图片文件也被清理

#### Scenario: 已产生正式知识禁止删除
- **WHEN** 用户尝试删除已产生正式知识的 Source
- **THEN** 请求失败（409），Source 与证据保持不变

#### Scenario: 处理中禁止删除
- **WHEN** 用户尝试删除处理中（`processing`）的 Source
- **THEN** 请求失败（409），Source 保持不变

#### Scenario: 有待确认候选删除需确认
- **WHEN** 用户删除存在 N 条待确认候选、未产生正式知识的 Source
- **THEN** 前端提示将连带删除 N 条候选并要求确认，确认后执行删除

#### Scenario: 已产生正式知识的来源不展示操作
- **WHEN** 用户查看已产生正式知识的 Source 行
- **THEN** 该行不展示改归属下拉与删除按钮
