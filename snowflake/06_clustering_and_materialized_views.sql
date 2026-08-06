-- =============================================================================
-- Clustering Keys & Materialized Views
-- =============================================================================
-- Clustering columns mirror pyspark/optimization/optimize_and_maintain.py's
-- ZORDER_COLUMNS exactly (Phase 10 Section 6) -- same query-pattern
-- evidence (Phase 8's executed KPI SQL), same principle, different engine's
-- mechanism (Delta Z-ORDER co-locates data within files; Snowflake
-- clustering maintains sorted micro-partition metadata for pruning). Both
-- exist because Silver lives in Delta (Databricks-served) and Gold marts
-- live natively in Snowflake (04's design decision) -- each needs its own
-- engine-native optimization, not because the same table needs both.

ALTER TABLE MARTS.FCT_DELINQUENCY CLUSTER BY (SNAPSHOT_DATE_SK, LOAN_SK);
ALTER TABLE MARTS.FCT_PAYMENT     CLUSTER BY (PAYMENT_DATE_SK, LOAN_SK);
ALTER TABLE MARTS.FCT_CONTACT     CLUSTER BY (CONTACT_DATE_SK, COLLECTOR_SK);

-- Automatic reclustering is enabled by default once a clustering key is
-- set -- no manual maintenance job needed on the Snowflake side (unlike
-- Delta's OPTIMIZE, which Databricks must run explicitly, Phase 10
-- Section 6). This asymmetry is itself worth knowing: Snowflake bills
-- reclustering compute automatically in the background; Delta's
-- OPTIMIZE is an explicit, schedulable cost you control directly.

-- ---------------------------------------------------------------------------
-- Materialized Views -- the highest-traffic KPI queries, pre-computed
-- ---------------------------------------------------------------------------
-- Candidates chosen by actual query frequency, not guessed: PAR trend and
-- the executive summary roll/cure numbers are what EVERY dashboard page
-- (Phase 13) touches on load, per Phase 1's persona table. Lower-traffic
-- KPIs (e.g. collector productivity, viewed by a smaller ops-manager
-- audience on a drill-through page) stay as plain views -- materializing
-- everything would just spend storage/maintenance credits on views that
-- don't get the traffic to justify it.

CREATE MATERIALIZED VIEW IF NOT EXISTS KPI.MV_PAR_BY_DATE AS
    SELECT
        t.full_date AS snapshot_date,
        SUM(d.outstanding_balance) AS total_balance,
        SUM(CASE WHEN d.bucket_index >= 1 THEN d.outstanding_balance ELSE 0 END) AS balance_30plus,
        SUM(CASE WHEN d.bucket_index >= 2 THEN d.outstanding_balance ELSE 0 END) AS balance_60plus,
        SUM(CASE WHEN d.bucket_index >= 4 THEN d.outstanding_balance ELSE 0 END) AS balance_90plus
    FROM MARTS.FCT_DELINQUENCY d
    JOIN MARTS.DIM_TIME t ON t.date_sk = d.snapshot_date_sk
    GROUP BY t.full_date;

CREATE MATERIALIZED VIEW IF NOT EXISTS KPI.MV_DAILY_ROLL_CURE AS
    SELECT
        t.full_date AS snapshot_date,
        COUNT(*) FILTER (WHERE d.bucket_index >= 1) AS delinquent_population,
        COUNT(*) FILTER (WHERE d.roll_flag) AS rolled_count,
        COUNT(*) FILTER (WHERE d.cure_flag) AS cured_count
    FROM MARTS.FCT_DELINQUENCY d
    JOIN MARTS.DIM_TIME t ON t.date_sk = d.snapshot_date_sk
    WHERE d.prior_day_bucket IS NOT NULL
    GROUP BY t.full_date;

-- NOTE: materialized views auto-refresh on base-table change (Snowflake-
-- managed background compute, billed separately) -- no manual REFRESH
-- needed, unlike the external table in 04. This is Snowflake's own
-- equivalent of the "worth the added complexity" cost/benefit judgment
-- made throughout this project (Phase 4's two-profile dataset, Phase 8's
-- documented PySpark-vs-dbt exceptions): materialize the two queries that
-- earn it, leave the rest as plain views.

-- ---------------------------------------------------------------------------
-- Search Optimization Service -- point-lookup acceleration
-- ---------------------------------------------------------------------------
-- Power BI's account drill-through (Phase 13, Customer Drilldown page)
-- does a highly selective point lookup (WHERE loan_id = ?) against a
-- clustered-but-not-indexed fact table -- clustering helps range scans,
-- not equality point lookups at this selectivity. Search Optimization
-- Service is the right tool specifically for that access pattern.
ALTER TABLE MARTS.FCT_DELINQUENCY ADD SEARCH OPTIMIZATION ON EQUALITY(loan_id);
ALTER TABLE MARTS.FCT_PAYMENT     ADD SEARCH OPTIMIZATION ON EQUALITY(loan_id);
