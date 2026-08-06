# Phase 8 — Gold Layer (incl. KPI Layer)

**Traces to:** Phase 3 (star schema — every table below is exactly what
was specified there), Phase 7 (every Gold table is built from a Silver
table in the same DuckDB warehouse). Code: [`sql/gold/`](../sql/gold/).

**Scope note:** the original brief lists "Gold Layer" and "KPI Layer" as
separate sections, but the 17-phase plan has no separate KPI phase — the
KPI catalog (12 metrics, each with business definition / SQL / actual
computed value / interpretation / pitfalls) lives here, in Section 4,
since that's genuinely where it's built (Gold-layer views over the star
schema). All numbers in this document are from a real, executed run —
[`sql/gold/local_execution/run_gold_build_duckdb.py`](../sql/gold/local_execution/run_gold_build_duckdb.py)
against the same warehouse Phase 7 built.

---

## 1. Dimensions Built

| Dimension | Source | Pattern | Result |
|---|---|---|---|
| `dim_customer` | `silver.customer` | Direct promotion (already SCD2, Gold-shaped) | 8,400 rows |
| `dim_loan` | `silver.loan` | Direct promotion | 10,389 rows |
| `dim_collector` | `bronze.raw_collectors_daily` | Incremental SCD2 (same pattern as Silver `customer`) | 168 versions, 2 batches (initial load + reorg) |
| `dim_channel` | Static reference (Phase 3 design) | Literal load | 13 rows (see Section 2) |
| `dim_risk_band` | Static reference (Phase 3 design) | Literal load | 7 rows |
| `dim_time` | Generated (2023–2027) | Calendar generation + US bank holiday flags | 1,826 rows |

