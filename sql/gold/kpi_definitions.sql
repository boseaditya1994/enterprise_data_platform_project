-- =============================================================================
-- Gold: KPI Layer -- 12 governed metric definitions, each as a view
-- =============================================================================
-- Every KPI is defined ONCE here and consumed by Power BI (Phase 13), ad hoc
-- SQL, and any other consumer -- this is the direct fix for Phase 1's root
-- cause (Section 2.1: roll-rate/cure-rate numbers disagreeing across teams
-- because everyone computed them differently). See docs/08-gold-layer.md for
-- business definitions, actual computed values, interpretation, and pitfalls.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- PAR 30 / 60 / 90 (Portfolio At Risk) -- as of any snapshot date
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_par_by_date AS
SELECT
    t.full_date AS snapshot_date,
    SUM(d.outstanding_balance)                                                   AS total_balance,
    SUM(CASE WHEN d.bucket_index >= 1 THEN d.outstanding_balance ELSE 0 END)      AS balance_30plus,
    SUM(CASE WHEN d.bucket_index >= 2 THEN d.outstanding_balance ELSE 0 END)      AS balance_60plus,
    SUM(CASE WHEN d.bucket_index >= 4 THEN d.outstanding_balance ELSE 0 END)      AS balance_90plus,
    balance_30plus / NULLIF(total_balance, 0) AS par_30,
    balance_60plus / NULLIF(total_balance, 0) AS par_60,
    balance_90plus / NULLIF(total_balance, 0) AS par_90
FROM gold.delinquency_fact d
JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
GROUP BY t.full_date;

-- ---------------------------------------------------------------------------
-- Roll Rate -- % of delinquent accounts that moved to a WORSE bucket, daily
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_roll_rate_daily AS
SELECT
    t.full_date AS snapshot_date,
    COUNT(*) FILTER (WHERE d.bucket_index >= 1)                AS delinquent_population,
    COUNT(*) FILTER (WHERE d.roll_flag)                        AS rolled_count,
    rolled_count::DOUBLE / NULLIF(delinquent_population, 0)    AS roll_rate
FROM gold.delinquency_fact d
JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
WHERE d.prior_day_bucket IS NOT NULL
GROUP BY t.full_date;

-- ---------------------------------------------------------------------------
-- Cure Rate -- % of delinquent accounts that returned to Current, daily
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_cure_rate_daily AS
SELECT
    t.full_date AS snapshot_date,
    COUNT(*) FILTER (WHERE d.prior_day_bucket != 'Current')    AS delinquent_population,
    COUNT(*) FILTER (WHERE d.cure_flag)                        AS cured_count,
    cured_count::DOUBLE / NULLIF(delinquent_population, 0)     AS cure_rate
FROM gold.delinquency_fact d
JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
WHERE d.prior_day_bucket IS NOT NULL
GROUP BY t.full_date;

-- ---------------------------------------------------------------------------
-- Recovery Rate -- settlement/recovery $ collected on charged-off balances
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_recovery_rate AS
SELECT
    SUM(CASE WHEN pf.payment_type = 'Settlement' THEN pf.payment_amount ELSE 0 END) AS recovered_amount,
    SUM(l.origination_amount)                                                       AS charged_off_original_balance,
    recovered_amount / NULLIF(charged_off_original_balance, 0)                      AS recovery_rate
FROM gold.dim_loan l
LEFT JOIN gold.payment_fact pf ON pf.loan_sk = l.loan_sk
WHERE l.charge_off_flag AND l.is_current;

-- ---------------------------------------------------------------------------
-- Call Connect Rate -- % of live-agent outbound attempts that reach the RPC
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_call_connect_rate AS
SELECT
    COUNT(*)                              AS live_agent_attempts,
    COUNT(*) FILTER (WHERE cf.is_rpc_flag) AS right_party_contacts,
    right_party_contacts::DOUBLE / NULLIF(live_agent_attempts, 0) AS call_connect_rate
FROM gold.contact_fact cf
JOIN gold.dim_channel ch ON ch.channel_sk = cf.channel_sk
WHERE ch.channel_category = 'Live Agent';

-- ---------------------------------------------------------------------------
-- Promise-to-Pay Fulfillment Rate
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_ptp_fulfillment_rate AS
SELECT
    COUNT(*)                                    AS total_ptps,
    COUNT(*) FILTER (WHERE ptp_status = 'Kept') AS kept_ptps,
    kept_ptps::DOUBLE / NULLIF(total_ptps, 0)   AS ptp_fulfillment_rate
FROM gold.promise_to_pay_fact;

-- ---------------------------------------------------------------------------
-- Collector Productivity -- contacts, PTPs obtained, $ actually collected
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_collector_productivity AS
SELECT
    col.collector_id, col.collector_name, col.team_name,
    COUNT(DISTINCT cf.contact_id)  AS contacts_made,
    COUNT(DISTINCT ptp.ptp_id)     AS ptps_obtained,
    SUM(CASE WHEN ptp.ptp_status = 'Kept' THEN ptp.amount_paid_against_ptp ELSE 0 END) AS kept_dollars_collected
FROM gold.dim_collector col
LEFT JOIN gold.contact_fact cf ON cf.collector_sk = col.collector_sk
LEFT JOIN gold.promise_to_pay_fact ptp ON ptp.collector_sk = col.collector_sk
WHERE col.is_current
GROUP BY col.collector_id, col.collector_name, col.team_name;

-- ---------------------------------------------------------------------------
-- Average Days Delinquent -- across all currently-delinquent loan-days
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_avg_days_delinquent AS
SELECT t.full_date AS snapshot_date, AVG(d.dpd) AS avg_days_delinquent
FROM gold.delinquency_fact d
JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
WHERE d.bucket_index BETWEEN 1 AND 4
GROUP BY t.full_date;

-- ---------------------------------------------------------------------------
-- Collection Efficiency -- past-due $ CURED / past-due $ AT RISK, daily
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_collection_efficiency AS
SELECT
    t.full_date AS snapshot_date,
    SUM(CASE WHEN d.prior_day_bucket != 'Current' THEN d.outstanding_balance ELSE 0 END) AS past_due_balance_at_risk,
    SUM(CASE WHEN d.prior_day_bucket != 'Current' AND d.bucket_index = 0
             THEN d.outstanding_balance ELSE 0 END)                                      AS past_due_balance_cured,
    past_due_balance_cured / NULLIF(past_due_balance_at_risk, 0)                         AS collection_efficiency
FROM gold.delinquency_fact d
JOIN gold.dim_time t ON t.date_sk = d.snapshot_date_sk
WHERE d.prior_day_bucket IS NOT NULL
GROUP BY t.full_date;

-- ---------------------------------------------------------------------------
-- Contact Success Rate -- % of live-agent contacts that directly produced a PTP
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW gold.vw_contact_success_rate AS
SELECT
    COUNT(*)                                                                    AS live_agent_contacts,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM gold.promise_to_pay_fact p WHERE p.contact_id = cf.contact_id
    ))                                                                           AS contacts_resulting_in_ptp,
    contacts_resulting_in_ptp::DOUBLE / NULLIF(live_agent_contacts, 0)          AS contact_success_rate
FROM gold.contact_fact cf
JOIN gold.dim_channel ch ON ch.channel_sk = cf.channel_sk
WHERE ch.channel_category = 'Live Agent';
