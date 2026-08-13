## 1. 流程骨架

- [x] 1.1 更新 `grove-ui-conventions` 的触发描述、任务风险分流和原型对齐门禁
- [x] 1.2 增加 `references/visual-fidelity-workflow.md`，包含基线表、准备/完成定义、验收矩阵和设计记录模板
- [x] 1.3 同步 `agents/openai.yaml` 的展示说明和默认提示

## 2. 规格与验证

- [x] 2.1 使用 skill-creator `quick_validate.py` 校验 Skill 结构，并确认主文档保持在 500 行以内
- [x] 2.2 以完整页面对齐、局部视觉调整、非视觉任务三个代表请求审查触发和流程分流
- [x] 2.3 运行 `openspec validate --all --strict` 与 `git diff --check`

## 3. 同步与交付

- [x] 3.1 将 delta spec 同步到 `frontend-foundation` 主规格
- [x] 3.2 完成归档与本地提交前检查，不 push、不 merge
