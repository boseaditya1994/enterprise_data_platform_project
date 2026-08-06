-- =============================================================================
-- Streams & Tasks -- Snowflake-side change-driven gate
-- =============================================================================
-- RELATIONSHIP TO ADF (Phase 11): ADF's schedule trigger is the PRIMARY
-- orchestration mechanism (triggers Databricks, polls dbt Cloud). These
-- Streams/Tasks are a complementary, Snowflake-native SAFETY GATE: even
-- if ADF's trigger fires on schedule regardless of whether new Silver
-- data actually landed, a Task that checks SYSTEM$STREAM_HAS_DATA before
-- running dbt avoids a wasted (and misleadingly "successful") dbt run
-- against stale staging tables -- e.g. if Databricks' Silver job ran
-- late or failed upstream of Snowpipe. This is a defensive layer, not a
-- second competing orchestrator.

-- One stream per Snowpipe-loaded staging table, tracking inserts only
-- (Silver tables land as append-then-native-table-replace per Snowpipe's
-- COPY INTO semantics -- see 04's design note on why native tables, not
-- Delta-aware CDC, are used here).
CREATE STREAM IF NOT EXISTS STAGING.STRM_SILVER_DELINQUENCY
    ON TABLE STAGING.SILVER_DELINQUENCY
    APPEND_ONLY = TRUE
    COMMENT = 'Tracks new rows landed by PIPE_SILVER_DELINQUENCY since the last task consumed the stream.';

CREATE STREAM IF NOT EXISTS STAGING.STRM_SILVER_PAYMENT
    ON TABLE STAGING.SILVER_PAYMENT
    APPEND_ONLY = TRUE;

-- Task: gate + trigger. Runs on a schedule slightly AFTER ADF's expected
-- Bronze/Silver completion window (Phase 11's tr_daily_schedule fires at
-- 6 AM UTC; this task runs at 8 AM UTC as a defensive check, not the
-- primary trigger).
CREATE TASK IF NOT EXISTS STAGING.TASK_VALIDATE_AND_NOTIFY_GOLD_READY
    WAREHOUSE = WH_TRANSFORM
    SCHEDULE = 'USING CRON 0 8 * * * UTC'
    WHEN
        SYSTEM$STREAM_HAS_DATA('STAGING.STRM_SILVER_DELINQUENCY')
        AND SYSTEM$STREAM_HAS_DATA('STAGING.STRM_SILVER_PAYMENT')
AS
    CALL AUDIT.USP_LOG_GOLD_READY_CHECK(CURRENT_TIMESTAMP());

-- Companion task: if the stream is STILL empty by 9 AM (meaning Silver
-- data never landed as expected), page on-call directly from Snowflake --
-- an independent alert path from ADF's own (Phase 11 Section 3), so a
-- failure that somehow didn't trip ADF's alerting (e.g. ADF itself is
-- down) still gets caught.
CREATE TASK IF NOT EXISTS STAGING.TASK_ALERT_ON_MISSING_SILVER_DATA
    WAREHOUSE = WH_TRANSFORM
    SCHEDULE = 'USING CRON 0 9 * * * UTC'
    WHEN
        NOT SYSTEM$STREAM_HAS_DATA('STAGING.STRM_SILVER_DELINQUENCY')
AS
    CALL AUDIT.USP_SEND_ALERT(
        'Snowflake: no new silver.delinquency rows detected by 9 AM UTC -- Bronze/Silver pipeline likely failed upstream.'
    );

ALTER TASK STAGING.TASK_VALIDATE_AND_NOTIFY_GOLD_READY RESUME;
ALTER TASK STAGING.TASK_ALERT_ON_MISSING_SILVER_DATA RESUME;

-- NOTE: consuming a stream (any SELECT against it inside a task body,
-- even indirectly via the stored procedure) advances its offset. Both
-- tasks above only CHECK has_data in the WHEN clause (which does NOT
-- consume the stream) and never directly SELECT from the stream itself --
-- deliberate, so this defensive layer never interferes with whatever
-- actually consumes the stream data for real (if anything does, in a
-- future Snowflake-native transformation step).
