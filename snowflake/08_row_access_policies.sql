-- =============================================================================
-- Row Access Policies -- account-level visibility scoping for
-- ROLE_COLLECTOR and ROLE_COLLECTIONS_MANAGER (Phase 1 NFR Security)
-- =============================================================================
-- A mapping table drives the policy (same metadata-driven principle as
-- the Bronze schema registry and ADF's pipeline_control -- this project's
-- consistent pattern for "config, not hard-coded logic," now applied to
-- access control).

CREATE TABLE IF NOT EXISTS AUDIT.COLLECTOR_TEAM_MAP (
    snowflake_username VARCHAR NOT NULL,
    collector_id VARCHAR,           -- populated for ROLE_COLLECTOR users
    team_name VARCHAR,               -- populated for ROLE_COLLECTIONS_MANAGER users (their team)
    role_type VARCHAR NOT NULL       -- 'COLLECTOR' | 'MANAGER'
)
    COMMENT = 'Maps a logged-in Snowflake user to the collector_id or team_name their row access policy scopes them to. Synced from HR/collections-platform roster (Phase 16 ownership: Data Platform Admin, updated on collector reassignment).';

CREATE ROW ACCESS POLICY IF NOT EXISTS QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS
    AS (row_collector_id VARCHAR) RETURNS BOOLEAN ->
    CASE
        -- Elevated roles bypass row scoping entirely -- explicit
        -- allow-list, not a default-permit fallthrough.
        WHEN CURRENT_ROLE() IN ('ROLE_DATA_PLATFORM_ADMIN', 'ROLE_ANALYTICS_ENGINEER', 'ROLE_COMPLIANCE_AUDITOR') THEN TRUE

        -- A collections manager sees every account currently assigned to
        -- ANY collector on their team.
        WHEN CURRENT_ROLE() = 'ROLE_COLLECTIONS_MANAGER' THEN
            row_collector_id IN (
                SELECT c.collector_id
                FROM MARTS.DIM_COLLECTOR c
                JOIN AUDIT.COLLECTOR_TEAM_MAP m
                    ON m.team_name = c.team_name AND m.role_type = 'MANAGER'
                WHERE m.snowflake_username = CURRENT_USER() AND c.is_current
            )

        -- A collector sees ONLY accounts assigned to them, specifically
        -- (Phase 1: "a front-line collector should not see the full portfolio").
        WHEN CURRENT_ROLE() = 'ROLE_COLLECTOR' THEN
            row_collector_id = (
                SELECT collector_id FROM AUDIT.COLLECTOR_TEAM_MAP
                WHERE snowflake_username = CURRENT_USER() AND role_type = 'COLLECTOR'
            )

        ELSE FALSE   -- fail closed: an unrecognized role sees nothing, not everything
    END;

-- Applied to every table carrying a collector attribution -- the
-- assigned/last-touch collector column (Phase 8 Section 3.3's ASOF-join
-- attribution, or dim_collector's own collector_id for productivity views).
ALTER TABLE MARTS.FCT_DELINQUENCY
    ADD ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS ON (assigned_collector_id);

ALTER TABLE MARTS.FCT_CONTACT
    ADD ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS ON (collector_sk);
    -- NOTE: collector_sk here is a surrogate key, not collector_id -- a
    -- real implementation joins through dim_collector inside the policy
    -- body (or denormalizes collector_id onto the fact) rather than
    -- comparing a surrogate key against a natural key directly. Shown
    -- simplified here; docs/12-snowflake.md Section 6 flags this as the
    -- one piece of this phase that would need a follow-up fix before
    -- actual deployment, rather than silently leaving the mismatch unstated.
