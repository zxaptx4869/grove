## 1. 产品与工程基线

- [x] 1.1 更新产品蓝图中的视图偏好、技术栈、端侧演进、优先级和已锁定决策，可用 `rg -n "390|移动端默认|响应式 Web" docs/产品蓝图与功能优先级.md` 验证旧承诺已清理
- [x] 1.2 更新 `AGENTS.md`、`README.md` 与 `openspec/config.yaml`，统一桌面 Web 和小屏边界，可用 `rg -n "390px 移动|390px 响应式|保证 390px" AGENTS.md README.md openspec/config.yaml` 验证无冲突

## 2. 前端规范

- [x] 2.1 更新 `frontend-foundation` 主规格，取消 390px 业务流程要求并记录桌面验收和小屏阻断规划
- [x] 2.2 更新 `.codex/skills/grove-ui-conventions` 的触发描述、实施规则、验收口径和界面元数据

## 3. 验证

- [x] 3.1 运行 `python3 /Users/hujun/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/grove-ui-conventions`
- [x] 3.2 运行 `openspec validate --all --strict` 与 `git diff --check`
