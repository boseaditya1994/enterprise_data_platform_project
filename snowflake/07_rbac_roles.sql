-- =============================================================================
-- Role-Based Access Control -- implements Phase 1 Section 4 personas and
-- Section 7 NFR Security ("a front-line collector should not see the full
-- portfolio; an executive should not need PII drill-down")
-- =============================================================================
-- Role hierarchy (functional roles inherit from more restricted roles
-- upward, per Snowflake convention -- SYSADMIN grants warehouse/db
-- ownership, functional roles below are what's actually assigned to people):
--
--   ACCOUNTADMIN
--        |
--   ROLE_DATA_PLATFORM_ADMIN          (Data Platform Engineering, Phase 1 persona)
--        |
--   ROLE_ANALYTICS_ENGINEER            (builds/maintains dbt models)
--        |
--   ROLE_COMPLIANCE_AUDITOR   ROLE_COLLECTIONS_MANAGER   ROLE_EXECUTIVE
--        |                          |
--                            ROLE_COLLECTOR

USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS ROLE_DATA_PLATFORM_ADMIN
    COMMENT = 'Phase 1 persona: Data Platform Engineering. Full read/write on STAGING/MARTS/KPI/QUARANTINE/AUDIT. Owns warehouses, pipes, tasks.';

CREATE ROLE IF NOT EXISTS ROLE_ANALYTICS_ENGINEER
    COMMENT = 'Builds/maintains dbt models (Phase 9). Read/write MARTS+KPI, read-only STAGING, no QUARANTINE/AUDIT write access.';

CREATE ROLE IF NOT EXISTS ROLE_COMPLIANCE_AUDITOR
    COMMENT = 'Phase 1 persona: Compliance/Legal. Read-only, ALL schemas including QUARANTINE and AUDIT (needs full traceability for FDCPA/UDAAP review), but every PII column still masked (09_masking_policies.sql) -- audit access does not mean unmasked access.';

CREATE ROLE IF NOT EXISTS ROLE_COLLECTIONS_MANAGER
    COMMENT = 'Phase 1 persona: Collections Operations Manager / Strategy Analyst. Read KPI+MARTS, row-access-policy scoped to their team (08_row_access_policies.sql), PII visible (need name/phone for case escalation).';

CREATE ROLE IF NOT EXISTS ROLE_COLLECTOR
    COMMENT = 'Phase 1 persona: Individual Collector. Read KPI+MARTS, row-access-policy scoped to ONLY accounts assigned to them, PII visible (need contact info to do the job), no cross-collector visibility.';

CREATE ROLE IF NOT EXISTS ROLE_EXECUTIVE
    COMMENT = 'Phase 1 persona: VP Collections & Recovery, Credit Risk Officer. Read KPI schema ONLY (aggregated views/materialized views), no MARTS row-level access, PII masked (09_masking_policies.sql) -- executives need portfolio trend, never an individual customer''s phone number.';

-- Hierarchy grants
GRANT ROLE ROLE_ANALYTICS_ENGINEER TO ROLE ROLE_DATA_PLATFORM_ADMIN;
GRANT ROLE ROLE_COLLECTIONS_MANAGER TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT ROLE ROLE_COLLECTOR TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT ROLE ROLE_COMPLIANCE_AUDITOR TO ROLE ROLE_DATA_PLATFORM_ADMIN;
GRANT ROLE ROLE_EXECUTIVE TO ROLE ROLE_DATA_PLATFORM_ADMIN;

-- ---------------------------------------------------------------------------
-- Schema/object grants
-- ---------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;  -- object ownership grants require elevated context in most setups

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_DATA_PLATFORM_ADMIN;
GRANT ALL ON ALL SCHEMAS IN DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_DATA_PLATFORM_ADMIN;
GRANT ALL ON FUTURE SCHEMAS IN DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_DATA_PLATFORM_ADMIN;

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT USAGE ON SCHEMA STAGING TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT SELECT ON ALL TABLES IN SCHEMA STAGING TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT ALL ON SCHEMA MARTS TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT ALL ON SCHEMA KPI TO ROLE ROLE_ANALYTICS_ENGINEER;
GRANT USAGE ON WAREHOUSE WH_TRANSFORM TO ROLE ROLE_ANALYTICS_ENGINEER;

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COMPLIANCE_AUDITOR;
GRANT USAGE ON ALL SCHEMAS IN DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COMPLIANCE_AUDITOR;
GRANT SELECT ON ALL TABLES IN DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COMPLIANCE_AUDITOR;
GRANT SELECT ON ALL VIEWS IN DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COMPLIANCE_AUDITOR;
GRANT USAGE ON WAREHOUSE WH_ADHOC_ANALYST TO ROLE ROLE_COMPLIANCE_AUDITOR;

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT USAGE ON SCHEMA MARTS TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT USAGE ON SCHEMA KPI TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT SELECT ON ALL TABLES IN SCHEMA MARTS TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT SELECT ON ALL VIEWS IN SCHEMA KPI TO ROLE ROLE_COLLECTIONS_MANAGER;
GRANT USAGE ON WAREHOUSE WH_BI_SERVING TO ROLE ROLE_COLLECTIONS_MANAGER;

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_COLLECTOR;
GRANT USAGE ON SCHEMA MARTS TO ROLE ROLE_COLLECTOR;
GRANT USAGE ON SCHEMA KPI TO ROLE ROLE_COLLECTOR;
GRANT SELECT ON ALL TABLES IN SCHEMA MARTS TO ROLE ROLE_COLLECTOR;
GRANT SELECT ON ALL VIEWS IN SCHEMA KPI TO ROLE ROLE_COLLECTOR;
GRANT USAGE ON WAREHOUSE WH_BI_SERVING TO ROLE ROLE_COLLECTOR;

GRANT USAGE ON DATABASE LOAN_DELINQUENCY_CC TO ROLE ROLE_EXECUTIVE;
GRANT USAGE ON SCHEMA KPI TO ROLE ROLE_EXECUTIVE;
GRANT SELECT ON ALL VIEWS IN SCHEMA KPI TO ROLE ROLE_EXECUTIVE;
GRANT SELECT ON ALL MATERIALIZED VIEWS IN SCHEMA KPI TO ROLE ROLE_EXECUTIVE;
-- Deliberately NO grant on MARTS for ROLE_EXECUTIVE -- executives get the
-- governed KPI layer only, never raw fact/dim row access. This is the
-- single most direct implementation of Phase 1's stated NFR: "an
-- executive should not need PII drill-down."
GRANT USAGE ON WAREHOUSE WH_BI_SERVING TO ROLE ROLE_EXECUTIVE;
