## ADDED Requirements

### Requirement: 用户可见执行阶段必须独立于恢复步骤

普通 answer Run MUST 在现有 dialogue-loop 状态快照中保存可选的用户可见 `stage`，其值只能来自统一循环已有 activity callback；`current_step` MUST 继续表示 Worker 领取与崩溃恢复边界，不得被界面阶段覆盖。生产适配器 MUST 去重连续相同阶段并仅在真实变化时用短事务持久化，终态快照 MUST 清除活动阶段。

#### Scenario: 阶段更新不影响 Worker 恢复

- **WHEN** processing Run 从 organizing 进入 querying、reading_entries 和 finalizing
- **THEN** `current_step` 始终保持 `dialogue_loop`，API 的 `dialogue_stage` 随真实事件更新，连续重复事件不产生重复持久化

#### Scenario: 刷新恢复当前活动阶段

- **WHEN** 客户端在 processing Run 期间刷新并重新查询消息页
- **THEN** API 从 Run 快照返回最近已提交的 `dialogue_stage`，无需浏览器计时推测

#### Scenario: 终态不返回旧活动阶段

- **WHEN** Run 完成、部分完成、失败或取消
- **THEN** 终态响应的 `dialogue_stage` 为空，旧 processing 快照不得使客户端继续显示动效
