---
name: openspec-explore
description: 用于产品方向、架构方案、设计取舍与需求边界的开放探索，或用户显式调用 openspec-explore / opsx:explore。普通故障排查、日志分析、对话效果诊断、错误定位和明确的 bug 修复不自动使用本技能；直接检查相关证据与代码。
allowed-tools: Bash(openspec:*)
license: MIT
metadata:
  author: openspec
  version: "1.6.0"
  generatedBy: "1.6.0"
  compatibility: Requires openspec CLI.
---

# OpenSpec 方案探索

用于尚未确定实现方向的产品、架构与需求讨论，帮助用户比较方案并明确边界。

## 使用边界

- 普通排查直接读取相关代码、日志、运行记录和必要规格，不因出现“排查”“分析问题”“效果不好”等表达而加载本技能，也不为排查例行加载其他 OpenSpec 技能。
- 排查发现设计缺口，不自动转入探索流程；先说明原因与影响。用户进一步要求讨论方案或取舍时，再按需使用本技能。
- 用户显式调用本技能时遵循其指定范围；仅要求方案探索时不修改业务代码。
- 用户随后明确要求实施或修复时，按仓库要求进入相应变更流程，不要求额外发送“退出探索”指令。

## 探索方式

- 围绕当前尚未确定的目标、约束和取舍展开，以相关规格与代码为依据。
- 只读取当前决策所需的文件；不默认通读历史 change、全部产品专题或生成长篇示例。
- 优先提出有依据的判断；只在缺失信息会改变方案时询问用户。
- 比较方案时说明行为差异、代价和适用条件；图示仅在有助于理解时使用。
- 探索本身不要求产出工件。用户要求记录或推进变更时，再维护对应 OpenSpec 工件。

## 按需使用 OpenSpec

当讨论涉及已有 change 或需要了解当前变更状态时，使用 `openspec list --json`；无关的概念讨论不必例行运行。

读取具体 change 时：

1. 执行 `openspec status --change <name> --json`。
2. 根据返回的 `changeRoot`、`artifactPaths` 和 `actionContext`，只读取相关的已有工件。
3. 将需求边界对应到 proposal/specs、技术取舍对应到 design、实施工作对应到 tasks；获得用户记录或更新要求后再编辑，保持工件一致。

用户指定独立的 OpenSpec store 时，先用 `openspec store list --json` 查明 store ID，并在读取或写入规格与 change 的命令上携带 `--store <id>`；未指定时使用最近的本地 `openspec/` 根目录。

完成探索后，说明已确定的结论、仍需决定的事项与适合的下一步，不强制创建 change 或要求确认。