**Why `dim_customer`/`dim_loan` are direct promotions, not rebuilt:**
Silver already produced the exact SCD2 shape Phase 3 specifies for these
dimensions — rebuilding them would just be copying the same logic twice.
This is a legitimate, common pattern (some shops call this layer "Silver
that's also Gold-shaped") as long as it's a deliberate choice, documented
here, rather than an accident of not knowing where the boundary is.

---

## 2. A Gap Found and Fixed While Building `dim_channel`

Phase 3 designed `channel_dim` around **contact** channels (call, SMS,
IVR, letter, etc.) — 9 codes. But `payment_fact.channel_sk` needs to
resolve every `silver.payment.payment_method` value (`ACH`, `Debit Card`,
`Check`, `Wire`, `Cash`), and only `ACH` and `BRANCH` from the original 9
actually cover payment methods. Building `payment_fact`'s join immediately
surfaced this gap. Fix: added 4 more channel codes (`DEBIT_CARD`, `CHECK`,
`WIRE`, `CASH`) at Gold-build time — documented here rather than silently
patched, since it's a real example of a dimension design surfacing a gap
only once a downstream fact actually tries to join to it.

---

## 3. Facts Built — and Two Real Bugs Found Along the Way

| Fact | Rows | Notes |
|---|---|---|
| `payment_fact` | 48,743 (of 49,473 Silver rows) | See Section 3.2 — 730 rows correctly excluded, not lost |
| `delinquency_fact` | 1,509,105 (exact match to Silver) | See Section 3.1 — required a bug fix to get here |
| `contact_fact` | 38,569 | Matches Silver exactly after the same fix |
| `promise_to_pay_fact` | 1,847 | Matches Silver closely (small SCD2-boundary effect on collector attribution) |

### 3.1 Bug: inclusive `BETWEEN` on SCD2 date ranges double-counts boundary days

First build attempt produced **1,509,858** delinquency rows — 753 more
than Silver's 1,509,105. Root cause: SCD2 rows are built with
`effective_end_date` of the OLD version set to exactly the
`source_updated_at` of the NEW version (Phase 7's two-pass MERGE
pattern) — so a day landing exactly on that boundary satisfied
`BETWEEN effective_start_date AND effective_end_date` for **both** the
closing row and the opening row. Fixed by switching every SCD2 join
(customer, loan, collector) from inclusive `BETWEEN` to a half-open
interval: `date >= effective_start_date AND date < effective_end_date`.
Re-running produced **exactly** 1,509,105 — matching Silver to the row.
**This is a genuinely common real-world SCD2 bug** (not manufactured for
this writeup) and a good one to be able to describe in an interview,
including why `BETWEEN` is the wrong tool for half-open version ranges.

### 3.2 Investigation: 730 `payment_fact` rows didn't join

Rather than assume this was another bug, it was investigated by
splitting the failure by which join caused it:

| Cause | Row count | Verdict |
|---|---|---|
| No matching `dim_loan` version for the payment's date | 656 | **Real generator limitation** (see below) |
| `customer_id` is `NULL` on the source row | 74 | **Correct behavior** — see below |

- **The 74 "customer_id is NULL" rows** are exactly Phase 4/5's scenario
  #13 corrupt-record injection (nulled required field). These *should*
  fail to join and *should not* land in Gold — this is the DQ design
  working as intended, not a defect. Confirmed by checking their
  `payment_id`s against `is_corrupt_record` in Bronze.
- **The 656 "no matching loan version" rows** are all `payment_type =
  'Extra'`. Root cause: Phase 5's `messiness.finalize_payments()`
  assigns extra-payment dates uniformly across the whole 6-month window,
  independent of each loan's actual origination date — so a loan that
  originated (say) March 2025 can get an "Extra" payment dated January
  2025, before the loan existed. This is a genuine, if minor, Phase 5
  generator limitation (documented here rather than silently
  regenerating the whole dataset and invalidating every row-count in
  Phases 5–7's docs) — the fix would be constraining
  `extra_loan_ids`' payment dates to `>= loan.origination_date` in
  `identities.py`/`messiness.py`. **The important part:** Gold's INNER
  JOIN correctly refuses to fabricate a loan version for a payment that
  predates the loan's existence, rather than silently attaching it to
  the wrong (or a nonexistent) version — exactly the behavior you'd want
  in production, where this would route to a referential-integrity
  quarantine (Phase 14) instead of silently dropping.

### 3.3 `delinquency_fact.assigned_collector_id` — a documented proxy, not a real field

Phase 3 specifies `delinquency_fact.collector_sk` as "currently assigned
collector." Our generator has no explicit assignment table — collectors
are chosen per-contact, not persistently assigned to a loan. The Gold
build uses an **ASOF JOIN** (DuckDB's "latest matching row as of a
timestamp" join) against `contact_fact` to attribute each loan-day to
whichever collector most recently contacted that loan, as a documented
analytical proxy. Only **9.5%** of loan-days get an attribution this way
— expected, since most loan-days are Current (no collections activity at
all) and even delinquent loan-days often precede the loan's first
contact. This coverage rate is itself a useful diagnostic: if it came
back near 100% or near 0%, that would suggest a join bug rather than a
sparse-by-nature signal.

---

## 4. KPI Catalog

All values below are **actually computed** by
`sql/gold/kpi_definitions.sql`'s views (executed via
`run_gold_build_duckdb.py`) against the real dataset. PAR figures are "as
of" the last snapshot date in the window, 2025-06-30; rate KPIs are
computed across the full 6-month window unless noted.

### PAR 30 / PAR 60 / PAR 90
- **Business definition:** the % of total outstanding portfolio balance
  that is 30+ / 60+ / 90+ days past due, as of a given date.
- **SQL:** `gold.vw_par_by_date` (in `kpi_definitions.sql`).
- **Computed value (2025-06-30):** PAR 30 = **8.00%**, PAR 60 = **4.28%**, PAR 90 = **1.64%**.
- **Interpretation:** each PAR bucket should nest inside the one before
  it (PAR 90 ≤ PAR 60 ≤ PAR 30, which holds here) — a portfolio-health
  headline number for executives (Phase 1 persona: VP Collections,
  Credit Risk Officer).
- **Common pitfall:** computing PAR on *loan count* instead of *dollar
  balance* — a portfolio of many small current loans and few large
  delinquent ones looks very different by count vs. by balance, and
  balance is what actually drives loss exposure. This implementation
  weights by `outstanding_balance` deliberately.

### Roll Rate
- **Business definition:** of accounts that were delinquent yesterday,
  the % that moved to a **worse** bucket today.
- **SQL:** `gold.vw_roll_rate_daily`.
- **Computed value (window average):** **3.254%** daily roll rate among
  the delinquent population.
- **Interpretation:** the earlier a roll is caught (e.g., 1-29→30-59 vs.
  60-89→90+), the more treatable it usually is — Phase 13's Roll Rates
  dashboard page breaks this out by originating bucket, not just as one
  blended number.
- **Common pitfall:** computing roll rate against the *whole portfolio*
  instead of the *delinquent population* — diluting it into a
  meaningless near-zero number. This implementation's denominator is
  explicitly `bucket_index >= 1` accounts only.

### Cure Rate
- **Business definition:** of accounts that were delinquent yesterday,
  the % that returned to Current today.
- **SQL:** `gold.vw_cure_rate_daily`.
- **Computed value (window average):** **1.288%** daily cure rate.
- **Interpretation:** cure rate this low relative to roll rate (3.25%)
  reflects the generator's calibrated cure probabilities being harder at
  deeper buckets (Phase 4 Section 5's `CURE_PROB_BY_DEPTH` decays from
  55% at 1-29 down to 8% at 90+) — a real portfolio would expect the same
  shape: most cures happen early, roll-forward dominates once an account
  is deep.
- **Common pitfall:** conflating cure rate with roll rate's complement
  (`1 - roll_rate`) — they're not opposites; an account can also stay in
  the *same* bucket (neither cured nor rolled), which is in fact the
  majority daily outcome here (~95%+).

### Recovery Rate
- **Business definition:** $ recovered via settlement, as a % of the
  original balance on charged-off loans.
- **SQL:** `gold.vw_recovery_rate`.
- **Computed value:** **11.59%**.
- **Interpretation:** matches expectation directly from the Phase 4/5
  design — only ~30% of charged-off loans get a settlement at all
  (`PCT_CHARGED_OFF_SETTLED`), and settlements themselves recover 35–65%
  of balance, so a blended ~11–12% recovery rate across *all*
  charged-off loans (settled and un-settled) is exactly right.
- **Common pitfall:** computing recovery rate only against *settled*
  loans instead of *all* charged-off loans — that would overstate
  recovery performance by hiding the majority of charge-offs that
  recovered nothing.

### Call Connect Rate
- **Business definition:** % of live-agent outbound call attempts that
  reach the actual borrower (right-party contact).
- **SQL:** `gold.vw_call_connect_rate`.
- **Computed value:** **54.98%**.
- **Interpretation:** matches the generator's calibrated
  `LIVE_AGENT_OUTCOME_WEIGHTS` (55% RPC) almost exactly — validates the
  full chain from generator through Bronze/Silver/Gold preserved the
  intended distribution.
- **Common pitfall:** including automated channels (SMS/IVR "Delivered")
  in a "connect rate" number meant to describe live-agent performance —
  this implementation explicitly filters to `channel_category =
  'Live Agent'`.

### Promise-to-Pay Fulfillment Rate
- **Business definition:** % of PTPs that were ultimately Kept.
- **SQL:** `gold.vw_ptp_fulfillment_rate`.
- **Computed value:** **65.46%**.
- **Interpretation:** matches the generator's `PTP_KEEP_PROB = 0.65`
  target closely — same validation logic as above.
- **Common pitfall:** counting `Partial` PTPs as "fulfilled" — they're
  not Broken, but they're not fully Kept either; this metric only counts
  exact `Kept` status, with Partial tracked as its own category for
  collections strategy analysis (Phase 13).

### Collector Productivity
- **Business definition:** contacts made, PTPs obtained, and $ actually
  collected via kept PTPs, per collector.
- **SQL:** `gold.vw_collector_productivity`.
- **Computed value (top 5 by kept dollars):**

  | Collector | Team | Contacts | PTPs | Kept $ |
  |---|---|---|---|---|
  | Amber Garza | Late Stage 90+ | 98 | 29 | $2,152,431 |
  | Bryan Elliott | Late Stage 90+ | 103 | 28 | $1,787,036 |
  | Dean Nelson | Late Stage 90+ | 94 | 31 | $1,711,158 |
  | James Ramos | Late Stage 90+ | 92 | 37 | $1,690,540 |
  | Katie Lewis | Late Stage 90+ | 93 | 27 | $1,656,522 |

- **Interpretation:** top 5 are all "Late Stage 90+" collectors —
  expected, since PTP dollar amounts scale with DPD in the generator
  (`ptp_amount = dpd * random(3,9)`), so late-stage PTPs are inherently
  larger dollar commitments. This is exactly why Phase 1 flagged
  "collectors measured by call volume, not $ collected" as a root-cause
  problem — a call-volume ranking would look completely different from
  this $-based ranking, and the platform's whole point is making that
  visible.
- **Common pitfall:** ranking collectors by raw contact volume (call
  count) — rewards quantity over outcome, and doesn't account for the
  fact that different teams work fundamentally different account
  profiles (early-stage accounts are smaller-dollar, higher-volume by
  design).

### Average Days Delinquent
- **Business definition:** mean DPD across all currently-delinquent
  loan-days.
- **SQL:** `gold.vw_avg_days_delinquent`.
- **Computed value (window average):** **50.7 days**.
- **Common pitfall:** averaging DPD across the *whole portfolio*
  (including Current loans, DPD=0) instead of the delinquent population —
  this implementation filters to `bucket_index BETWEEN 1 AND 4`
  specifically to avoid that distortion.

### Collection Efficiency
- **Business definition:** of the past-due dollar balance at risk, the %
  that was successfully cured (returned to Current), daily.
- **SQL:** `gold.vw_collection_efficiency`.
- **Computed value (window average):** **1.30%**.
- **Interpretation:** intentionally close to (but not identical to) Cure
  Rate above — this metric weights by *dollars*, Cure Rate weights by
  *account count*. The two should track directionally but rarely
  match exactly, and a large divergence between them would flag that
  large-balance and small-balance accounts are curing at meaningfully
  different rates — worth watching for in real portfolio monitoring.
- **Common pitfall:** treating Collection Efficiency and Cure Rate as
  interchangeable — presenting only one to executives can hide whether
  cures are concentrated in small or large balances.

### Contact Success Rate
- **Business definition:** % of live-agent contacts that directly
  produced a promise-to-pay.
- **SQL:** `gold.vw_contact_success_rate`.
- **Computed value:** **29.82%**.
- **Interpretation:** lower than Call Connect Rate (55.0%) as expected —
  not every right-party contact converts to a PTP, and this metric
  correctly uses the full live-agent contact population as its
  denominator (not just RPCs), so it implicitly captures both
  "did we reach them" and "did the conversation work."
- **Common pitfall:** defining "success" as merely reaching the
  customer (conflating it with Call Connect Rate) rather than tying it
  to a concrete collections outcome (a PTP) — this implementation
  deliberately ties it to `EXISTS (... promise_to_pay_fact ...)`.

---

## 5. Design Rationale

**Why show the SCD2 boundary bug and the payment-drop investigation
instead of a clean, bug-free narrative:** this is the same principle as
every prior phase — a portfolio project that only ever shows things
working is less credible than one that shows real debugging judgment.
The `BETWEEN` boundary bug in particular is a bug real engineers hit
constantly in production SCD2 pipelines; being able to describe it,
diagnose it, and explain the half-open-interval fix is a stronger
interview signal than never having encountered it.

**Why validate every KPI against the generator's own known injection
rates (Section 4) instead of just computing them:** the same "trust
nothing unmeasured" throughline from every prior phase — a KPI that
happens to match its known-good target (PTP fulfillment ≈ 65% vs.
generator's 0.65 target, connect rate ≈ 55% vs. 55% target) is strong
evidence the full Bronze→Silver→Gold chain preserved the data correctly
end to end, not just that the SQL runs without erroring.

**Common interview questions for this phase:**
- *"Walk me through a bug you found building this."* → Section 3.1, in
  full — root cause, why `BETWEEN` was wrong, the fix, and how you
  verified the fix (exact row-count match to Silver).
- *"How do you validate a KPI is computing correctly?"* → Section 4's
  repeated technique of comparing computed KPI values back to the
  generator's own known injection-rate targets.
- *"What's the difference between Cure Rate and Collection Efficiency?"*
  → Collection Efficiency's write-up — same concept, different
  weighting (dollars vs. accounts), and why both matter.
- *"How would you attribute a 'currently assigned collector' if your
  source system doesn't track that explicitly?"* → Section 3.3's ASOF
  JOIN last-touch-attribution design, and why the 9.5% coverage rate is
  itself a meaningful sanity check rather than a red flag.

---

## Next

**Phase 9 — dbt Models**: translating this same Silver/Gold logic into a
proper dbt project — sources, staging/intermediate/mart models,
snapshots (for SCD2, replacing the hand-rolled MERGE), schema tests,
macros, and generated documentation/lineage.

Say **"continue to Phase 9"** (or flag changes to Phase 8) when ready.
