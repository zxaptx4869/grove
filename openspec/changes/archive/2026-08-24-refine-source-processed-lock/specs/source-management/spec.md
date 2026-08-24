## MODIFIED Requirements

### Requirement: 项目归属修改

系统 MUST 支持把未归属 Source 归属到同一 Workspace 内的项目，或修改其所属项目；跨 Workspace 的项目 MUST 被拒绝；已有确认候选或 Entry 来源证据的 Source MUST 禁止改归属；处理状态为已完成（`done`）的 Source MUST 禁止改归属。

#### Scenario: 选择项目
- **WHEN** 用户把未归属 Source 归属到某个项目
- **THEN** Source 更新为归属该项目

#### Scenario: 拒绝跨空间项目
- **WHEN** 用户尝试把 Source 归属到其他 Workspace 的项目
- **THEN** 请求失败（400），归属不改变

#### Scenario: 已归档来源禁止改归属
- **WHEN** 用户尝试修改已被确认候选或 Entry 证据引用的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

#### Scenario: 已处理完成来源禁止改归属
- **WHEN** 用户尝试修改处理状态为 `done` 的 Source 的所属项目
- **THEN** 请求失败（409），归属不改变，并返回可读原因

### Requirement: 删除 Source

系统 MUST 支持删除 Source 并级联删除其 Attachment 记录、来源证据与本地附件文件；当该 Source 是某正式 Entry 的来源证据时 MUST 阻止删除（作为纵深防御）；处理状态为已完成（`done`）的 Source MUST 禁止删除，且前端 MUST NOT 展示改归属与删除操作。

#### Scenario: 删除清理附件
- **WHEN** 用户删除一个含图片的未处理 Source
- **THEN** Source 及其 Attachment 记录被删除，本地图片文件也被清理

#### Scenario: 唯一证据阻止删除
- **WHEN** 用户删除某正式 Entry 的唯一来源证据 Source
- **THEN** 请求失败（409），Source 与证据保持不变

#### Scenario: 已处理完成来源禁止删除
- **WHEN** 用户尝试删除处理状态为 `done` 的 Source
- **THEN** 请求失败（409），Source 保持不变

#### Scenario: 已处理来源不展示操作
- **WHEN** 用户查看处理状态为 `done` 的 Source 行
- **THEN** 该行不展示改归属下拉与删除按钮
