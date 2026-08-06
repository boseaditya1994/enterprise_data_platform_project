# Phase 14 — Testing & Data Quality

**Traces to:** Phase 6 (Bronze quarantine/schema-drift), Phase 9 (40 dbt
tests), Phase 10 Section 5 (`pyspark/dq/dq_framework.py`'s check
functions), Phase 12 (Snowflake `QUARANTINE` schema). This phase
**formalizes and executes** the enterprise DQ catalog those pieces were
each building toward. Code: [`dq/`](../dq/).

**This is a real, executed run** — `dq/run_dq_checks_duckdb.py` against
the same warehouse every prior phase built and validated, producing a
genuine result set (Section 3), including a **real, previously-unknown
FAIL** the check suite caught (Section 4) — not a clean run staged for
the writeup.

---

## 1. The DQ Rules Catalog — Metadata-Driven, Same Pattern as Every Prior Phase

`dq/dq_rules_catalog.yaml` follows the identical principle established by
Phase 6's schema registry and Phase 11's `pipeline_control`: **rules are
data, not code.** Adding a check to an existing table, or covering a new
table entirely, is a YAML edit — `run_dq_checks_duckdb.py` interprets the
catalog generically rather than having one hard-coded check function per
table.

**Check types covered** (the original brief's full enterprise DQ list,
each with a real implementation): duplicate detection, balance
reconciliation, referential integrity, freshness, completeness, null
thresholds, business rule validation, payment amount validation
(negative-value check), negative balance detection, outlier detection
(IQR method), accepted-values validation, and row-count reconciliation.

**Three severity levels**, applied deliberately unevenly across rules —
not everything is `FAIL`:
- **FAIL** — blocks Silver→Gold promotion, pages on-call. Used for
  structural integrity (uniqueness on a natural key, referential
  integrity, negative balances that shouldn't exist).
- **WARN** — logged, visible on the dashboard, doesn't block. Used where
  the "violation" is an *expected, injected* scenario — e.g. Bronze
  payment duplicates are WARN, not FAIL, because Phase 4/5 deliberately
  injects them and Bronze's whole job is to preserve what landed (Phase
  6 Section 1), not reject it. Silver is where duplicates actually get
  resolved.
- **INFO** — never blocks, reporting only (outlier counts, a
  balance-reconciliation check with no independent GL feed to check
  against in this portfolio — the production hook is documented rather
  than faked).

---

## 2. Quarantine Architecture (recap — already built, not rebuilt here)

This phase doesn't introduce a new quarantine mechanism — it formalizes
and exercises the ones already built:
- **Bronze quarantine** (`pyspark/bronze/ingest_bronze.py`, Phase 6) —
  schema-drift and corrupt-record routing, proven against real data in
  Phase 6.
- **Snowflake `QUARANTINE` schema** (Phase 12) — the serving-layer
  mirror, plus the row-access-policy home for the collector-scoping
  mapping table.
- **dbt tests** (Phase 9) — 40 tests, including the regression guard that
  turned Phase 8's payment-join-loss investigation into a standing check.

This phase's `dq.check_results` table is the **cross-layer** record all
three of those write into conceptually — one place to see Bronze,
Silver, and Gold check outcomes together, which none of the earlier,
layer-specific mechanisms alone provide.

---

## 3. Actual Results — 35 Checks, 33 Passed, 1 Real FAIL, 1 Expected WARN

```
✅ [PASS] bronze.raw_payments          completeness__payment_id           0.000% null
✅ [PASS] bronze.raw_payments          completeness__loan_id              0.000% null
🟡 [WARN] bronze.raw_payments          uniqueness__payment_id             494 duplicate key(s)
🔴 [FAIL] bronze.raw_payments          negative_value__payment_amount     72 row(s) violating: payment_amount < 0 AND NOT is_reversal_flag
✅ [PASS] silver.customer              uniqueness__customer_id            0 duplicate key(s)
✅ [PASS] silver.payment               referential_integrity__reversal_original_payment_exists  0 orphaned
✅ [PASS] silver.delinquency           outlier_iqr__outstanding_balance   97,206 outlier(s) outside [-59,484.86, 106,016.42]
✅ [PASS] gold.delinquency_fact        row_count_reconciliation__vs_silver.delinquency  diff=0.00%
✅ [PASS] gold.payment_fact            row_count_reconciliation__vs_silver.payment      diff=1.48% (tolerance 3.0%)
... (35 total)

Summary: 35 checks run
  Passed:                 33
  FAIL-severity failures:  1  (would block Silver->Gold promotion)
  WARN-severity failures:  1  (logged, does not block)
```

Full output in [`dq/run_dq_checks_duckdb.py`](../dq/run_dq_checks_duckdb.py)'s
run log; static dashboard rendered to `dq/dq_dashboard.html`
([`generate_dq_dashboard.py`](../dq/generate_dq_dashboard.py)).

