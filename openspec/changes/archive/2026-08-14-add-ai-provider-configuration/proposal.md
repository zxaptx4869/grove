## Why

下一项 `add-organizing-agent-extraction` 需要真实模型与视觉 OCR，但当前 `backend/app/ai/` 只有一版未被业务使用的 `AIProvider` 骨架，密钥也只是 `.env` 里的占位键。Grove 采用「用户自带 key（BYOK）」：产品不提供模型，用户后续自己配置密钥。因此在做提取 Agent 之前，先落地模型密钥配置与 PydanticAI provider/client 底座，避免把「密钥管理」和「提取逻辑」混在一个 change 里。

## What Changes

- 修改 `ai-provider` 能力：
  - 用 PydanticAI 的 provider/client 体系替换现有手写 `AIProvider` 骨架；
  - 文本与视觉模型解耦，分别通过统一服务层获取；
  - 首个文本 Provider 固定为 DeepSeek，首个视觉/OCR Provider 固定为豆包视觉模型；
  - 密钥 BYOK：用户为当前 Workspace 配置自己的密钥，产品不内置密钥；
  - 密钥不明文入库：通过系统钥匙串/加密存储，数据库只保存脱敏元信息；
  - 提供测试连接能力校验配置是否可用；
  - 未配置或校验失败时明确报错，测试环境可回退到离线确定性模型。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `ai-provider`: 改为 PydanticAI provider/client 体系，新增 BYOK 密钥配置、DeepSeek 文本 Provider、豆包视觉 Provider、密钥安全存储与连接校验。

## Impact

- 后端：新增模型设置模型与 API、密钥存储服务（系统钥匙串/加密抽象）、PydanticAI provider 工厂；移除或停用旧 `app/ai/` 骨架；更新 `pyproject.toml` 依赖与 `.env.example`。
- 前端：新增「模型设置」页面或入口，配置文本/视觉密钥、展示脱敏状态、测试连接。
- 配置：密钥不再从 `.env` 作为运行时唯一来源，改为按 Workspace 存储；`.env` 仅保留非敏感默认项。
- 无实际提取逻辑：本 change 只提供模型访问与配置底座。

## Non-Goals

- 不实现 Organizing Agent、语义拆分、Candidate 或 Extraction（留给 `add-organizing-agent-extraction`）。
- 不实现图片 OCR 处理管道接线（留给提取 change）。
- 不提供内置或共享的模型密钥。
- 不做多 Workspace 密钥共享、计费、用量统计或供应商切换 UI。
- 不做真实中文截图 OCR 质量评测的完整评测集（仅作为后续 change 的 spike 范围）。
