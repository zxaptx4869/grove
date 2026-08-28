"""add knowledge agent context versions and working set

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-28 18:40:00.000000

新增上下文版本与工作集项表，并扩展 Run 的上下文决策契约字段。
关键约束：
- knowledge_context_versions 的 (conversation_id, active_slot) 唯一约束保证
  同一对话最多一个活动工作集版本；终态（superseded/closed）置 NULL，
  SQLite 与 MySQL 的唯一索引都允许多个 NULL；
- knowledge_working_set_items 的 (context_version_id, entry_id) 唯一约束
  保证同一版本内 Entry 线索不重复（entry_id 可空，允许多个空主题版本）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bigint() -> sa.BigInteger:
    """返回与 ORM 一致的双库兼容主键/外键类型。

    MySQL 8 使用 BIGINT；SQLite 必须用 INTEGER 才能获得 rowid 自增语义
    （BIGINT PRIMARY KEY 不会自动生成 id）。
    """
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """新增上下文版本/工作集表并扩展 Run 上下文字段。"""
    op.create_table(
        "knowledge_context_versions",
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
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "parent_version_id",
            _bigint(),
            sa.ForeignKey("knowledge_context_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column(
            "project_id",
            _bigint(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_name", sa.String(length=64), nullable=True),
        sa.Column("topic_label", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("close_reason", sa.String(length=16), nullable=True),
        sa.Column("active_slot", sa.String(length=8), nullable=True),
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
            name="uq_knowledge_context_active_slot",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_conversation_id"),
        "knowledge_context_versions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_workspace_id"),
        "knowledge_context_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_owner_user_id"),
        "knowledge_context_versions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_parent_version_id"),
        "knowledge_context_versions",
        ["parent_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_source_run_id"),
        "knowledge_context_versions",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_versions_project_id"),
        "knowledge_context_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_context_claim"),
        "knowledge_context_versions",
        ["conversation_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_working_set_items",
        sa.Column("id", _bigint(), primary_key=True, autoincrement=True),
        sa.Column(
            "context_version_id",
            _bigint(),
            sa.ForeignKey("knowledge_context_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            _bigint(),
            sa.ForeignKey("entries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("entry_title", sa.String(length=255), nullable=True),
        sa.Column("project_name", sa.String(length=64), nullable=True),
        sa.Column("node_path", sa.Text(), nullable=True),
        sa.Column(
            "source_run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("include_reason", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "last_used_at",
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
        sa.UniqueConstraint(
            "context_version_id",
            "entry_id",
            name="uq_knowledge_working_set_entry",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_working_set_items_context_version_id"),
        "knowledge_working_set_items",
        ["context_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_working_set_items_entry_id"),
        "knowledge_working_set_items",
        ["entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_working_set_items_source_run_id"),
        "knowledge_working_set_items",
        ["source_run_id"],
        unique=False,
    )

    # Run 上下文决策契约字段（可空，既有对话保持无上下文决策；SQLite 批量重建）
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("request_context_mode", sa.String(length=8), nullable=True)
        )
        batch_op.add_column(
            sa.Column("context_decision", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(sa.Column("standalone_query", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("topic_label", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("history_message_ids_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "input_context_version_id",
                _bigint(),
                sa.ForeignKey(
                    "knowledge_context_versions.id",
                    ondelete="SET NULL",
                    name="fk_knowledge_agent_runs_input_context_version",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "output_context_version_id",
                _bigint(),
                sa.ForeignKey(
                    "knowledge_context_versions.id",
                    ondelete="SET NULL",
                    name="fk_knowledge_agent_runs_output_context_version",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("context_meta_json", sa.Text(), nullable=True)
        )
        batch_op.create_index(
            "ix_knowledge_agent_runs_input_context_version_id",
            ["input_context_version_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_knowledge_agent_runs_output_context_version_id",
            ["output_context_version_id"],
            unique=False,
        )

    # 模型调用用途列加宽，容纳 context_decision 阶段（SQLite 需批量重建）
    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.alter_column(
            "purpose",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    """回滚：先删 Run 字段，再删工作集与上下文版本表。"""
    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.alter_column(
            "purpose",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
    op.drop_index(
        op.f("ix_knowledge_agent_runs_output_context_version_id"),
        table_name="knowledge_agent_runs",
    )
    op.drop_index(
        op.f("ix_knowledge_agent_runs_input_context_version_id"),
        table_name="knowledge_agent_runs",
    )
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("context_meta_json")
        batch_op.drop_column("output_context_version_id")
        batch_op.drop_column("input_context_version_id")
        batch_op.drop_column("history_message_ids_json")
        batch_op.drop_column("topic_label")
        batch_op.drop_column("standalone_query")
        batch_op.drop_column("context_decision")
        batch_op.drop_column("request_context_mode")
    op.drop_table("knowledge_working_set_items")
    op.drop_table("knowledge_context_versions")
