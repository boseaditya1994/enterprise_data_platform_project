-- =============================================================================
-- Data Loading: Snowpipe (native tables) + one External Table (Bronze review)
-- =============================================================================
-- DESIGN DECISION, stated explicitly: Silver data is LOADED into native
-- Snowflake tables via Snowpipe, not read in place as External Tables.
--
-- Why not External Tables for everything (the "zero-copy" option):
--   - Silver/Gold are exactly what Power BI and executives query
--     constantly (Phase 1's core use case) -- native tables give
--     clustering keys, materialized views, and result-set caching that
--     External Tables either can't use or use far less effectively.
--   - Silver tables are Delta Lake, not plain Parquet -- an External
--     Table pointed at a Delta table's data files without understanding
--     _delta_log would see every historical file version as live data
--     (Delta doesn't physically delete old Parquet files on MERGE the
--     way a plain overwrite would). Reading Delta correctly needs either
--     Snowflake's native Iceberg/Delta external table support (version-
--     dependent) or a VACUUM'd, MERGE-free export -- added complexity
--     this project doesn't need given Silver's modest data volume.
--   - Net: Snowpipe copying Parquet snapshots (written by a small
--     Databricks export step after each Silver MERGE completes) into
--     native Snowflake tables is simpler, faster to query, and fully
--     supports 06's clustering/materialized-view strategy.
--
-- External Tables ARE still used for the one case they're the right
-- tool for: ad hoc investigation of Bronze/quarantine data that's
-- queried rarely and never needs BI-grade performance (bottom of this file).

CREATE FILE FORMAT IF NOT EXISTS STAGING.FF_PARQUET
    TYPE = PARQUET;

-- One pipe per Silver entity -- mirrors the "one job per source" design
-- principle from Phase 6, applied to the loading layer.
CREATE OR REPLACE TABLE STAGING.SILVER_CUSTOMER LIKE MARTS.DIM_CUSTOMER;

CREATE PIPE IF NOT EXISTS STAGING.PIPE_SILVER_CUSTOMER
    AUTO_INGEST = TRUE
    COMMENT = 'Auto-ingest triggered by Azure Event Grid notification on new files landing under silver/customer/ (Snowflake''s native Event Grid integration, not polling).'
AS
    COPY INTO STAGING.SILVER_CUSTOMER
    FROM @STAGING.STG_SILVER_ADLS/customer/
    FILE_FORMAT = (FORMAT_NAME = STAGING.FF_PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

CREATE OR REPLACE TABLE STAGING.SILVER_LOAN LIKE MARTS.DIM_LOAN;

CREATE PIPE IF NOT EXISTS STAGING.PIPE_SILVER_LOAN
    AUTO_INGEST = TRUE
AS
    COPY INTO STAGING.SILVER_LOAN
    FROM @STAGING.STG_SILVER_ADLS/loan/
    FILE_FORMAT = (FORMAT_NAME = STAGING.FF_PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

CREATE OR REPLACE TABLE STAGING.SILVER_PAYMENT LIKE MARTS.FCT_PAYMENT;

CREATE PIPE IF NOT EXISTS STAGING.PIPE_SILVER_PAYMENT
    AUTO_INGEST = TRUE
AS
    COPY INTO STAGING.SILVER_PAYMENT
    FROM @STAGING.STG_SILVER_ADLS/payment/
    FILE_FORMAT = (FORMAT_NAME = STAGING.FF_PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

CREATE OR REPLACE TABLE STAGING.SILVER_DELINQUENCY LIKE MARTS.FCT_DELINQUENCY;

CREATE PIPE IF NOT EXISTS STAGING.PIPE_SILVER_DELINQUENCY
    AUTO_INGEST = TRUE
AS
    COPY INTO STAGING.SILVER_DELINQUENCY
    FROM @STAGING.STG_SILVER_ADLS/delinquency/
    FILE_FORMAT = (FORMAT_NAME = STAGING.FF_PARQUET)
    MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

-- (silver_contact, silver_promise_to_pay pipes follow the identical
--  pattern -- omitted for brevity, not because the pattern changes.)

-- ---------------------------------------------------------------------------
-- External Table: Bronze quarantine review (the case External Tables ARE
-- the right tool -- rare, ad hoc, no BI performance requirement)
-- ---------------------------------------------------------------------------
CREATE STAGE IF NOT EXISTS QUARANTINE.STG_BRONZE_QUARANTINE_ADLS
    STORAGE_INTEGRATION = SI_ADLS_LOAN_DELINQ
    URL = 'azure://loandelinqcc.blob.core.windows.net/bronze/quarantine/'
    FILE_FORMAT = (TYPE = PARQUET);

CREATE EXTERNAL TABLE IF NOT EXISTS QUARANTINE.EXT_BRONZE_QUARANTINE (
    table_name VARCHAR AS (VALUE:table_name::VARCHAR),
    batch_id VARCHAR AS (VALUE:_batch_id::VARCHAR),
    quarantine_reason VARCHAR AS (VALUE:_schema_drift_classification::VARCHAR),
    raw_record VARIANT AS (VALUE)
)
    LOCATION = @QUARANTINE.STG_BRONZE_QUARANTINE_ADLS
    AUTO_REFRESH = TRUE
    FILE_FORMAT = (TYPE = PARQUET)
    COMMENT = 'Zero-copy read access for a Data Engineer investigating a quarantine spike (Phase 6 Section 6). Queried rarely, never joined into a dashboard -- exactly the workload profile where paying the External Table performance cost is fine.';
