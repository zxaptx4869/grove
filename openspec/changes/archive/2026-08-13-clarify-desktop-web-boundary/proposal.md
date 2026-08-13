## Why

Grove 的确认台、目录管理、批量处理和思维导图属于高密度桌面工作流，为 390px 手机 Web 维护一套完整交互会显著增加设计与实现成本，却不符合前期真实使用场景。需要在继续设计关键页面前锁定端侧边界，让 Web 专注桌面深度整理，并把移动使用留给后续原生 App。

## What Changes

- **BREAKING**：取消“390px 手机 Web 可完成核心业务流程”的产品与工程承诺。
- 将 Grove Web 定义为桌面知识整理工作台，按桌面信息密度设计和验收。
- 小屏浏览器不加载业务工作台；原生 App 上线前仅提示用户在电脑上访问，上线后再改为 App 打开或下载承接页。
- 更新产品蓝图、代理守则、OpenSpec 上下文、README 和仓库级 UI skill，删除相互冲突的移动响应式要求。
- 保留浏览器缩放、桌面窄窗口、文字溢出和可访问性检查，但不为手机 Web 设计业务流程。

Non-Goals：

- 本 change 不实现小屏阻断页或设备检测逻辑。
- 本 change 不开发原生 App，也不定义 App 的完整功能规格。
- 本 change 不修改历史归档工件；历史文件继续记录当时的决策。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `frontend-foundation`：将 390px 完整响应式要求改为桌面 Web 支持范围、小屏阻断行为和相应的 Grove UI skill 验收口径。

## Impact

- 产品基线：`docs/产品蓝图与功能优先级.md`。
- 工程守则与入口：`AGENTS.md`、`README.md`、`openspec/config.yaml`。
- 主规格：`openspec/specs/frontend-foundation/spec.md`。
- 前端专属规范：`.codex/skills/grove-ui-conventions/`。
- 后续前端页面设计无需提供 390px 业务版，但实现时必须提供统一的小屏阻断页。
