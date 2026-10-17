"""Deny direct browser DB access and enforce append-only event history.

Revision ID: 0002_security_isolation
Revises: f8f85e52a406
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0002_security_isolation"
down_revision = "f8f85e52a406"
branch_labels = None
depends_on = None

TABLES = (
    "market_prices",
    "outbox_events",
    "rate_buckets",
    "skills_taxonomy",
    "users",
    "abuse_reports",
    "candidate_profiles",
    "idempotency_records",
    "inbox_consumptions",
    "notification_outbox",
    "notification_preferences",
    "organizations",
    "privacy_requests",
    "revoked_sessions",
    "shadow_runs",
    "audit_events",
    "candidate_blocks",
    "candidate_skills",
    "evidence_claims",
    "org_members",
    "organization_invitations",
    "pact_policy_versions",
    "vacancies",
    "candidate_term_consents",
    "evidence_access_grants",
    "exclusive_reservations",
    "pact_policy_authorizations",
    "pair_cycles",
    "vacancy_acl",
    "vacancy_requirements",
    "decision_cards",
    "employment_offers",
    "mutual_matches",
    "policy_clarification_requests",
    "process_stage_events",
    "readiness_proofs",
    "verified_employment_starts",
    "waiting_items",
    "exposure_events",
    "interview_proposals",
    "match_messages",
    "interview_events",
)
APPEND_ONLY = ("audit_events", "exposure_events", "process_stage_events")


def upgrade() -> None:
    connection = op.get_bind()
    browser_roles: Sequence[str] = (
        connection.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')"))
        .scalars()
        .all()
    )
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE "{table}" FROM PUBLIC')
        for role in browser_roles:
            op.execute(f'REVOKE ALL ON TABLE "{table}" FROM "{role}"')
    op.execute("""
        CREATE FUNCTION career_kitchen_reject_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Append-only event cannot be changed'
                USING ERRCODE = '55000';
        END;
        $$
    """)
    for table in APPEND_ONLY:
        op.execute(
            f'CREATE TRIGGER reject_event_mutation BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION career_kitchen_reject_event_mutation()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f'DROP TRIGGER IF EXISTS reject_event_mutation ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS career_kitchen_reject_event_mutation()")
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    # Privileges remain revoked intentionally; rollback never exposes private data.
