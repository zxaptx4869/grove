## 1. 清理一次性文档

- [x] 1.1 删除 `docs/初始化提示词.md` 与 `docs/UI基础建设提示词.md`
- [x] 1.2 检查当前入口不再引用两份提示词，历史归档引用保持不变

## 2. 更新 Grove UI skill

- [x] 2.1 重写 `SKILL.md` 的触发描述、权威来源、工作流和产品 UI 不变量
- [x] 2.2 同步 `agents/openai.yaml` 的展示信息与默认提示词
- [x] 2.3 运行 `backend/.venv/bin/python /Users/hujun/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/grove-ui-conventions`

## 3. 验证与归档

- [x] 3.1 运行 `git diff --check` 与 `openspec validate --all --strict`
- [x] 3.2 同步 `frontend-foundation` 主规格并归档 change，再次运行严格校验
