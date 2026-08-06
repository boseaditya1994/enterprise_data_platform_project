-- =============================================================================
-- Storage Integration -- Snowflake <-> ADLS Gen2 federated auth
-- =============================================================================
-- STORAGE INTEGRATION avoids ever storing an Azure account key inside
-- Snowflake -- Snowflake instead gets a service principal / consent grant
-- scoped to exactly the Bronze/Silver containers, auditable and
-- revocable independent of any credential rotation. This is the same
-- "never hardcode a secret in config" principle ADF's linked services
-- (Phase 11) followed via Key Vault references.

CREATE STORAGE INTEGRATION IF NOT EXISTS SI_ADLS_LOAN_DELINQ
    TYPE = EXTERNAL_STAGE
    STORAGE_PROVIDER = 'AZURE'
    ENABLED = TRUE
    AZURE_TENANT_ID = '{tenant_id}'
    STORAGE_ALLOWED_LOCATIONS = (
        'azure://loandelinqcc.blob.core.windows.net/silver/',
        'azure://loandelinqcc.blob.core.windows.net/bronze/'   -- read access for quarantine investigation only, see 02 schema comment
    )
    COMMENT = 'Federated auth to ADLS Gen2. After creation, DESC INTEGRATION SI_ADLS_LOAN_DELINQ
               and grant the returned AZURE_CONSENT_URL''s service principal Storage Blob Data
               Reader on the silver/ container (least privilege -- no write access needed).';

-- External stage referencing the integration -- this is what Snowpipe
-- (04_external_tables_and_snowpipe.sql) and any manual COPY INTO read from.
CREATE STAGE IF NOT EXISTS STAGING.STG_SILVER_ADLS
    STORAGE_INTEGRATION = SI_ADLS_LOAN_DELINQ
    URL = 'azure://loandelinqcc.blob.core.windows.net/silver/'
    FILE_FORMAT = (TYPE = PARQUET)
    COMMENT = 'Points at Databricks'' Silver Delta table Parquet files. Snowflake reads the
               Parquet data files directly -- Delta''s transaction log (_delta_log) is NOT
               interpreted by this stage; see docs/12-snowflake.md Section 1 for why plain
               Parquet + Snowpipe was chosen over Delta-aware external tables for this project.';
