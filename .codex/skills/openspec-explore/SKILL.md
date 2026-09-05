---
name: openspec-explore
description: 用于产品方向、架构方案、设计取舍与需求边界的开放探索，或用户显式调用 openspec-explore / opsx:explore。普通故障排查、日志分析、对话效果诊断和明确的 bug 修复不自动使用本技能。
license: MIT
metadata:
  compatibility: Requires openspec CLI only when inspecting a change.
  author: openspec
  version: "1.6.0"
---

# OpenSpec 方案探索

用于尚未确定实现方向的讨论，以相关规格与代码帮助用户判断方案。任务分流与批准遵循 [AGENTS.md](../../../AGENTS.md)。

## 使用边界

- 普通排查直接读取相关代码、日志、运行记录和必要规格，不因出现“分析问题”“效果不好”等表达加载本技能，也不例行加载其他 OpenSpec Skill。
- 排查发现设计缺口时先说明原因与影响，不自动展开方案探索或另建 change。用户要求讨论取舍时再使用本技能。
- 用户仅要求探索时不修改业务代码，也不强制生成工件。随后明确要求修复或实施时按仓库任务分流继续，无需额外发送“退出探索”。

## 探索方式

- 围绕当前目标、约束和取舍提出有依据的判断；只读当前决策所需文件，复用未变化的内容，不默认通读历史 change、全部产品专题或生成长篇范例。
- 可从现有证据解决的细节自行判断；缺失信息会实质性改变方案且无法推断时再澄清。
- 比较行为差异、代价和适用条件；图示仅在有助理解时使用。
- 用户要求记录或推进变更时才维护工件；已有计划的修订先按批准规则展示整体建议。

## 按需使用 OpenSpec

已有明确 change 时可直接用 `openspec status --change <name> --json` 定位相关工件；只有需要发现目标或了解多项状态时才用 `openspec list --json`。无关概念讨论不必运行 CLI。

用户指定独立 store 时先查询 `openspec store list --json`，并在支持的命令上保留 `--store <id>`；未指定时使用本仓库。完成探索后说明已确定结论、仍需决定的事项与下一步；不强制创建 change 或要求确认，用户已授权的后续工作按范围继续。
