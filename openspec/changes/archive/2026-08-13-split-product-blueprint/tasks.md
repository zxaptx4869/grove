## 1. 蓝图结构

- [x] 1.1 创建 `docs/产品蓝图.md` 短索引，包含稳定摘要、阅读规则和任务路由表
- [x] 1.2 将原长蓝图全部决策迁移到 `docs/产品蓝图/` 七份专题，并删除旧长文档
- [x] 1.3 核对原顶级章节、关键决策与未决问题在新结构中均有唯一归属

## 2. 当前生效引用

- [x] 2.1 更新 `README.md`、`AGENTS.md` 和 `openspec/config.yaml` 的入口、路由及工件规则
- [x] 2.2 更新 `project-workflow` 与 `frontend-foundation` 主规格
- [x] 2.3 更新 Grove UI skill 的渐进式读取规则和界面元数据

## 3. 验证

- [x] 3.1 检查当前生效文件无旧蓝图路径、所有 Markdown 相对链接目标存在
- [x] 3.2 校验专题覆盖、索引长度与重复决策边界
- [x] 3.3 运行 Grove UI skill 校验、`openspec validate --all --strict` 和 `git diff --check`
