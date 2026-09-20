# native-knowledge-agent-entry-revision Specification

## Purpose
记录原生移动端旧 Entry Revision 编辑、确认和撤销流程退役后的只读边界。当前知识与关联来源仍可阅读，移动端不发起修订；共享后端的版本、来源与人在环确认规则保持独立。

## Requirements

### Requirement: 原生端 Entry 详情保持只读边界
原生 App MUST 仅提供明确 Entry 的当前正文与关联来源阅读，不提供 Entry 修订、差异编辑、确认应用或撤销入口；共享 Revision 服务与其他端调用方不受影响。

#### Scenario: 阅读当前 Entry
- **WHEN** 用户从知识列表打开带明确 Entry 标识的条目
- **THEN** 移动端只调用现有 Entry 只读接口展示当前内容，不出现修订、保存、应用或撤销操作
