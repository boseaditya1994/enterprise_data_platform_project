# Business Glossary

Single source of truth for every domain term used across this project's
17 phases. Referenced from `docs/01-requirements-business-analysis.md`
Section 3 (the original domain primer, expanded here into a full
reference) and linked from every other doc rather than redefining terms
locally — the same single-definition principle this project applies to
KPIs (Phase 8/9/13) and schemas (Phase 6), now applied to language itself.

## Delinquency & Risk

| Term | Definition |
|---|---|
| **DPD** | Days Past Due — days since a missed payment's due date. |
| **Delinquency bucket** | Current, 1–29, 30–59, 60–89, 90+, Charged-off, Settled (Phase 3 `delinquency_bucket`). |
| **PAR (Portfolio At Risk)** | % of total outstanding balance in a given bucket or worse — PAR 30/60/90 (Phase 8). |
| **Roll rate** | % of delinquent accounts that move to a *worse* bucket in a period (Phase 8). |
| **Cure rate** | % of delinquent accounts that return to Current (Phase 8). |
| **Roll-to-charge-off** | The full path from first missed payment through to charge-off (Phase 4 Section 3's state machine). |
| **Risk band** | Internal risk-score classification, R1 (Super Prime) – R7 (High Risk) (Phase 3 `risk_band_dim`). |
| **FICO score** | Third-party credit bureau score; distinct from internal risk band (Phase 3 Section 2.6, Phase 6 `raw_bureau`). |

## Collections Operations

| Term | Definition |
|---|---|
| **RPC (Right-Party Contact)** | A contact attempt that reaches the actual borrower, not voicemail/wrong number/a third party (Phase 3 `is_rpc_flag`). |
| **PTP (Promise-to-Pay)** | A customer's commitment to pay a specific amount by a specific date (Phase 3 `promise_to_pay_fact`). |
| **PTP fulfillment rate** | % of PTPs that were ultimately Kept vs. Broken/Partial (Phase 8). |
| **Collection efficiency** | Past-due dollars cured / past-due dollars at risk — the dollar-weighted counterpart to cure rate (Phase 8). |
| **Contact success rate** | % of live-agent contacts that directly produced a PTP (Phase 8). |
| **Charge-off** | Writing off a loan balance as a loss after a policy-defined delinquency threshold (150+ DPD in this project's simulated policy, Phase 4 Section 5 scenario #8). |
| **Recovery** | Cash collected on a charged-off balance, typically via settlement (Phase 8 `Recovery Rate`). |
| **Settlement** | A lump-sum payment, below the full balance, that closes a charged-off loan (Phase 4 Section 5 scenario #10). |
| **Restructuring** | Modifying a delinquent loan's terms (rate/term) to make it performable again (Phase 4 Section 5 scenario #9). |

## Data Platform

| Term | Definition |
|---|---|
| **Medallion architecture** | Bronze (raw) → Silver (conformed) → Gold (business-ready) layering (Phase 2). |
| **Bronze** | Raw, minimally-touched landing zone; preserves exactly what a source sent, plus audit columns (Phase 6). |
| **Silver** | Conformed, deduplicated, identity-resolved, SCD2-versioned entities (Phase 7). |
| **Gold** | Star-schema facts/dimensions and governed KPIs, ready for BI consumption (Phase 8). |
| **SCD2 (Slowly Changing Dimension, Type 2)** | Full version history preserved via `effective_start_date`/`effective_end_date`/`is_current` (Phase 3, implemented Phase 7). |
| **CDC (Change Data Capture)** | Detecting and applying only what changed in a source since the last load, via natural key + watermark merge (Phase 2 Section 4.1). |
| **Watermark** | The column (usually a timestamp) a CDC/streaming process uses to determine "what's new" (Phase 2, Phase 6 registry). |
| **Schema drift** | A source's structure changing over time — additive (new column, auto-merges) or breaking (rename/type change, quarantined) (Phase 6 Section 5). |
| **Quarantine** | Where records failing a DQ/schema check land instead of being silently dropped or promoted (Phase 6 Section 6, Phase 14). |
| **Natural key vs. surrogate key** | Natural = the business identifier (`loan_id`); surrogate = the generated, version-specific warehouse key (`loan_sk`) (Phase 3). |
| **Star schema** | Kimball-style modeling: fact tables at a declared grain, surrounded by conformed dimensions (Phase 3). |
| **Grain** | The precise meaning of "one row" in a fact table (Phase 3 Section 3, stated explicitly per fact). |
| **Conformed dimension** | A dimension shared identically across multiple fact tables (`dim_time`, `dim_channel`, etc.) (Phase 3). |

## Regulatory & Compliance

| Term | Definition |
|---|---|
| **FDCPA** | Fair Debt Collection Practices Act — governs contact frequency/timing/conduct in debt collection (Phase 1 Section 7). |
| **UDAAP** | Unfair, Deceptive, or Abusive Acts or Practices — broad fair-treatment standard (Phase 1 Section 7). |
| **ECOA / Reg B** | Equal Credit Opportunity Act — prohibits disparate treatment by protected class; relevant to risk-band/treatment-logic auditability (Phase 1 Section 7). |
| **GLBA** | Gramm-Leach-Bliley Act — customer financial data privacy/safeguarding (Phase 1 Section 7, Phase 12 masking). |
| **SR 11-7** | Federal Reserve model-risk-management guidance — informs this project's risk-band versioning/auditability design (Phase 3 Section 2.6). |

## Technology-Specific

| Term | Definition |
|---|---|
| **MERGE INTO** | The SQL pattern for CDC upsert — match on key, update if changed, insert if new (Phase 7). |
| **ASOF JOIN** | "Latest matching row as of a timestamp" join — used for last-touch collector attribution (Phase 8 Section 3.3). |
| **Z-ORDER / clustering key** | Co-locating related data physically for query pruning — Delta's Z-ORDER (Phase 10) and Snowflake's clustering key (Phase 12) are the same idea, different engine. |
| **VACUUM** | Removing old, no-longer-referenced Delta file versions past a retention window (Phase 10 Section 6). |
| **Materialized view** | A pre-computed, auto-maintained query result, used for the highest-traffic KPI queries (Phase 12 Section 4). |
| **Row Access Policy / RLS** | Restricting which *rows* a role can see (Phase 12 Section 8, Phase 13 Section 3). |
| **Masking policy / OLS** | Restricting which *columns'* values are visible, independent of row access (Phase 12 Section 9, Phase 13 Section 3). |
