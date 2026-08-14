## Context

当前 `backend/app/ai/` 是一版未被业务使用的手写 `AIProvider` 抽象（`complete() -> AICandidate`），密钥只是 `Settings` 里的占位字符串。Grove 采用 BYOK：产品不提供模型，用户后续自己配置密钥。下一项 `add-organizing-agent-extraction` 需要结构化 Agent 输出与视觉 OCR，因此本 change 先把 PydanticAI provider/client 底座和密钥配置做好。

## Goals / Non-Goals

**Goals:**

- 用 PydanticAI provider/client 替换手写 `AIProvider` 骨架。
- 支持按 Workspace 配置文本（DeepSeek）与视觉（豆包）密钥。
- 密钥不明文入库，使用系统钥匙串/加密存储。
- 提供脱敏查询、保存、清除与测试连接接口。
- 提供文本/视觉模型服务层，供后续提取 Agent 使用。

**Non-Goals:**

- 不实现 Organizing Agent、Candidate、Extraction。
- 不实现图片 OCR 管道接线。
- 不提供内置密钥。
- 不做多供应商 UI 切换与用量统计。

## Decisions

### D1：BYOK，按 Workspace 配置

模型配置归属 Workspace：v1 只有一个默认 Workspace，因此当前等于「当前用户的默认空间」。新增 `ai_provider_settings` 表，每个 Workspace 一行，保存文本与视觉两类配置的 Provider、模型名、密钥尾号、可用状态与时间；完整密钥不落库。

### D2：密钥存储用系统钥匙串

新增 `SecretStore` 抽象：`get / put / delete`。默认实现使用 `keyring`（macOS Keychain / Windows Credential Manager / Linux Secret Service），密钥命名空间按 Workspace 与 Provider 隔离，例如 `grove.ai.<workspace_id>.deepseek`。

- 数据库只保存密钥尾号（last 4）等脱敏信息。
- API 永不返回完整密钥。
- 测试使用内存实现，避免触碰系统钥匙串。

这样满足「不明文」；云端部署若无法使用本地钥匙串，再在部署 change 引入云 Secret Manager，接口不变。

### D3：PydanticAI provider/client 作为模型底座

引入 `pydantic-ai` 与 OpenAI 兼容客户端依赖。服务层返回 PydanticAI `Model` 对象：

- 文本：`OpenAIChatModel(text_model, provider=DeepSeekProvider(api_key=...))`。
- 视觉：`OpenAIChatModel(vision_model, provider=OpenAIProvider(base_url="https://ark.cn-beijing.volces.com/api/v3", api_key=...))`，首个视觉模型固定为 `doubao-seed-2-0-lite-260428`。

旧的 `backend/app/ai/` 骨架移除；「AI 输出是候选」铁律下沉到后续 `Extraction/Candidate` 持久化边界，并由服务层约束结构化输出必须落候选。

### D4：服务层边界

新增 `backend/app/ai/` 或 `backend/app/services/ai_models.py`：

- `get_text_model(db, workspace)` / `get_vision_model(db, workspace)`；
- 未配置时返回离线测试模型；
- 真实 Provider 缺密钥时明确抛「未配置」。

业务代码只调用服务层，不直接创建 provider。

### D5：离线测试模型

使用 PydanticAI 的确定性测试模型（`TestModel`/`FunctionModel` 或等价机制）作为离线回退，保持现有 Demo 的「相同输入相同输出、不访问外部 API」能力，同时支持结构化输出，便于后续 Agent 测试。

### D6：模型设置 API

- `GET /api/settings/ai`：返回脱敏配置。
- `PUT /api/settings/ai/text`：保存文本密钥与模型。
- `PUT /api/settings/ai/vision`：保存视觉密钥与模型。
- `DELETE /api/settings/ai/text|vision`：清除对应配置。
- `POST /api/settings/ai/text/test`、`POST /api/settings/ai/vision/test`：测试连接。

测试连接对文本发起最小补全，对视觉发起最小图片理解；成功更新 `available`，失败返回错误且不改配置。

### D7：前端模型设置

在应用壳的用户菜单中增加「模型设置」入口，或新增一个设置页。界面只展示脱敏状态、尾号与「测试连接」结果；保存与测试均使用 `useGroveMutation` 并显式失效 `aiSettings` 查询键。

### D8：配置与依赖

- `backend/pyproject.toml` 增加 `pydantic-ai`、OpenAI 兼容依赖与 `keyring`。
- `.env.example` 移除运行时密钥占位，保留 Provider/模型名等非敏感默认值。
- 测试环境使用内存 `SecretStore` 与离线模型，不发网络请求。

## Risks / Trade-offs

- [系统钥匙串在无桌面环境不可用] → 抽象 `SecretStore`；部署 change 再换云 Secret Manager。
- [测试连接依赖真实网络] → 测试用注入的假 Provider 验证状态流转，联调用真实 Provider。
- [豆包视觉模型先锁定但未做完整评测] → 记录为后续 spike；provider 抽象允许替换。
- [PydanticAI 版本与 Python 3.12 兼容] → 安装时锁定与项目一致的稳定版本。

## Migration Plan

- 新增 `ai_provider_settings` 表（唯一 Workspace 外键，脱敏字段）。
- 无密钥数据迁移：现有 `.env` 占位不迁移；用户重新在设置页配置。

## Open Questions

- 豆包方舟默认 base_url 为 `https://ark.cn-beijing.volces.com/api/v3`，首个视觉模型为 `doubao-seed-2-0-lite-260428`；如用户使用其他区域或模型，再增加配置项。
- 是否需要在保存前强制测试连接成功（当前设计允许先保存、后测试）。
