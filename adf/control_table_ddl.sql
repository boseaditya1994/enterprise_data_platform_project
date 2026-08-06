-- =============================================================================
-- ADF Control Table (Azure SQL Database) -- metadata-driven pipeline config
-- =============================================================================
-- This is the ADF-side equivalent of pyspark/bronze/schema_registry.yaml
-- (Phase 6) -- same 13 sources, same design principle (one config-driven
-- pipeline, not thirteen hand-coded ones), different consumer. ADF's
-- Lookup activity reads this table at the start of every run; the
-- registry YAML remains the single source of truth for SCHEMA/drift
-- rules (Databricks' job), this table is the single source of truth for
-- ORCHESTRATION (ADF's job: where to land, how to trigger, retry policy).
-- =============================================================================

CREATE TABLE dbo.pipeline_control (
    source_name              VARCHAR(50)  NOT NULL PRIMARY KEY,
    source_system             VARCHAR(30)  NOT NULL,
    ingestion_pattern          VARCHAR(20)  NOT NULL,   -- 'batch' | 'streaming'
    source_connection_name    VARCHAR(50)  NOT NULL,    -- linked service name
    source_path_pattern        VARCHAR(200) NOT NULL,
    landing_path_pattern       VARCHAR(200) NOT NULL,
    databricks_notebook_path  VARCHAR(200) NOT NULL,
    databricks_job_id          VARCHAR(50),
    schedule_cron              VARCHAR(50)  NOT NULL,   -- informational; actual trigger is tr_daily_schedule
    max_retries                 INT          NOT NULL DEFAULT 3,
    retry_interval_seconds      INT          NOT NULL DEFAULT 30,
    timeout_minutes              INT          NOT NULL DEFAULT 60,
    freshness_sla_minutes         INT,                    -- alert if not landed within this window
    is_active                    BIT          NOT NULL DEFAULT 1,
    depends_on_source            VARCHAR(50)              -- e.g. servicing_daily_status depends on servicing_loans
);

INSERT INTO dbo.pipeline_control
    (source_name, source_system, ingestion_pattern, source_connection_name, source_path_pattern,
     landing_path_pattern, databricks_notebook_path, schedule_cron, max_retries,
     retry_interval_seconds, timeout_minutes, freshness_sla_minutes, depends_on_source)
VALUES
    ('raw_crm', 'CRM', 'batch', 'ls_crm_sftp', '/exports/crm/{date}/*.csv',
     'landing/crm/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * *', 3, 30, 30, 120, NULL),

    ('raw_collectors_daily', 'COLLECTIONS_PLATFORM', 'batch', 'ls_collections_api', '/exports/collectors/{date}/*.csv',
     'landing/collectors/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * *', 3, 30, 20, 120, NULL),

    ('raw_servicing_applications', 'RISK_ENGINE', 'batch', 'ls_risk_engine_sftp', '/exports/applications/{date}/*.csv',
     'landing/servicing_applications/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 5 * * *', 3, 30, 20, 90, NULL),

    ('raw_servicing_loans', 'LOAN_SERVICING', 'batch', 'ls_servicing_sftp', '/exports/loans/{date}/*.csv',
     'landing/servicing_loans/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 5 * * *', 3, 30, 30, 90, NULL),

    ('raw_servicing_daily_status', 'LOAN_SERVICING', 'batch', 'ls_servicing_sftp', '/exports/daily_status/{date}/*.csv',
     'landing/servicing_daily_status/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * *', 3, 30, 45, 120, 'raw_servicing_loans'),

    ('raw_servicing_loan_events', 'LOAN_SERVICING', 'batch', 'ls_servicing_sftp', '/exports/loan_events/{date}/*.csv',
     'landing/servicing_loan_events/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * *', 3, 30, 20, 120, 'raw_servicing_loans'),

    ('raw_servicing_loan_applicant_bridge', 'LOAN_SERVICING', 'batch', 'ls_servicing_sftp', '/exports/bridge/full_snapshot.csv',
     'landing/servicing_loan_applicant_bridge/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * 0', 3, 30, 15, 10080, NULL),

    ('raw_payments', 'PAYMENT_SYSTEM', 'batch', 'ls_payments_sftp', '/exports/payments/{date}/*.csv',
     'landing/payments/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 5 * * *', 5, 60, 60, 90, NULL),

    ('raw_call_center', 'CALL_CENTER', 'streaming', 'ls_event_hubs', 'n/a (Event Hubs)',
     'streaming/call_center/dt={date}/', '/Repos/prod/pyspark/streaming/stream_call_center_collections.py', 'continuous', 5, 60, 0, 15, NULL),

    ('raw_collections', 'COLLECTIONS_PLATFORM', 'streaming', 'ls_event_hubs', 'n/a (Event Hubs)',
     'streaming/collections/dt={date}/', '/Repos/prod/pyspark/streaming/stream_call_center_collections.py', 'continuous', 5, 60, 0, 15, NULL),

    ('raw_collections_ptp', 'COLLECTIONS_PLATFORM', 'streaming', 'ls_event_hubs', 'n/a (Event Hubs)',
     'streaming/collections_ptp/dt={date}/', '/Repos/prod/pyspark/streaming/stream_call_center_collections.py', 'continuous', 5, 60, 0, 15, NULL),

    ('raw_bureau', 'CREDIT_BUREAU', 'batch', 'ls_bureau_sftp', '/exports/bureau/{date}/*.csv',
     'landing/bureau/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 7 * * *', 2, 120, 30,
     50400, NULL),  -- 35-day freshness SLA (Phase 6 registry) -- bureau is expected to be occasionally absent

    ('raw_risk_scores', 'RISK_ENGINE', 'batch', 'ls_risk_engine_sftp', '/exports/risk_scores/{date}/*.csv',
     'landing/risk_scores/dt={date}/', '/Repos/prod/pyspark/bronze/ingest_bronze.py', '0 6 * * *', 3, 30, 20, 120, NULL);

-- The pipeline_control table -- not the pipeline JSON -- is what a new
-- 8th source system requires touching (Phase 2's "adding a source is a
-- config change" claim, now concrete for orchestration too, matching
-- Phase 6's identical claim for schema/ingestion).
