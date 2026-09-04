"""应用配置：基于 pydantic-settings 的统一配置入口。

所有环境变量集中在这里定义；密钥类键位在本骨架阶段只保留占位，
真实接入（AI、认证）由后续 change 填充。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Grove 后端配置。

    读取顺序：环境变量 > backend/.env > 默认值。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用信息
    app_name: str = "知林 Grove 后端"
    app_version: str = "0.1.0"

    # 数据库：开发默认 SQLite；生产通过环境变量切换 MySQL 8
    database_url: str = "sqlite+aiosqlite:///./grove.db"

    # 允许跨域的前端来源（逗号分隔）
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 处理 Provider：organizing（默认）/ 其他占位
    processing_provider: str = Field(default="organizing", description="处理 Provider 标识")

    # 进程内处理 Worker：应用启动时是否开启（测试环境可关闭）
    processing_worker_enabled: bool = Field(default=True, description="是否启用处理 Worker")

    # 项目上下文生成器：llm（默认，无密钥时离线回退）/ demo（确定性）/ 其他占位
    context_generator: str = Field(default="llm", description="项目上下文生成器标识")

    # 项目上下文刷新防抖时长（秒）
    context_refresh_debounce_seconds: float = Field(
        default=60.0, description="项目上下文刷新防抖时长"
    )

    # 项目上下文最小生成间隔（秒）：距上次成功生成不足该时长时不立即重新生成
    context_min_interval_seconds: float = Field(default=300.0, description="项目上下文最小生成间隔")

    # 进程内项目上下文 Worker：应用启动时是否开启（测试环境可关闭）
    context_worker_enabled: bool = Field(default=True, description="是否启用项目上下文 Worker")

    # 进程内目录起草 Worker（测试环境可置 false）
    directory_draft_worker_enabled: bool = Field(
        default=True, description="是否启用目录起草 Worker"
    )

    # 进程内 embedding 向量重建 Worker（测试环境可置 false）
    embedding_worker_enabled: bool = Field(
        default=True, description="是否启用 embedding 向量重建 Worker"
    )

    # 进程内知识 Agent Worker（测试环境可置 false）
    knowledge_agent_worker_enabled: bool = Field(
        default=True, description="是否启用知识 Agent Worker"
    )

    # 知识 Agent 固定执行图预算：搜索召回上限、回答上下文 Entry 上限与 Evidence 读取上限
    knowledge_agent_recall_limit: int = Field(default=20, description="知识 Agent 混合召回候选上限")
    knowledge_agent_context_limit: int = Field(
        default=15, description="知识 Agent 回答上下文最多使用的 Entry 条数"
    )
    knowledge_agent_evidence_limit: int = Field(
        default=30, description="知识 Agent 单 Run 最多读取的 Source/Attachment 证据数"
    )
    knowledge_agent_history_limit: int = Field(
        default=8, description="上下文决策最多使用的近期消息条数"
    )
    knowledge_agent_history_message_chars: int = Field(
        default=500, description="上下文决策单条历史消息截断长度"
    )
    knowledge_agent_working_set_limit: int = Field(
        default=15, description="工作集版本最多保存的 Entry 线索数"
    )
    # 知识 Agent 有界调查预算：创建 Investigation 时固化，客户端/模型不能放大
    knowledge_agent_investigation_max_rounds: int = Field(
        default=3, description="深度调查默认最多轮次"
    )
    knowledge_agent_investigation_max_queries_per_round: int = Field(
        default=3, description="深度调查每轮最多查询数"
    )
    knowledge_agent_investigation_max_total_queries: int = Field(
        default=6, description="深度调查全 Run 最多不同查询数"
    )
    knowledge_agent_investigation_max_entries: int = Field(
        default=30, description="深度调查最多发现的不同 Entry 数"
    )
    knowledge_agent_investigation_max_evidence: int = Field(
        default=12, description="深度调查最多可引用 Evidence 条数"
    )
    # 回答模式路由与调查控制器模型设置
    knowledge_agent_answer_mode_router_enabled: bool = Field(
        default=True, description="auto 回答模式路由是否启用；关闭时 auto 一律 quick"
    )
    knowledge_agent_answer_mode_router_timeout_seconds: float = Field(
        default=20.0, description="回答模式路由模型调用超时（秒）"
    )
    knowledge_agent_investigation_controller_timeout_seconds: float = Field(
        default=30.0, description="调查控制器模型调用超时（秒）"
    )
    # 调查控制器输出摘要长度上限（服务端确定性截断）
    knowledge_agent_investigation_summary_items: int = Field(
        default=20, description="控制器 coverage/gaps/conflicts 最多条目数"
    )
    knowledge_agent_investigation_summary_item_chars: int = Field(
        default=200, description="控制器单条摘要最大字符数"
    )
    knowledge_agent_investigation_reason_chars: int = Field(
        default=500, description="控制器 reason 最大字符数"
    )
    knowledge_agent_investigation_query_chars: int = Field(
        default=200, description="调查控制器单条文本查询最大字符数"
    )
    # 结构化 Entry 查找预算：候选上限、持久化结果上限、分页与摘要长度
    knowledge_agent_result_candidate_limit: int = Field(
        default=50, description="结构化 Entry 查找混合召回候选上限"
    )
    knowledge_agent_result_persist_limit: int = Field(
        default=30, description="结构化 Entry 结果快照最多持久化条数"
    )
    knowledge_agent_result_default_page_size: int = Field(
        default=6, description="结构化 Entry 结果默认每页条数"
    )
    knowledge_agent_result_max_page_size: int = Field(
        default=12, description="结构化 Entry 结果最大每页条数"
    )
    knowledge_agent_result_excerpt_chars: int = Field(
        default=240, description="结构化 Entry 结果摘要最大字符数"
    )
    knowledge_agent_result_node_path_chars: int = Field(
        default=400, description="结构化 Entry 结果目录路径最大字符数"
    )
    knowledge_agent_result_match_hint_chars: int = Field(
        default=120, description="结构化 Entry 结果匹配线索最大字符数"
    )
    knowledge_agent_result_json_bytes_limit: int = Field(
        default=60000,
        description=(
            "结构化 Entry 结果 JSON 序列化后最大字节数（须低于 MySQL TEXT "
            "65535 字节上限，SQLite 无上限）"
        ),
    )
    # 一次结构化查询计划（阶段 B1）：默认关闭，范围只由 Run 固化上下文注入
    knowledge_agent_structured_query_enabled: bool = Field(
        default=False, description="知识 Agent 一次结构化查询计划是否启用"
    )
    knowledge_agent_structured_query_planner_timeout_seconds: float = Field(
        default=20.0, description="结构化查询规划模型调用超时（秒）"
    )
    knowledge_agent_structured_query_plan_bytes_limit: int = Field(
        default=12000, description="规范化结构化查询计划 JSON 最大字节数"
    )
    knowledge_agent_structured_query_max_outputs: int = Field(
        default=3, description="单个结构化查询计划最多输出数"
    )
    knowledge_agent_structured_query_max_tool_calls: int = Field(
        default=3, description="单个结构化查询计划最多只读工具调用数"
    )
    knowledge_agent_structured_query_entry_limit: int = Field(
        default=30, description="query_entries 单次最多返回并持久化的 Entry 数"
    )
    knowledge_agent_structured_query_semantic_candidate_limit: int = Field(
        default=50, description="含 semantic_query 时最多处理的语义候选数"
    )
    knowledge_agent_structured_query_bucket_limit: int = Field(
        default=24, description="group_count 单次最多返回的分组桶数"
    )
    knowledge_agent_structured_query_execution_timeout_seconds: float = Field(
        default=15.0, description="结构化查询确定性执行总超时（秒）"
    )
    knowledge_agent_structured_query_result_json_bytes_limit: int = Field(
        default=60000,
        description=("结构化查询 v2 结果 JSON 最大字节数（低于 MySQL TEXT 65535 字节）"),
    )
    # 结果形态路由：auto 请求独立路由；关闭时 auto 一律 answer
    knowledge_agent_result_mode_router_enabled: bool = Field(
        default=True, description="auto 结果形态路由是否启用；关闭时 auto 一律综合回答"
    )
    knowledge_agent_result_mode_router_timeout_seconds: float = Field(
        default=20.0, description="结果形态路由模型调用超时（秒）"
    )
    # 开放讨论特性开关：关闭时完全沿用当前 Grove-only 执行图与响应
    knowledge_agent_open_discussion_enabled: bool = Field(
        default=False, description="知识 Agent 开放讨论/依据规划是否启用"
    )
    knowledge_agent_basis_route_timeout_seconds: float = Field(
        default=20.0, description="依据规划模型调用超时（秒）"
    )
    # 回答阶段有界用户陈述预算：数量与单条长度上限
    knowledge_agent_statement_limit: int = Field(
        default=6, description="回答阶段最多采用当前话题近期用户陈述条数"
    )
    knowledge_agent_statement_message_chars: int = Field(
        default=800, description="回答阶段单条用户陈述最大字符数"
    )
    # quick 复合回答：默认关闭；模型只提出候选，服务端限制计划与执行预算
    knowledge_agent_composite_answer_enabled: bool = Field(
        default=False, description="知识 Agent quick 复合回答计划是否启用"
    )
    knowledge_agent_composite_answer_planner_timeout_seconds: float = Field(
        default=20.0, ge=1.0, le=120.0, description="复合回答规划模型超时（秒）"
    )
    knowledge_agent_composite_answer_max_requirements: int = Field(
        default=8, ge=1, le=20, description="单次复合回答最多回答义务数"
    )
    knowledge_agent_composite_answer_max_retrieval_requests: int = Field(
        default=3, ge=0, le=8, description="单次复合回答最多 Grove 检索请求数"
    )
    knowledge_agent_composite_answer_max_structured_requests: int = Field(
        default=2, ge=0, le=5, description="单次复合回答最多结构化请求数"
    )
    knowledge_agent_composite_answer_plan_bytes_limit: int = Field(
        default=24000, ge=1000, le=60000, description="规范化复合计划 JSON 最大字节数"
    )
    knowledge_agent_composite_answer_execution_bytes_limit: int = Field(
        default=60000,
        ge=1000,
        le=64000,
        description="复合回答执行检查点 JSON 最大字节数",
    )
    knowledge_agent_composite_answer_max_entries: int = Field(
        default=30, ge=1, le=100, description="复合回答最多读取的不同 Entry 数"
    )
    knowledge_agent_composite_answer_max_evidence: int = Field(
        default=30, ge=1, le=100, description="复合回答最多使用的 Evidence 数"
    )
    knowledge_agent_composite_answer_execution_timeout_seconds: float = Field(
        default=30.0, ge=1.0, le=180.0, description="复合回答一次受控执行总超时（秒）"
    )
    # quick 共享执行图：独立开关与服务端固化预算，默认关闭
    knowledge_agent_shared_execution_graph_enabled: bool = Field(
        default=False, description="quick 复合回答共享执行图是否启用"
    )
    knowledge_agent_shared_execution_graph_max_nodes: int = Field(
        default=24, ge=1, le=100, description="共享执行图最大节点数"
    )
    knowledge_agent_shared_execution_graph_max_depth: int = Field(
        default=4, ge=1, le=20, description="共享执行图最大深度"
    )
    knowledge_agent_shared_execution_graph_max_dependencies: int = Field(
        default=4, ge=0, le=20, description="共享执行图单节点最大依赖数"
    )
    knowledge_agent_shared_execution_graph_max_concurrency: int = Field(
        default=2, ge=1, le=16, description="共享执行图最大并发度"
    )
    knowledge_agent_shared_execution_graph_max_tool_calls: int = Field(
        default=12, ge=0, le=100, description="共享执行图最大工具调用数"
    )
    knowledge_agent_shared_execution_graph_max_entries: int = Field(
        default=30, ge=0, le=500, description="共享执行图最大 Entry 数"
    )
    knowledge_agent_shared_execution_graph_max_evidence: int = Field(
        default=30, ge=0, le=500, description="共享执行图最大 Evidence 数"
    )
    knowledge_agent_shared_execution_graph_max_buckets: int = Field(
        default=24, ge=0, le=500, description="共享执行图最大分组桶数"
    )
    knowledge_agent_shared_execution_graph_bytes_limit: int = Field(
        default=24000, ge=1000, le=60000, description="共享执行图 JSON 最大字节数"
    )
    knowledge_agent_shared_execution_graph_state_bytes_limit: int = Field(
        default=60000, ge=1000, le=64000, description="共享执行图 state JSON 最大字节数"
    )
    knowledge_agent_shared_execution_graph_timeout_seconds: float = Field(
        default=30.0, ge=1.0, le=180.0, description="共享执行图总耗时预算（秒）"
    )

    # 知识 Agent Worker 租约（秒）：processing 超过该阈值可恢复重试
    knowledge_agent_lease_seconds: int = Field(
        default=300, description="知识 Agent Run 处理租约时长（秒）"
    )

    # 模型密钥存储：keychain（默认）/ memory（测试）
    secret_store: str = Field(default="keychain", description="密钥安全存储实现")

    # 文本模型：产品不提供密钥，用户 BYOK 配置
    text_provider: str = Field(default="deepseek", description="文本模型 Provider")
    text_model: str = Field(default="deepseek-chat", description="文本模型名")

    # 视觉模型：产品不提供密钥，用户 BYOK 配置
    vision_provider: str = Field(default="doubao", description="视觉模型 Provider")
    vision_model: str = Field(default="doubao-seed-2-0-lite-260428", description="视觉模型名")
    doubao_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        description="豆包方舟 OpenAI 兼容地址",
    )

    # 附件存储目录：默认相对 backend 运行目录，由存储服务解析
    attachment_dir: str = Field(default="uploads", description="本地附件存储目录")

    # ---- 会话与 Cookie ----
    session_cookie_name: str = Field(default="grove_session", description="会话 Cookie 名称")
    session_max_age_days: int = Field(default=30, description="会话有效期（天）")
    cookie_secure: bool = Field(default=False, description="生产环境置 True，Cookie 仅 HTTPS 传输")

    # ---- 会话与认证占位键 ----
    auth_secret_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的前端来源解析为列表。"""
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()
