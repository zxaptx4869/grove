## 1. 规格核对

- [x] 1.1 确认 delta 规格覆盖主规格中两条陈旧需求：`创建项目并默认空目录` 与 `多项目归属与列表`
- [x] 1.2 运行 `openspec validate --all --strict`，确认 change 与主规格校验通过

## 2. 同步主规格

- [x] 2.1 运行 `openspec archive revise-project-lifecycle-and-empty-start`，将 delta 合并到主规格
- [x] 2.2 确认 `openspec/specs/project-management/spec.md` 中「创建项目并默认空目录」与「多项目归属与列表」的正文已更新，且不再出现「创建时 MUST 选择模板」或「149 个」旧描述

## 3. 验证

- [x] 3.1 运行 `openspec validate --all --strict`，确认归档后全部主规格通过
- [x] 3.2 运行 `rg -n "创建项目并选择目录模板|149 个|装修模板生成完整树" openspec/specs`，确认主规格无残留陈旧场景
- [x] 3.3 运行 `git status --short`，确认本次变更仅涉及 `openspec/`，无业务代码改动
