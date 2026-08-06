-- =============================================================================
-- Warehouse Strategy — workload isolation (Phase 1 NFR Cost, Phase 2
-- storage/compute separation applied WITHIN Snowflake, not just between
-- Databricks and Snowflake)
-- =============================================================================
-- Principle: a runaway dbt build should never degrade an executive's
-- Power BI dashboard, and a heavy ad hoc analyst query should never queue
-- behind (or compete for credits with) the nightly load. Separate
-- warehouses per workload is the direct mechanism for that isolation --
-- the same blast-radius argument Phase 2 Section 5 used to justify
-- Snowflake existing in the stack at all, now applied one level deeper.

-- Loading warehouse: Snowpipe + staging-table loads (04_external_tables_and_snowpipe.sql).
-- Small and short-lived on purpose -- loading is I/O-bound, not compute-bound.
CREATE WAREHOUSE IF NOT EXISTS WH_LOADING
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 60           -- seconds; loads are bursty, suspend fast between files
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Snowpipe + staging loads only. Never used for transformation or BI queries.';

-- Transform warehouse: dbt run (Phase 9's staging->marts chain, executed
-- here in production instead of DuckDB).
CREATE WAREHOUSE IF NOT EXISTS WH_TRANSFORM
    WAREHOUSE_SIZE = 'MEDIUM'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    MIN_CLUSTER_COUNT = 1
    MAX_CLUSTER_COUNT = 3        -- multi-cluster: dbt's parallel model DAG benefits from concurrency
    SCALING_POLICY = 'STANDARD'
    COMMENT = 'dbt run/test execution (Phase 9). Sized MEDIUM based on the actual model complexity observed in Phase 9''s 35-model DAG; revisit at production data volume.';

-- BI-serving warehouse: Power BI (Phase 13) and any direct SQL dashboard
-- queries. Multi-cluster auto-scaling because concurrent executive/manager
-- dashboard sessions are genuinely unpredictable in count and timing --
-- exactly the workload multi-cluster warehouses exist for.
CREATE WAREHOUSE IF NOT EXISTS WH_BI_SERVING
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    MIN_CLUSTER_COUNT = 1
    MAX_CLUSTER_COUNT = 5
    SCALING_POLICY = 'ECONOMY'   -- favor cost over instant scale-out; a dashboard user
                                  -- waiting 20-30s longer under peak load is an acceptable
                                  -- trade against paying for idle extra clusters most of the day
    COMMENT = 'Power BI + ad hoc executive/manager SQL. Isolated from WH_TRANSFORM so a heavy dbt run never queues a dashboard query.';

-- Ad hoc analyst warehouse: deliberately separate from BI-serving so a
-- careless exploratory query (SELECT * with no filter on a billion-row
-- fact table) can't degrade the executive dashboard's SLA.
CREATE WAREHOUSE IF NOT EXISTS WH_ADHOC_ANALYST
    WAREHOUSE_SIZE = 'SMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    STATEMENT_TIMEOUT_IN_SECONDS = 1800   -- hard stop on a runaway analyst query
    COMMENT = 'Collections Strategy Analyst ad hoc SQL (Phase 1 persona). Isolated blast radius + a statement timeout as a backstop, since analysts iterate on unindexed/unfiltered queries by nature of the work.';

-- Sizing rationale (all four): start small, rely on auto-suspend/auto-resume
-- for cost control (Phase 1 NFR Cost), and size UP only after observing
-- actual query queueing in Snowflake's QUERY_HISTORY / WAREHOUSE_LOAD_HISTORY
-- views -- guessing a warehouse size upfront at portfolio-project data
-- volume would be exactly the kind of unjustified sizing decision this
-- project's documentation style argues against everywhere else.
