# Phase 7 — Silver Layer

**Traces to:** Phase 2 (CDC/streaming design), Phase 3 (star schema, SCD
strategy per table), Phase 6 (Bronze schema registry — every Silver model
below reads directly from a registered Bronze table). Code: [`sql/silver/`](../sql/silver/).

**Scope note:** as with Phase 6, this phase's SQL is real, executable
logic — not narrated pseudocode. Since this sandbox has no Snowflake/
Databricks cluster, [`sql/silver/local_execution/run_silver_build_duckdb.py`](../sql/silver/local_execution/run_silver_build_duckdb.py)
runs equivalent MERGE INTO / window-function SQL against DuckDB (which
supports the same `MERGE INTO` syntax) directly on the real Phase 5
generated data, and the results in Section 7 are from that actual run.

---

## 1. Silver Entities Built

| Silver table | Source(s) | Pattern | SQL file |
|---|---|---|---|
| `silver.customer` | `bronze.raw_crm` | Incremental SCD2, day-by-day MERGE | `01_customer_scd2_merge.sql` |
| `silver.loan` | `bronze.raw_servicing_loans` + `raw_servicing_loan_events` | Windowed full-history SCD2 build | `02_loan_scd2_merge.sql` |
| `silver.payment` | `bronze.raw_payments` | Dedup + CDC upsert | `03_payment_cdc_merge.sql` |
| `silver.contact` | `bronze.raw_call_center` + `raw_collections` | Union + conform + dedup, append-only | `04_contact_conform_merge.sql` |
| `silver.delinquency` | `bronze.raw_servicing_daily_status` | Conform + `LAG()`-derived roll/cure flags | `05_delinquency_conform_merge.sql` |
| `silver.promise_to_pay` | `bronze.raw_collections_ptp` | Dedup + CDC upsert (mutable status) | `06_promise_to_pay_merge.sql` |

