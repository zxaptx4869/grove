# native-knowledge-agent-entry-revision Specification

## Purpose
TBD - created by archiving change add-knowledge-agent-entry-revision. Update Purpose after archive.
## Requirements
### Requirement: 原生端 Entry 详情保持只读边界
原生 App MUST 仅提供明确 Entry 的当前正文与关联来源阅读，不提供 Entry 修订、差异编辑、确认应用或撤销入口；共享 Revision 服务与其他端调用方不受影响。

#### Scenario: 阅读当前 Entry
- **WHEN** 用户从知识列表打开带明确 Entry 标识的条目
- **THEN** 移动端只调用现有 Entry 只读接口展示当前内容，不出现修订、保存、应用或撤销操作

#### Scenario: 三尺寸与系统能力验收
- **WHEN** 在 360×800、390×844、412×915 及可用 iOS/Android 环境走查完整路径
- **THEN** 顶栏、thread、Composer、键盘、Sheet、全屏差异、底栏和安全区无非预期遮挡/溢出，并保存截图与未验证项

#### Scenario: 原型中的批量内容不抢跑
- **WHEN** 正式页面渲染单 Entry 修订路径
- **THEN** 不出现重复 Entry 标记、冲突对象、多条合并计数或“确认合并”文案

