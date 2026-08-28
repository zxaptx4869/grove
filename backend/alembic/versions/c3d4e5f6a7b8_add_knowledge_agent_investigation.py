"""add knowledge agent investigation tables and answer mode fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-28 20:00:00.000000

新增有界自主调查的 Investigation / Round / Query 三张表，并扩展 Run、
模型调用、工具调用与 Evidence 的回答模式与调查归属字段。
关键约束：
- knowledge_investigations 的 run_id 唯一：调查与 Run 一对一；
- knowledge_investigation_rounds 的 (investigation_id, round_number) 唯一：
  同一调查的轮次号稳定且不重复（恢复/并发写入由应用幂等 + 该约束防御）；
- knowledge_investigation_queries 的 (investigation_id, normalized_query_hash)
  唯一：Run 内规范化查询全局去重，重复查询不重复计费/计数；
- 三张表冗余 workspace_id / owner_user_id，读取仍经 Run/对话所有权复验。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bigint() -> sa.BigInteger:
    """返回与 ORM 一致的双库兼容主键/外键类型。"""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """新增调查表并扩展既有表字段。"""
    op.create_table(
        "knowledge_investigations",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            _bigint(),
            sa.ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            _bigint(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            _bigint(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column(
            "project_id",
            _bigint(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_name", sa.String(length=64), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("requested_answer_mode", sa.String(length=16), nullable=False),
        sa.Column("actual_answer_mode", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("max_rounds", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "max_queries_per_round",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "max_total_queries",
            sa.Integer(),
            server_default=sa.text("6"),
            nullable=False,
        ),
        sa.Column(
            "max_entries",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column(
            "max_evidence",
            sa.Integer(),
            server_default=sa.text("12"),
            nullable=False,
        ),
        sa.Column(
            "current_round",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_queries_executed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "distinct_entries_found",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "citable_evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("coverage_summary", sa.Text(), nullable=True),
        sa.Column("gaps_summary", sa.Text(), nullable=True),
        sa.Column("conflicts_summary", sa.Text(), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", name="uq_knowledge_investigation_run"),
    )
    op.create_index(
        op.f("ix_knowledge_investigations_run_id"),
        "knowledge_investigations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigations_conversation_id"),
        "knowledge_investigations",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigations_workspace_id"),
        "knowledge_investigations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigations_owner_user_id"),
        "knowledge_investigations",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigations_project_id"),
        "knowledge_investigations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_status"),
        "knowledge_investigations",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_investigation_rounds",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "investigation_id",
            _bigint(),
            sa.ForeignKey("knowledge_investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            _bigint(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            _bigint(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("controller_action", sa.String(length=16), nullable=True),
        sa.Column("coverage_json", sa.Text(), nullable=True),
        sa.Column("gaps_json", sa.Text(), nullable=True),
        sa.Column("conflicts_json", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "queries_planned",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "queries_executed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "entries_added",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evidence_added",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "investigation_id",
            "round_number",
            name="uq_knowledge_investigation_round_number",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_investigation_rounds_investigation_id"),
        "knowledge_investigation_rounds",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_rounds_workspace_id"),
        "knowledge_investigation_rounds",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_rounds_owner_user_id"),
        "knowledge_investigation_rounds",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_round_claim"),
        "knowledge_investigation_rounds",
        ["investigation_id", "status", "round_number"],
        unique=False,
    )

    op.create_table(
        "knowledge_investigation_queries",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "investigation_id",
            _bigint(),
            sa.ForeignKey("knowledge_investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id",
            _bigint(),
            sa.ForeignKey("knowledge_investigation_rounds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workspace_id",
            _bigint(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            _bigint(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("normalized_query_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_counts_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "investigation_id",
            "normalized_query_hash",
            name="uq_knowledge_investigation_query_hash",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_investigation_queries_investigation_id"),
        "knowledge_investigation_queries",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_queries_round_id"),
        "knowledge_investigation_queries",
        ["round_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_queries_workspace_id"),
        "knowledge_investigation_queries",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_queries_owner_user_id"),
        "knowledge_investigation_queries",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_investigation_query_round"),
        "knowledge_investigation_queries",
        ["investigation_id", "round_number", "sequence"],
        unique=False,
    )

    # Run：请求/实际回答模式、当前轮次与调查摘要（可空，旧 Run 兼容）
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("request_answer_mode", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("actual_answer_mode", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "current_round",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("investigation_summary", sa.Text(), nullable=True)
        )

    # 模型调用：调查归属（路由/控制器/综合阶段）
    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "investigation_id",
                _bigint(),
                sa.ForeignKey(
                    "knowledge_investigations.id",
                    ondelete="SET NULL",
                    name="fk_knowledge_model_invocations_investigation",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("round_number", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("query_sequence", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            "ix_knowledge_agent_model_invocations_investigation_id",
            ["investigation_id"],
            unique=False,
        )

    # 工具调用：逐轮查询归属
    with op.batch_alter_table("knowledge_agent_tool_calls") as batch_op:
        batch_op.add_column(
            sa.Column(
                "investigation_id",
                _bigint(),
                sa.ForeignKey(
                    "knowledge_investigations.id",
                    ondelete="SET NULL",
                    name="fk_knowledge_tool_calls_investigation",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("round_number", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("query_sequence", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            "ix_knowledge_agent_tool_calls_investigation_id",
            ["investigation_id"],
            unique=False,
        )

    # Evidence：轮次归属（多轮命中同一 Evidence 幂等复用并保留首轮归属）
    with op.batch_alter_table("knowledge_agent_evidences") as batch_op:
        batch_op.add_column(
            sa.Column("round_number", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("query_sequence", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """回滚：先删扩展字段，再删调查表。"""
    with op.batch_alter_table("knowledge_agent_evidences") as batch_op:
        batch_op.drop_column("query_sequence")
        batch_op.drop_column("round_number")

    with op.batch_alter_table("knowledge_agent_tool_calls") as batch_op:
        batch_op.drop_index("ix_knowledge_agent_tool_calls_investigation_id")
        batch_op.drop_column("query_sequence")
        batch_op.drop_column("round_number")
        batch_op.drop_column("investigation_id")

    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.drop_index("ix_knowledge_agent_model_invocations_investigation_id")
        batch_op.drop_column("query_sequence")
        batch_op.drop_column("round_number")
        batch_op.drop_column("investigation_id")

    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("investigation_summary")
        batch_op.drop_column("current_round")
        batch_op.drop_column("actual_answer_mode")
        batch_op.drop_column("request_answer_mode")

    op.drop_table("knowledge_investigation_queries")
    op.drop_table("knowledge_investigation_rounds")
    op.drop_table("knowledge_investigations")
