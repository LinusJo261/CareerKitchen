-- Run after owner migrations, in the intended database, with psql --single-transaction
-- and ON_ERROR_STOP=1. This exact allowlist never grants auth/storage/compliance schema access.
-- career_kitchen_backend is the trusted API/worker tier; tenant authorization stays in FastAPI.
DO $role$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_kitchen_backend') THEN
        CREATE ROLE career_kitchen_backend NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'career_kitchen_backend'
        AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Existing backend group has unsafe attributes; review before applying';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_auth_members
        WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'career_kitchen_backend')
    ) THEN
        RAISE EXCEPTION 'Backend group must not inherit unrelated roles';
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO career_kitchen_backend', current_database());
END
$role$;

REVOKE ALL ON SCHEMA public FROM career_kitchen_backend;
GRANT USAGE ON SCHEMA public TO career_kitchen_backend;
REVOKE ALL ON TABLE public.alembic_version FROM PUBLIC;
GRANT SELECT ON TABLE public.alembic_version TO career_kitchen_backend;

DO $policies$
DECLARE
    table_name text;
    browser_role text;
BEGIN
    IF has_schema_privilege('career_kitchen_backend', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'Backend group inherits schema CREATE; remove the unrelated grant before applying';
    END IF;
    IF has_database_privilege('career_kitchen_backend', current_database(), 'CREATE') THEN
        RAISE EXCEPTION 'Backend group inherits database CREATE; remove the unrelated grant before applying';
    END IF;
    FOR browser_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
        EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I', browser_role);
        IF pg_has_role(browser_role, 'career_kitchen_backend', 'MEMBER') THEN
            RAISE EXCEPTION 'Browser role must not inherit backend membership';
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY[
        'abuse_reports',
        'audit_events',
        'candidate_blocks',
        'candidate_profiles',
        'candidate_skills',
        'candidate_term_consents',
        'congestion_prices',
        'decision_cards',
        'employment_offers',
        'evidence_access_grants',
        'evidence_claims',
        'exclusive_reservations',
        'exposure_events',
        'idempotency_records',
        'inbox_consumptions',
        'interview_events',
        'interview_proposals',
        'market_prices',
        'matching_learning_state',
        'matching_models',
        'matching_observations',
        'match_attachments',
        'match_messages',
        'mutual_matches',
        'notification_outbox',
        'notification_preferences',
        'org_members',
        'organization_invitations',
        'organizations',
        'outbox_events',
        'pact_policy_authorizations',
        'pact_policy_versions',
        'pair_cycles',
        'policy_clarification_requests',
        'privacy_requests',
        'process_stage_events',
        'rate_buckets',
        'readiness_proofs',
        'revoked_sessions',
        'shadow_runs',
        'skills_taxonomy',
        'users',
        'vacancies',
        'vacancy_acl',
        'vacancy_requirements',
        'verified_employment_starts',
        'waiting_items'
    ] LOOP
        IF to_regclass(format('public.%I', table_name)) IS NULL THEN
            RAISE EXCEPTION 'Required backend table % is absent; migrate first', table_name;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = table_name
              AND pg_has_role('career_kitchen_backend', c.relowner, 'MEMBER')
        ) THEN
            RAISE EXCEPTION 'Backend group inherits table ownership for %', table_name;
        END IF;
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM career_kitchen_backend', table_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', table_name);
        IF table_name IN ('audit_events', 'exposure_events', 'process_stage_events', 'matching_observations') THEN
            EXECUTE format('GRANT SELECT, INSERT ON TABLE public.%I TO career_kitchen_backend', table_name);
        ELSE
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO career_kitchen_backend', table_name);
        END IF;
        FOR browser_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', table_name, browser_role);
        END LOOP;
        EXECUTE format('DROP POLICY IF EXISTS career_kitchen_backend_access ON public.%I', table_name);
        EXECUTE format(
            'CREATE POLICY career_kitchen_backend_access ON public.%I FOR ALL TO career_kitchen_backend USING (true) WITH CHECK (true)',
            table_name
        );
    END LOOP;
END
$policies$;

-- No default privileges are changed: a new table requires an explicit reviewed allowlist update.
-- Provision a separate LOGIN role using your managed secret flow, then:
-- GRANT career_kitchen_backend TO career_kitchen_runtime;
-- Do not grant the runtime login membership in the table owner or any BYPASSRLS role.
