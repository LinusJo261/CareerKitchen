"""Explicit matching-learning consent and versioned model registry.

Revision ID: 0006_matching_learning
Revises: 0005_congestion_prices
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_matching_learning"
down_revision = "0005_congestion_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("candidate_profiles", "organizations"):
        op.add_column(
            table,
            sa.Column("matching_learning_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(
            table,
            sa.Column("matching_learning_consent_version", sa.Integer(), nullable=False, server_default="1"),
        )
    op.create_table(
        "matching_learning_state",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, unique=True),
    )
    op.create_table(
        "matching_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False, unique=True),
        sa.Column("artifact", sa.JSON(), nullable=False),
        sa.Column("evaluation", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("activated_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE','RETIRED')"),
    )
    op.create_index(
        "uq_matching_model_active",
        "matching_models",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "matching_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "pair_cycle_id", sa.String(36), sa.ForeignKey("pair_cycles.id"), nullable=False, unique=True
        ),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("candidate_profiles.id"), nullable=False),
        sa.Column("vacancy_id", sa.String(36), sa.ForeignKey("vacancies.id"), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
    )
    op.create_index("ix_matching_observations_candidate_id", "matching_observations", ["candidate_id"])
    op.create_index("ix_matching_observations_vacancy_id", "matching_observations", ["vacancy_id"])
    op.create_index("ix_matching_observations_created_at_id", "matching_observations", ["created_at", "id"])
    for table in ("matching_models", "matching_observations", "matching_learning_state"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute("""CREATE TRIGGER matching_observations_immutable
        BEFORE UPDATE OR DELETE ON matching_observations
        FOR EACH ROW EXECUTE FUNCTION career_kitchen_reject_event_mutation()""")
    role: str
    for role in (
        op.get_bind()
        .execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')"))
        .scalars()
    ):
        for table in ("matching_models", "matching_observations", "matching_learning_state"):
            op.execute(f'REVOKE ALL ON TABLE {table} FROM "{role}"')


def downgrade() -> None:
    op.drop_table("matching_observations")
    op.drop_index("uq_matching_model_active", table_name="matching_models")
    op.drop_table("matching_models")
    op.drop_table("matching_learning_state")
    for table in ("organizations", "candidate_profiles"):
        op.drop_column(table, "matching_learning_consent_version")
        op.drop_column(table, "matching_learning_opt_in")
