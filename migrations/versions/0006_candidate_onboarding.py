"""Optional candidate identity and professional links for saved onboarding.

Revision ID: 0006_candidate_onboarding
Revises: 0005_congestion_prices
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_candidate_onboarding"
down_revision = "0005_congestion_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles", sa.Column("display_name", sa.String(120), nullable=False, server_default="")
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("professional_links", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "professional_links")
    op.drop_column("candidate_profiles", "display_name")
