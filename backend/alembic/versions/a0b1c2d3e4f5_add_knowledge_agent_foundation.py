"""add knowledge agent foundation tables

Revision ID: a0b1c2d3e4f5
Revises: e5f6a7b8c9d0
Create Date: 2026-08-28 10:00:00.000000

新增知识对话、消息、Agent Run、工具调用、模型调用与 Run Evidence 表。
关键约束：
- knowledge_messages 的 (conversation_id, client_message_id) 唯一约束实现幂等提交；
- knowledge_agent_runs 的 (conversation_id, active_slot) 唯一约束实现单会话串行：
  活动态写固定值 'active'，终态置 NULL（SQLite 与 MySQL 的唯一索引都允许多个 NULL，
  因此终态释放槽位后同一对话可创建新 Run）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bigint() -> sa.BigInteger:
    """返回与 ORM 一致的双库兼容主键/外键类型。

    MySQL 8 使用 BIGINT；SQLite 必须用 INTEGER 才能获得 rowid 自增语义
    （BIGINT PRIMARY KEY 不会自动生成 id）。
    """
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """新增知识 Agent 底座表与约束。"""
    op.create_table(
        "knowledge_conversations",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
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
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
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
    )
    op.create_index(
        op.f("ix_knowledge_conversations_workspace_id"),
        "knowledge_conversations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_conversations_owner_user_id"),
        "knowledge_conversations",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_conversations_project_id"),
        "knowledge_conversations",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_agent_runs",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
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
        sa.Column("user_message_id", _bigint(), nullable=True),
        sa.Column("assistant_message_id", _bigint(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=True),
        sa.Column("active_slot", sa.String(length=8), nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("fallback_summary", sa.Text(), nullable=True),
        sa.Column("answer_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
            "conversation_id",
            "active_slot",
            name="uq_knowledge_run_active_slot",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_conversation_id"),
        "knowledge_agent_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_workspace_id"),
        "knowledge_agent_runs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_owner_user_id"),
        "knowledge_agent_runs",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_project_id"),
        "knowledge_agent_runs",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_user_message_id"),
        "knowledge_agent_runs",
        ["user_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_assistant_message_id"),
        "knowledge_agent_runs",
        ["assistant_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_runs_status"),
        "knowledge_agent_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_run_claim"),
        "knowledge_agent_runs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_messages",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            _bigint(),
            sa.ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column(
            "run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("project_id", _bigint(), nullable=True),
        sa.Column("project_name", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_knowledge_message_client_id",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_messages_conversation_id"),
        "knowledge_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_messages_run_id"),
        "knowledge_messages",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_messages_project_id"),
        "knowledge_messages",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_message_cursor"),
        "knowledge_messages",
        ["conversation_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "knowledge_agent_tool_calls",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("params_summary", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_knowledge_agent_tool_calls_run_id"),
        "knowledge_agent_tool_calls",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_agent_model_invocations",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column(
            "is_fallback",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_knowledge_agent_model_invocations_run_id"),
        "knowledge_agent_model_invocations",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_agent_evidences",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column(
            "entry_id",
            _bigint(),
            sa.ForeignKey("entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            _bigint(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_id",
            _bigint(),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "attachment_id",
            _bigint(),
            sa.ForeignKey("attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entry_title", sa.String(length=255), nullable=True),
        sa.Column("project_name", sa.String(length=64), nullable=True),
        sa.Column("source_title", sa.String(length=255), nullable=True),
        sa.Column("node_path", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column(
            "is_citable",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_run_id"),
        "knowledge_agent_evidences",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_handle"),
        "knowledge_agent_evidences",
        ["handle"],
        unique=True,
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_entry_id"),
        "knowledge_agent_evidences",
        ["entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_project_id"),
        "knowledge_agent_evidences",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_source_id"),
        "knowledge_agent_evidences",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_agent_evidences_attachment_id"),
        "knowledge_agent_evidences",
        ["attachment_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：按依赖顺序删除新增表。"""
    op.drop_table("knowledge_agent_evidences")
    op.drop_table("knowledge_agent_model_invocations")
    op.drop_table("knowledge_agent_tool_calls")
    op.drop_table("knowledge_messages")
    op.drop_table("knowledge_agent_runs")
    op.drop_table("knowledge_conversations")
