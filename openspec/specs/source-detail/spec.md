# source-detail Specification

## Purpose
TBD - created by archiving change add-source-detail-view. Update Purpose after archive.
## Requirements
### Requirement: 来源详情查看

系统 MUST 提供来源详情弹窗：展示来源标题、采集说明、处理状态、所属项目、候选数、正式知识数与创建时间；MUST 展示全部附件原始材料（图片可点击放大查看原图，文字/OCR 全文完整显示）；MUST 提供候选列表（无候选时显示空状态），并保留候选证据高亮与切换定位。

#### Scenario: 查看来源详情

- **WHEN** 用户从来源列表点击「查看」或点击来源标题
- **THEN** 打开来源详情弹窗，展示元信息、全部附件与候选列表

#### Scenario: 图片放大查看

- **WHEN** 用户点击详情中的图片附件
- **THEN** 全屏遮罩显示原图，Esc 或点击可关闭

#### Scenario: 无候选来源

- **WHEN** 来源没有候选（如失败或未处理）
- **THEN** 详情仍可打开，候选区显示空状态，材料区正常展示

### Requirement: 来源列表查看入口

来源列表 MUST 为所有来源提供「查看」按钮（不限于有候选的来源），点击来源标题 MUST 同样打开来源详情；「查看」入口 MUST NOT 与删除/重试等操作冲突。

#### Scenario: 所有来源可查看

- **WHEN** 用户查看任意状态（待处理/处理中/提取完成/失败）的来源列表
- **THEN** 每行都有「查看」入口，点击可打开详情

#### Scenario: 点击标题打开详情

- **WHEN** 用户点击来源标题
- **THEN** 打开该来源的详情弹窗

