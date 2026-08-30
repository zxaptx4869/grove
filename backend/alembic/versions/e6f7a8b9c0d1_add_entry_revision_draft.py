"""add knowledge agent entry revision draft and execution

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-30 14:00:00.000000

为知识 Agent 增加单 Entry 修订操作：
- knowledge_agent_runs 增加 target_entry_id（entry_revision 操作 Run 锚定目标 Entry，
  既有 answer/draft_candidate 数据保持 NULL，不修改既有行）；
- 新增 knowledge_entry_revision_drafts：operation Run 一对一、确认幂等键、
  不可变基线快照/指纹、允许与采用 Evidence 句柄、候选字段、执行关联；
- 新增 knowledge_entry_revision_executions：确认幂等键、before/after 快照与指纹、
  前后版本、本操作新增 Evidence id、applied/undoing/undone 状态与撤销幂等键。

两个新表存在 circular FK（draft.execution_id ↔ execution.draft_id），
先建 drafts（execution_id 仅普通列），再建 executions，最后补 drafts 的 FK，
保证 MySQL 8 与 SQLite 均可升级。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bigint() -> sa.BigInteger:
    """返回与 ORM 一致的双库兼容主键/外键类型。"""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """扩展 Run 表并新增修订草稿与执行审计表。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("target_entry_id", _bigint(), nullable=True))
        batch_op.create_foreign_key(
            "fk_knowledge_agent_runs_target_entry_id",
            "entries",
            ["target_entry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_knowledge_agent_runs_target_entry_id"),
            ["target_entry_id"],
            unique=False,
        )

    op.create_table(
        "knowledge_entry_revision_drafts",
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
        sa.Column(
            "conversation_id",
            _bigint(),
            sa.ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_run_id",
            _bigint(),
            sa.ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_entry_id",
            _bigint(),
            sa.ForeignKey("entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_project_id",
            _bigint(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_project_name", sa.String(length=64), nullable=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("base_entry_json", sa.Text(), nullable=False),
        sa.Column("base_entry_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("base_version_id", _bigint(), nullable=True),
        sa.Column("base_version_number", sa.Integer(), nullable=True),
        sa.Column("allowed_evidence_handles_json", sa.Text(), nullable=True),
        sa.Column("selected_evidence_handles_json", sa.Text(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("main_type", sa.String(length=16), nullable=True),
        sa.Column("info_nature", sa.String(length=16), nullable=True),
        sa.Column("applicable_condition", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("generation_meta_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        # circular FK：先作为普通列建表，执行表建好后补外键
        sa.Column("execution_id", _bigint(), nullable=True),
        sa.Column("client_operation_id", sa.String(length=64), nullable=True),
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
            "operation_run_id",
            name="uq_knowledge_entry_revision_draft_operation_run",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_entry_revision_draft_operation_key",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_workspace_id"),
        "knowledge_entry_revision_drafts",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_owner_user_id"),
        "knowledge_entry_revision_drafts",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_conversation_id"),
        "knowledge_entry_revision_drafts",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_operation_run_id"),
        "knowledge_entry_revision_drafts",
        ["operation_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_source_run_id"),
        "knowledge_entry_revision_drafts",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_target_entry_id"),
        "knowledge_entry_revision_drafts",
        ["target_entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_target_project_id"),
        "knowledge_entry_revision_drafts",
        ["target_project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_draft_status"),
        "knowledge_entry_revision_drafts",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "knowledge_entry_revision_executions",
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
        sa.Column(
            "conversation_id",
            _bigint(),
            sa.ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            _bigint(),
            sa.ForeignKey("knowledge_entry_revision_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_id",
            _bigint(),
            sa.ForeignKey("entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_operation_id", sa.String(length=64), nullable=False),
        sa.Column("before_entry_json", sa.Text(), nullable=False),
        sa.Column("after_entry_json", sa.Text(), nullable=False),
        sa.Column("before_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("after_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("before_version_id", _bigint(), nullable=True),
        sa.Column("before_version_number", sa.Integer(), nullable=True),
        sa.Column("after_version_id", _bigint(), nullable=True),
        sa.Column("after_version_number", sa.Integer(), nullable=True),
        sa.Column("added_evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("undo_client_operation_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
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
            "draft_id",
            name="uq_knowledge_entry_revision_execution_draft",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_entry_revision_execution_operation_key",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "undo_client_operation_id",
            name="uq_knowledge_entry_revision_execution_undo_key",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_executions_workspace_id"),
        "knowledge_entry_revision_executions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_executions_owner_user_id"),
        "knowledge_entry_revision_executions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_executions_conversation_id"),
        "knowledge_entry_revision_executions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_executions_draft_id"),
        "knowledge_entry_revision_executions",
        ["draft_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_executions_entry_id"),
        "knowledge_entry_revision_executions",
        ["entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entry_revision_execution_status"),
        "knowledge_entry_revision_executions",
        ["status", "created_at"],
        unique=False,
    )

    # 补 drafts.execution_id 外键（MySQL 需要先有被执行表）
    with op.batch_alter_table("knowledge_entry_revision_drafts") as batch_op:
        batch_op.create_foreign_key(
            "fk_knowledge_entry_revision_drafts_execution_id",
            "knowledge_entry_revision_executions",
            ["execution_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_knowledge_entry_revision_drafts_execution_id"),
        "knowledge_entry_revision_drafts",
        ["execution_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：先删执行表，再删草稿表，最后移除 Run 表扩展字段。"""
    with op.batch_alter_table("knowledge_entry_revision_drafts") as batch_op:
        batch_op.drop_index(
            op.f("ix_knowledge_entry_revision_drafts_execution_id"),
        )
        batch_op.drop_constraint(
            "fk_knowledge_entry_revision_drafts_execution_id",
            type_="foreignkey",
        )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_execution_status"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_executions_entry_id"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_executions_draft_id"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_executions_conversation_id"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_executions_owner_user_id"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_executions_workspace_id"),
        table_name="knowledge_entry_revision_executions",
    )
    op.drop_table("knowledge_entry_revision_executions")
    op.drop_index(
        op.f("ix_knowledge_entry_revision_draft_status"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_target_project_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_target_entry_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_source_run_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_operation_run_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_conversation_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_owner_user_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_entry_revision_drafts_workspace_id"),
        table_name="knowledge_entry_revision_drafts",
    )
    op.drop_table("knowledge_entry_revision_drafts")
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_index(
            op.f("ix_knowledge_agent_runs_target_entry_id"),
        )
        batch_op.drop_constraint(
            "fk_knowledge_agent_runs_target_entry_id",
            type_="foreignkey",
        )
        batch_op.drop_column("target_entry_id")
