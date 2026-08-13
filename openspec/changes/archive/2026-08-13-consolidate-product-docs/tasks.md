## 1. 文档职责收敛

- [x] 1.1 将 `PROPOSAL.md` 中仍有效的技术选型、AI 架构和开放技术决策合并到产品蓝图
- [x] 1.2 更新 `README.md`，使其成为唯一文档入口并包含目录结构、开发与验证命令
- [x] 1.3 更新 `AGENTS.md` 与 `openspec/config.yaml`，移除对旧提案和文档路由的当前依赖

## 2. 删除过时入口

- [x] 2.1 删除 `PROPOSAL.md` 与 `docs/项目上下文与文档路由.md`
- [x] 2.2 搜索当前文档和配置中的旧引用，确认仅归档工件与历史任务书保留历史路径

## 3. 验证与归档

- [x] 3.1 运行 `git diff --check`，确认 Markdown 与补丁格式无错误
- [x] 3.2 运行 `openspec validate --all --strict`，确认 change 和主规格校验通过
- [x] 3.3 同步 `project-workflow` 主规格并归档本 change，再次运行 `openspec validate --all --strict`
