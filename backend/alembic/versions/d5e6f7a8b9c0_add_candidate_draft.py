"""add knowledge candidate draft model

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-30 10:00:00.000000

为知识 Agent 增加受控候选草稿操作：
- knowledge_agent_runs 增加 run_kind（answer/draft_candidate，既有数据默认 answer）
  与可选 source_run_id（操作 Run 自引用锚定来源回答 Run）；
- 新增 knowledge_candidate_drafts：operation Run 一对一、confirmed Candidate 唯一、
  (conversation_id, client_operation_id) 幂等键，并固化目标项目快照与生成可观测信息。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bigint() -> sa.BigInteger:
    """返回与 ORM 一致的双库兼容主键/外键类型。"""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    """扩展 Run 表并新增候选草稿表。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "run_kind",
                sa.String(length=16),
                server_default="answer",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("source_run_id", _bigint(), nullable=True))
        batch_op.create_foreign_key(
            "fk_knowledge_agent_runs_source_run_id",
            "knowledge_agent_runs",
            ["source_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_knowledge_agent_runs_source_run_id"),
            ["source_run_id"],
            unique=False,
        )

    op.create_table(
        "knowledge_candidate_drafts",
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
            "target_project_id",
            _bigint(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_project_name", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("main_type", sa.String(length=16), nullable=True),
        sa.Column("info_nature", sa.String(length=16), nullable=True),
        sa.Column("evidence_handles_json", sa.Text(), nullable=True),
        sa.Column("generation_meta_json", sa.Text(), nullable=True),
        sa.Column("client_operation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "confirmed_candidate_id",
            _bigint(),
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
            name="uq_knowledge_candidate_draft_operation_run",
        ),
        sa.UniqueConstraint(
            "confirmed_candidate_id",
            name="uq_knowledge_candidate_draft_candidate",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_candidate_draft_operation_key",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_workspace_id"),
        "knowledge_candidate_drafts",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_owner_user_id"),
        "knowledge_candidate_drafts",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_conversation_id"),
        "knowledge_candidate_drafts",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_operation_run_id"),
        "knowledge_candidate_drafts",
        ["operation_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_source_run_id"),
        "knowledge_candidate_drafts",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_target_project_id"),
        "knowledge_candidate_drafts",
        ["target_project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_drafts_confirmed_candidate_id"),
        "knowledge_candidate_drafts",
        ["confirmed_candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_candidate_draft_status"),
        "knowledge_candidate_drafts",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：先删候选草稿表，再移除 Run 表扩展字段。"""
    op.drop_index(
        op.f("ix_knowledge_candidate_draft_status"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_confirmed_candidate_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_target_project_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_source_run_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_operation_run_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_conversation_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_owner_user_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_index(
        op.f("ix_knowledge_candidate_drafts_workspace_id"),
        table_name="knowledge_candidate_drafts",
    )
    op.drop_table("knowledge_candidate_drafts")
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_index(
            op.f("ix_knowledge_agent_runs_source_run_id"),
        )
        batch_op.drop_constraint(
            "fk_knowledge_agent_runs_source_run_id",
            type_="foreignkey",
        )
        batch_op.drop_column("source_run_id")
        batch_op.drop_column("run_kind")