**A few results worth reading closely, not just skimming green:**
- **`silver.delinquency` outlier check: 97,206 outliers flagged, marked
  PASS.** This looks alarming until you read Section 1's design: outlier
  detection is deliberately `INFO`-only (`passed=True` always), because
  an unusual `outstanding_balance` is review-worthy, not automatically
  wrong — a legitimately large loan balance shouldn't be rejected by a
  statistical heuristic. 97,206 / 1,509,105 ≈ 6.4% is a real number worth
  a strategy analyst's attention (Phase 1 persona), not a pipeline
  defect.
- **`gold.payment_fact` row-count reconciliation: PASS at 1.48% loss,
  tolerance 3.0%.** This is the exact same number Phase 8 investigated
  by hand and Phase 9 turned into a dbt regression test — now it's *also*
  checked here, a third independent enforcement of the same known,
  understood gap. Three layers catching the identical thing isn't
  redundant paranoia; it's what "defense in depth" concretely looks like
  across a real pipeline (Bronze quarantine → dbt test → this DQ suite).

---

## 4. The Real FAIL — Investigated, Not Just Reported

`bronze.raw_payments negative_value__payment_amount`: **72 rows** have a
negative `payment_amount` on a row that isn't flagged as a reversal.
Investigated immediately, same discipline as every prior phase's
findings:

```sql
SELECT is_corrupt_record, COUNT(*) FROM bronze.raw_payments
WHERE payment_amount < 0 AND NOT is_reversal_flag GROUP BY 1;
-- (True, 72)
```

**All 72, exactly, have `is_corrupt_record = TRUE`.** This is Phase 4/5's
scenario #13 (corrupt records) — `messiness.inject_corrupt_records()`
deliberately negates `payment_amount` on a small sample of non-reversal
rows to simulate a real upstream extraction glitch. **The check is
working exactly as designed**: Bronze's job (Phase 6 Section 1) is to
preserve raw fidelity and flag problems, never to silently clean data —
this `FAIL` is the DQ framework correctly identifying rows that
`ingest_bronze.py`'s corrupt-record routing (Phase 6 Section 6) should
quarantine before Silver ever sees them, not a bug in the pipeline.

**Why this is still reported as `FAIL` and not quietly reclassified to
`WARN` now that the cause is known:** the severity describes what the
*condition* requires (a negative amount on a non-reversal row should
never reach Silver un-quarantined), not what caused it this one time.
A future, genuinely unexpected source of negative payment amounts should
trip the identical alert — weakening the check because *this instance*
turned out to be intentional test data would defeat its purpose for the
next, real occurrence.

---

## 5. DQ Dashboard

`dq/dq_dashboard.html` — a real, generated static HTML report (not a
mockup) rendering `dq.check_results`: summary cards (total/passed/FAIL/
WARN counts) plus a full sortable-by-eye table of every check, its
table, severity, and detail message. This is a lightweight stand-in for
what a production DQ dashboard would be — a Databricks SQL dashboard or
a dedicated Power BI page (Phase 13's model already has the star schema
this would sit alongside) reading `dq.check_results` continuously rather
than being regenerated by a script. The mechanism (query a results table,
render pass/fail/warn) is identical either way; only the rendering layer
would change in production.

---

## 6. Design Rationale

**Why three severity levels instead of a binary pass/fail:** a DQ
framework that treats an *expected, documented* scenario (Bronze
duplicates, Phase 4/5 scenario #5) identically to a genuine structural
break (an orphaned foreign key) either pages on-call constantly for
non-issues (alert fatigue → real alerts get ignored) or under-reacts to
real problems by being tuned too loose. Three tiers, applied
deliberately per rule rather than uniformly, is what makes the FAIL in
Section 4 meaningful — it's rare enough in this run's output to actually
notice and investigate.

**Why keep investigating and writing up findings even when the
"bug" turns out to be intentional test data:** this project's whole
throughline (every phase from 5 onward) is measuring rather than
asserting. Section 4's FAIL could have been waved off as "oh, that's
just the corrupt-record scenario, nothing to see here" — but confirming
that with a query, and explaining *why* the severity stays FAIL anyway,
is a stronger and more honest artifact than either silently fixing the
YAML to hide it or hand-waving past it in the writeup.

**Common interview questions for this phase:**
- *"Walk me through a real DQ issue you found and how you triaged it."*
  → Section 4, in full — the investigation query, the root cause, and
  the reasoning for why the severity doesn't change even once explained.
- *"How do you avoid alert fatigue in a DQ framework?"* → Section 1's
  three-tier severity design, applied non-uniformly and justified per
  rule.
- *"Why treat outlier detection differently from a negative-balance
  check?"* → Section 3's outlier discussion — one is a hard business
  rule, the other is a statistical heuristic that needs human judgment,
  and conflating them either buries real outlier signal in a huge
  "failure" count or wrongly hard-blocks legitimately large values.
- *"How does this relate to the dbt tests you already built in Phase
  9?"* → Section 2 — layered, not redundant: Bronze quarantine, dbt
  tests, and this cross-layer suite each catch overlapping but
  differently-scoped classes of problems.

---

## Next

**Phase 15 — Deployment & CI/CD**: environment promotion strategy
(dev/test/prod), CI/CD pipeline design for dbt + PySpark + ADF changes,
and the release process tying every phase's code together into a
deployable whole.

Say **"continue to Phase 15"** (or flag changes to Phase 14) when ready.
