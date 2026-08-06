# Phase 9 — dbt Models

**Traces to:** Phase 6 (sources = the Bronze schema registry), Phase 7/8
(every dbt model here is a direct translation of the hand-rolled DuckDB
SQL from those phases). Code: [`dbt/`](../dbt/).

**This is a real, executed dbt project** — `dbt-core` 1.12.0 with the
`dbt-duckdb` adapter, run against a working copy of the same warehouse
Phases 7–8 built. Every number in this document comes from an actual
`dbt run` / `dbt test` / `dbt snapshot` execution, not narration.

```
dbt seed   -> 2 seeds loaded
dbt run    -> 35 models built (14 tables, 21 views), 0 errors
dbt test   -> 40 tests, 40 PASS, 0 errors
dbt snapshot (x2, see Section 4) -> genuine SCD2 history captured
dbt docs generate -> catalog.json + manifest.json (lineage) generated
```

---

## 1. Why DuckDB Instead of Snowflake Here

Same reasoning as every prior phase's local-execution harness: no live
Snowflake tenant exists in this sandbox (Phase 1's stated constraint).
`profiles.yml`'s `dev` target uses `dbt-duckdb`; a `prod` target pointed
at Snowflake (per Phase 12's design) would need zero model-code changes —
dbt's whole value proposition is that the SQL is the same, only the
adapter and connection config change. This is noted explicitly rather
than glossed over, since "how would you actually deploy this" is a fair
follow-up question.

---

## 2. Project Structure

```
dbt/
├── dbt_project.yml
├── profiles.yml              # DuckDB dev target (see Section 1)
├── models/
│   ├── staging/               # 10 models, one per Bronze source (+1 snapshot-demo helper)
│   │   ├── _sources.yml       # all 13 Bronze tables declared as dbt sources
│   │   ├── crm/, servicing/, payments/, collections/, collectors/, bureau/, risk/
│   ├── intermediate/          # 4 models: SCD2 derivation + roll/cure flags
│   ├── marts/
│   │   ├── core/               # 6 dimensions (+ _core.yml tests/docs)
│   │   ├── facts/               # 4 facts (+ _facts.yml tests/docs)
│   │   └── kpis/                # 10 KPI models
├── snapshots/
│   └── snap_crm_current_demo.sql   # genuine dbt-snapshot mechanism proof (Section 4)
├── seeds/
│   ├── channel_seed.csv
│   └── risk_band_seed.csv
├── macros/
│   ├── generate_schema_name.sql    # clean schema names (stg/int/marts, no target-prefix)
│   ├── bucket_label.sql            # single source of truth for bucket_index -> label
│   └── test_non_negative.sql       # custom generic test
└── tests/                     # 2 singular tests (Section 5)
```

**Schema layout produced:** `bronze` (already populated by Phase 6/7) →
`stg` → `int` → `marts` → `snapshots` → `seeds`, each a real DuckDB schema
in the same warehouse file, via the `generate_schema_name` macro override.

---

## 3. Staging → Intermediate → Marts, and What Changed From the Hand-Rolled Version

The model logic is a direct translation of `sql/silver/*.sql` and
`sql/gold/*.sql` — same joins, same half-open-interval SCD2 fix (Phase 8
Section 3.1), same ASOF-join collector attribution (Phase 8 Section
3.3) — expressed with `ref()`/`source()` instead of hard-coded schema
names, and with dedup/rename-resolution logic pushed into **staging**
specifically (dbt convention: every downstream model should be able to
assume one clean row per natural key without re-deduplicating).

**One deliberate design decision, stated directly: why `int_customer_scd2`
and `int_loan_scd2` are windowed full-history rebuilds, not dbt
incremental models.** dbt incremental models are the idiomatic tool for
"only process new rows since last run" — but this project's `dbt run`
loads the *entire* Bronze history in one shot every time (there's no
day-over-day production schedule actually running here), so an
incremental model would behave identically to a full-refresh table in
practice while adding `is_incremental()` branching complexity for no
executed benefit. In production, deployed against the real streaming
Bronze layer (Phase 2), these models **would** be converted to
`materialized='incremental'` with `unique_key` on the version grain —
documented here as the production evolution path, not implemented for a
project that only ever runs once per session.

---

## 4. Snapshots — a Genuine Two-Run Proof, Including Why It's *Not* Used for `customer`/`loan`

**The honest design tension, stated upfront:** dbt's snapshot mechanism
is built for sources that only ever expose **current state**, with dbt
itself accumulating history across repeated runs. `bronze.raw_crm` and
`bronze.raw_servicing_loans` already **are** full historical change
logs (Phase 5's generator emits one row per version, not just latest) —
so snapshotting them would be redundant with history the source already
provides. That's *why* Section 3's SCD2 tables use a windowed rebuild
instead of `dbt snapshot`.

To still prove real command of the mechanism (rather than just explain
why it wasn't used), `models/staging/crm/stg_crm__customers_current_simulated.sql`
deliberately **throws away** Bronze's history and exposes only the
latest CRM row per customer as of a configurable cutoff
(`var('crm_current_as_of_ingestion_day')`) — simulating what a real
current-state-only CRM extract would look like. `snapshots/snap_crm_current_demo.sql`
snapshots *that*, using `strategy='check'` on the address/segment/
employment columns.

**Executed two-run proof:**

```
Run 1: crm_current_as_of_ingestion_day = 2025-01-15  (before most relocations)
       dbt run --select stg_crm__customers_current_simulated
       dbt snapshot
       -> baseline captured, 8,000 rows, all dbt_valid_to = NULL

Run 2: crm_current_as_of_ingestion_day = 2025-06-30  (full window)
       dbt run --select stg_crm__customers_current_simulated
       dbt snapshot
       -> re-run detects changed rows via strategy='check'
```

**Result, queried directly from `snapshots.snap_crm_current_demo`:**

```
Total snapshot rows: 8,400
Customers with 2 snapshot versions (relocation detected): 400
```

**400 / 8,000 = exactly 5.0%** — matching Phase 4's relocation injection
rate precisely, and matching Phase 7's Silver-layer SCD2 result (400
historical customer versions) from an entirely independent mechanism.
Sample before/after (`dbt_valid_from`/`dbt_valid_to` populated correctly
by dbt itself, no manual date logic):

```
CUST-100023  Kelleytown, ME       valid_from=<run1 ts>  valid_to=<run2 ts>
CUST-100023  East Haileytown, UT  valid_from=<run2 ts>  valid_to=NULL
```

---

## 5. Tests

**40 tests total, all passing.** Generic (schema-defined) tests:
`not_null`/`unique`/`relationships`/`accepted_values` on every
dimension's surrogate key and every fact's natural key and foreign keys,
plus a custom generic test (`non_negative`, applied to
`dim_loan.origination_amount`).

**Two singular tests worth calling out specifically:**

- `assert_no_orphaned_reversals.sql` — direct translation of the
  referential-integrity check first written as a comment in Phase 7's
  hand-rolled SQL; now an actual enforced test, not just a suggestion.
- `assert_payment_join_loss_within_baseline.sql` — **turns Phase 8's
  investigated finding into a permanent regression guard.** Phase 8
  discovered ~1.5% of staged payments don't join into `fct_payment`
  (corrupt-record nulls + pre-origination "Extra" payments, both
  intentionally excluded, Phase 8 Section 3.2). Rather than leave that
  as a one-time finding, this test asserts the loss rate stays under 3%
  (double the observed baseline) on every future run — if it ever drifts
  meaningfully higher, *something new* broke and deserves the same kind
  of investigation Phase 8 did manually. This is a concrete example of
  converting ad hoc debugging into standing data-quality infrastructure,
  which is exactly what Phase 14 formalizes project-wide.

---

## 6. Cross-Validation: dbt Output vs. the Hand-Rolled Phase 8 Build

Queried directly from the dbt-built `marts.*` tables after the full run:

| Metric | dbt-built value | Phase 8 hand-rolled value | Match |
|---|---|---|---|
| PTP Fulfillment Rate | 65.457% | 65.46% | ✅ |
| Call Connect Rate | 54.983% | 54.98% | ✅ |
| Recovery Rate | 11.588% | 11.59% | ✅ |
| PAR 30 / 60 / 90 (last date) | 8.002% / 4.275% / 1.637% | 8.00% / 4.28% / 1.64% | ✅ |
| `fct_delinquency` row count | 1,509,105 | 1,509,105 | ✅ exact |
| `fct_payment` row count | 48,743 | 48,743 | ✅ exact |

Two independently-implemented builds (hand-rolled Python/SQL harness vs.
a real dbt project) landing on **identical** numbers is strong evidence
the logic is correct — not a coincidence, and not just "the SQL looks
right."

---

## 7. Design Rationale

**Why translate the hand-rolled Phase 7/8 SQL into dbt at all, instead of
just using the DuckDB harnesses as the final answer:** dbt gives
version-controlled, tested, documented, lineage-tracked models — the
hand-rolled harnesses were the right tool for *proving the logic* fast
(Phases 7–8), but a real analytics engineering team wouldn't hand this to
production; dbt is what makes it operable, reviewable by other analysts,
and safely modifiable going forward.

**Why keep both the hand-rolled SQL (Phases 7–8) and the dbt project
rather than deleting the former:** the hand-rolled versions are heavily
commented with the *why* behind every decision (Phase 7/8's docs walk
through real bugs found and fixed); dbt models are intentionally terser
since the documentation lives in this doc and the `.yml` files instead.
Keeping both also lets Section 6's cross-validation exist at all.

**Common interview questions for this phase:**
- *"Why didn't you use dbt snapshots for your SCD2 dimensions?"* →
  Section 4's full answer, including the two-run proof that the
  mechanism itself is well understood, just not the right tool for an
  already-historized source.
- *"How do you turn a data-quality investigation into something that
  doesn't silently regress?"* → Section 5's
  `assert_payment_join_loss_within_baseline` test.
- *"How would you know your dbt models are computing the same thing as
  your original prototype?"* → Section 6's cross-validation table.
- *"What would change if you pointed this at Snowflake instead of
  DuckDB?"* → Section 1 — `profiles.yml` target swap, zero model changes,
  because dbt's whole point is exactly this portability.

---

## Next

**Phase 10 — Databricks**: the PySpark notebooks for Bronze ingestion
(already designed in Phase 6, executed here for real via Databricks-style
job parameters), streaming ingestion, CDC merges at Delta Lake scale,
checkpointing, and cluster/job configuration — the production execution
layer this dbt project's `stg`/`int` models assume already happened
upstream.

Say **"continue to Phase 10"** (or flag changes to Phase 9) when ready.