**On "account" (the original brief's sixth Silver entity):** in this
single-product-per-loan design, an "account" and a "loan" are the same
thing — there's no revolving multi-product container above the loan level
(Phase 3's star schema reflects this too: no separate `account_dim`). It's
called out explicitly here rather than silently dropped, since a real
credit-card or deposit-account platform *would* need this distinction
(one account, many transactions, vs. one loan, one origination) — noted
as a documented modeling decision, not an oversight.

---

## 2. Why Three Different Merge Patterns for Six Tables

Phase 2 committed to "merge on natural key + source timestamp" as the CDC
strategy generally, but *how* that gets executed differs by what kind of
change the entity experiences — using one pattern everywhere would be
wrong, not just suboptimal:

| Pattern | Used for | Why |
|---|---|---|
| **Incremental day-by-day SCD2 MERGE** | `customer` | CRM attribute changes are independent, unordered edits (address today, employment status next month) — must be applied as a true batch-by-batch history to get `effective_start_date`/`effective_end_date` right |
| **Windowed full-history SCD2 build** | `loan` | Lifecycle flags (`restructured_flag`, `charge_off_flag`, etc.) are monotonic/cumulative — "was this loan already restructured as of date X" is a pure set-based question, so a single windowed query is both correct *and* simpler than iterating |
| **Single-pass dedup + upsert** | `payment`, `contact`, `promise_to_pay` | No SCD-style historical versioning needed — these are event/fact-shaped, not attribute-shaped; the only Silver-layer job is picking one winner per natural key when duplicates exist (Section 4) |

Being able to explain *why* a given entity gets a given pattern — not
just apply MERGE everywhere by rote — is exactly the kind of judgment a
senior data engineer is expected to demonstrate.

---

## 3. Identity Resolution & Survivorship

**The honest gap, stated directly:** Phase 5's synthetic generator uses
one shared `customer_id` across CRM, Servicing, and Bureau (documented in
`docs/04-dataset-design.md` Section 6) — a real bank's sources each mint
their own local ID, and Silver's `customer_id` join key would need to be
*produced* by matching, not just consumed. Rather than silently gloss
over this, the actual matching algorithm is implemented and proven
independently: [`sql/silver/local_execution/identity_resolution_demo.py`](../sql/silver/local_execution/identity_resolution_demo.py).

**Algorithm:**
1. **Blocking** on `(ssn_last4, date_of_birth)` — fields very unlikely to
   legitimately differ across systems for the same person, and cheap to
   index/join on at scale (full pairwise name comparison across millions
   of records is not tractable; blocking narrows candidates first).
2. **Scoring** candidate pairs within a block by normalized last-name
   similarity (`difflib.SequenceMatcher`, standing in for a production
   library like `jellyfish`/`recordlinkage` with Jaro-Winkler or similar).
3. **Clustering** via Union-Find — every pair scoring above threshold
   merges into one golden `customer_id`.
4. **Fallback block** for records missing `ssn_last4` (Bureau data gaps
   are common) — falls back to `(date_of_birth, exact last name, fuzzy
   first name)`, weaker and would route to manual review in production
   rather than auto-merge silently.

**Proven result**, run against a deliberately fragmented 13-record / 3-source
sample: correctly collapsed to exactly 6 golden IDs for 6 real people —
including correctly **keeping two different people who share a last name
separate** (negative control: Sarah Kim vs. David Kim, different SSN/DOB
block) and correctly **matching a record with no SSN on file** via the
fallback path (Elena Petrova's Bureau record). Full output:

```
CUST-GOLDEN-001 (3 records): CRM-001/SVC-901/BUR-317 -- "Maria"/"M." Chen
CUST-GOLDEN-002 (3 records): CRM-002/SVC-902/BUR-318 -- Whitfield / "Whitfeld" typo
CUST-GOLDEN-003 (3 records): CRM-003/SVC-903/BUR-319 -- "Robert"/"Bob" Garcia
CUST-GOLDEN-004 (1 record):  Sarah Kim   -- correctly NOT merged with David Kim
CUST-GOLDEN-005 (1 record):  David Kim   -- correctly NOT merged with Sarah Kim
CUST-GOLDEN-006 (2 records): Elena Petrova -- Bureau record (no SSN) correctly matched
```

**Survivorship rule** (which source wins when attributes conflict, once
identity is resolved): CRM is system-of-record for demographic/contact
attributes (Phase 1 stakeholder table names CRM as the customer-facing
system); Bureau/Servicing values are used only to *fill gaps* CRM leaves
null, never to overwrite a populated CRM value. This is a simple,
documented rule rather than a scored survivorship model — appropriate
given the actual attribute set here (address/segment/employment), but
called out as the kind of decision that would need real stakeholder
sign-off (Phase 1 RACI: Compliance/Risk consulted) at a real bank.

---

## 4. Deduplication

Every non-SCD2 table (`payment`, `contact`, `promise_to_pay`) applies the
same pattern: `ROW_NUMBER() OVER (PARTITION BY <natural_key> ORDER BY
_ingestion_ts DESC) = 1`, keeping the most-recently-landed copy of a
duplicated natural key (Phase 4/5 scenario #5). This is a NULL-safe,
single-pass dedup that works identically whether the duplicate landed in
the same batch or a later one — no separate "catch up on old duplicates"
job needed.

---

## 5. Late-Arriving Data — two different mechanisms for two different problems

- **`silver.payment`**: solved structurally. Bronze partitions by
  `ingestion_date` (Phase 6 Section 4) but the Silver MERGE keys on
  `payment_id` and preserves `effective_date` as a normal column — so a
  payment landing 8 days late still merges into the correct row with the
  correct historical `effective_date`. Partitioning strategy and merge
  correctness are fully decoupled by design.
- **`silver.delinquency`**: harder, and stated honestly rather than
  glossed over. `prior_day_bucket`/`cure_flag`/`roll_flag` need
  `LAG(...) OVER (PARTITION BY loan_id ORDER BY snapshot_date)` — but
  `raw_servicing_daily_status` lands **one snapshot_date per file**, so a
  naive per-batch MERGE would see only one row per loan per run and
  `LAG()` would always return `NULL`. The production fix (documented in
  `05_delinquency_conform_merge.sql`'s closing comment) is a dbt
  incremental model with a **lookback window** — re-derive the trailing
  N days on every run so each new day's `LAG()` has yesterday's
  already-landed row to compare against, then only insert the newly
  new rows. For this phase's executable proof, `run_silver_build_duckdb.py`
  instead computes `LAG()` over the **full history in one pass** — the
  bootstrap-equivalent of the lookback-window pattern, and how this table
  would be built the very first time regardless.

---

## 6. Corrupt Record Handling

`silver.contact`'s build explicitly filters out any Bronze row still
carrying `is_corrupt_record = TRUE` — those rows already sat in Bronze's
quarantine path (Phase 6 Section 6) and are never promoted to Silver
until a human resolves them. The executable run below shows exactly how
many were caught.

---

## 7. Actual Execution Results

Run against the real Phase 5 dataset (10,016 loans, 8,400 customer
versions, 181 days):

```
[Silver] silver.customer: 8,400 total versions (8,000 current, 400 historical)
         across 132 incremental batches
[Silver] silver.loan: 10,389 total versions (10,016 current loans),
         73 restructured, 201 charged off
[Silver] silver.payment: 49,967 bronze rows -> 49,473 deduped silver rows
         (494 duplicates removed)
         reversal referential-integrity check: 0 orphaned reversals (expect 0)
[Silver] silver.contact: 6,239 call_center + 32,832 collections bronze rows
         -> 38,569 silver rows (117 corrupt rows quarantined, dupes deduped)
[Silver] silver.delinquency: 1,509,105 rows, 1,462 cure events, 3,708 roll events
[Silver] silver.promise_to_pay: 1,852 rows --
         [('Kept', 1213), ('Broken', 362), ('Partial', 277)]
```

Sanity checks these numbers pass:
- **400 historical customer versions / 8,000 customers = 5.0%** — exactly
  matches the Phase 4 relocation injection rate.
- **494 / 49,967 = 0.99%** payment duplicate rate — matches Phase 5's
  measured ~0.99% duplicate injection almost exactly, and the dedup
  removed *precisely* that many, no more, no less.
- **0 orphaned reversals** — every `original_payment_id` a reversal
  points to resolves to a real payment; referential integrity holds
  end-to-end from generator through Bronze through Silver.
- **1,213 / 1,852 = 65.5% PTP "Kept" rate** — matches the generator's
  `PTP_KEEP_PROB = 0.65` target closely.

---

## 8. Design Rationale

**Why prove this with DuckDB instead of just writing the SQL and
asserting it's correct:** identical justification to Phase 5's
`validate.py` and Phase 6's `validate_registry_local.py` — this project's
throughline is "trust nothing that hasn't been measured" (Phase 1's own
stated root cause for why the platform is needed at all). Section 7's
numbers aren't just plausible, they're independently checkable against
Phase 5's own injection-rate report.

**Why three merge patterns instead of a single MERGE template used
everywhere:** Section 2 — using the same tool for attribute-history
entities, lifecycle-flag entities, and fact/event entities would either
under-serve the ones that need real SCD2 or add pointless complexity to
the ones that don't.

**Common interview questions for this phase:**
- *"How would you handle it if your source systems used different
  customer IDs?"* → Section 3, with a runnable proof, not just a
  description of the algorithm.
- *"Walk me through what happens to a duplicate payment event."* →
  Section 4 — lands in Bronze twice (by design, Phase 6), Silver's
  `ROW_NUMBER()`/`_ingestion_ts DESC` picks one winner.
- *"How do you compute day-over-day bucket transitions when your source
  only sends one day at a time?"* → Section 5's honest limitation +ith
  fix (lookback window / full-history bootstrap) — a good chance to show
  you understand *why* naive per-batch window functions break, not just
  that they can.
- *"Why does `loan` use a totally different merge pattern than
  `customer`?"* → Section 2's monotonic-flags argument.

---

## Next

**Phase 8 — Gold Layer**: the Delinquency & Collections Mart — building
the four star-schema fact tables and six dimensions (Phase 3) from these
Silver tables, deriving portfolio snapshots, rolling windows, and the
first KPI calculations (PAR 30/60/90, roll rate, cure rate) — executed
for real against this same DuckDB warehouse.

Say **"continue to Phase 8"** (or flag changes to Phase 7) when ready.
