-- =============================================================================
-- Database & Schema Structure
-- =============================================================================
-- One database, schemas mirroring the medallion layers already established
-- (Phases 6-9) -- consistent naming end to end so "which layer is this
-- table in" never requires context-switching between docs and warehouse.

CREATE DATABASE IF NOT EXISTS LOAN_DELINQUENCY_CC
    COMMENT = 'Loan Delinquency & Collections Command Center -- see docs/ in the project repo for full design.';

USE DATABASE LOAN_DELINQUENCY_CC;

-- STAGING: native Snowflake landing zone for Silver data arriving via
-- Snowpipe (04_external_tables_and_snowpipe.sql). NOT the same as
-- Databricks' Bronze -- this is Silver-in-Snowflake, the input dbt's
-- staging models read from once data physically lands here.
CREATE SCHEMA IF NOT EXISTS STAGING
    COMMENT = 'Snowpipe landing zone -- native copies of Silver Delta tables, refreshed continuously. dbt sources point here.';

-- MARTS: dbt's build target for the star schema (Phase 3/9) -- dims and facts.
CREATE SCHEMA IF NOT EXISTS MARTS
    COMMENT = 'Gold star schema -- dbt marts.core / marts.facts output lands here in production.';

-- KPI: the 10 governed KPI views (Phase 8/9) -- kept separate from MARTS
-- so a BI developer browsing the warehouse immediately sees "facts/dims"
-- vs. "the governed metric layer" as two distinct, purpose-labeled things.
CREATE SCHEMA IF NOT EXISTS KPI
    COMMENT = 'Governed KPI views + materialized views (06_clustering_and_materialized_views.sql).';

-- QUARANTINE: mirrors Phase 6's Bronze-side quarantine, for anything that
-- fails a Snowflake-side DQ check post-load (belt-and-suspenders with
-- Databricks' own quarantine -- see docs/12-snowflake.md Section 5).
CREATE SCHEMA IF NOT EXISTS QUARANTINE
    COMMENT = 'Rows failing Snowflake-side DQ checks (pyspark/dq/dq_framework.py logic re-applied here as a second gate).';

-- AUDIT: pipeline run logs, DQ check results, access-policy change history.
CREATE SCHEMA IF NOT EXISTS AUDIT
    COMMENT = 'Operational metadata -- pipeline_run_log, dq.check_results equivalent, RBAC change tracking.';
