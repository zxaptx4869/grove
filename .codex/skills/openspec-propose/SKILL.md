---
name: openspec-propose
description: 为需要正式 OpenSpec change 的功能或行为变更生成规划工件，或响应用户明确的提案请求。环境操作、普通排查和恢复既有行为的小 bug 不自动进入提案流程。
license: MIT
metadata:
  compatibility: Requires openspec CLI.
  author: openspec
  version: "1.0"
---

# 提出 OpenSpec 变更

按 [AGENTS.md](../../../AGENTS.md) 判断任务是否需要 change。仅讨论方案时不强制创建工件；用户已要求完整实施时，提案是整体任务的前置阶段。

## 创建与范围

1. 依据用户请求、相关产品专题、主规格与代码明确目标。可从证据解决的实现细节自行判断；只有会影响范围或关键行为的缺失信息才澄清，不默认通读所有产品文档。
2. 优先沿用本任务已明确的 change。需要新建时取简明的 kebab-case 名称，并先建立 `codex/<name>` 特性分支，再执行 `openspec new change <name>`。同名但目标不明确时先检查，仍无法判断才请求选择；不覆盖或混入无关变更。
3. 用 `openspec status --change <name> --json` 确认 schema、依赖和实际工件路径。用户指定独立 store 时先查询 `openspec store list --json`，在支持的命令上携带 `--store <id>`。

## 生成工件

- 按依赖顺序获取 `openspec instructions <artifact-id> --change <name> --json`，使用当前模板与规则。四类工件均保留；取得必要依赖后可继续，不为展示进度重复读取未变化的文件。
- proposal 写原因、范围、能力与影响；specs 写可验证的行为增量；design 写非显然的技术选择与理由，无新增决策时可简写；tasks 写可执行工作项与验收入口，不强制每次新增“骨架”阶段。
- Non-Goals 只列容易误入本次范围的相关能力。引用已有背景、需求与共享验收命令，不在多份工件中复制；不为填满模板制造备选方案或假想风险。
- `context` 与 `rules` 是写作约束，不复制进工件。使用 CLI 返回的实际输出路径；glob 工件应生成具体文件，不把 glob 字符串当作文件名。
- `MODIFIED` 必须包含完整更新后的需求块及保留的场景，与 CLI 归档语义一致。未涉及的需求不复制；不以节省篇幅为由截断被修改的需求。
- 初始状态用于确定依赖；中间仅在需要确认下一工件可生成、外部改动或出现错误时刷新状态。最终确认四类工件齐备并执行前置严格校验，不把 `apply-ready` 等同于验证通过。

## 交付

简述变更范围、工件位置、验证结果和未决事项。只要求提案时到此交付；已授权实施时，在前置条件满足后继续实施，不要求用户重复发送阶段命令。已有计划的修订批准、阶段提交及其他边界遵循 AGENTS.md。
