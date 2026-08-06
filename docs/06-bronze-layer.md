# Phase 6 — Bronze Layer

**Traces to:** Phase 2 (medallion principles, CDC/streaming design, schema
drift handling), Phase 4/5 (this is the formal schema contract for
exactly what the generator produces). Code: [`pyspark/bronze/`](../pyspark/bronze/).

**Scope note:** this phase defines the Bronze **schema, landing, and
governance design** — the schema registry that is the actual machine-
readable contract, plus a generic ingestion job written against it. The
Databricks-specific execution concerns (cluster sizing, job orchestration,
checkpointing at production scale) are Phase 10's job; what's here is
runnable logic, proven against the real Phase 5 dataset in this sandbox.

---

## 1. Design Principles (recap, applied)

Every Bronze table below follows the same contract, enforced by
[`schema_registry.yaml`](../pyspark/bronze/schema_registry.yaml) — **one
file that is simultaneously the documentation and the thing the ingestion
code actually reads**, so this document can't silently drift from what
the pipeline does (a very common real-world failure mode this design
specifically avoids):

- **Raw fidelity preserved** — Bronze columns are exactly what the source
  sends, plus a fixed set of audit columns. No business logic, renaming,
  or type coercion beyond what's declared in the registry.
- **Append-only landing, per source, per day** — matches exactly how
  Phase 5's generator wrote output (`raw_<table>/dt=YYYY-MM-DD/*.csv`),
  which in turn matches how ADF/Event Hubs will actually land files
  (Phase 2 Section 3).
- **Schema drift is detected, not absorbed** — every table declares
  whether new columns auto-merge (`allow_additive_drift`) and any known
  renames; anything else quarantines the batch instead of silently
  corrupting Silver.

---

## 2. Audit / Metadata Columns (added to every Bronze table)

| Column | Type | Purpose |
|---|---|---|
| `_batch_id` | `STRING` | UUID per ingestion run — ties every row back to one job execution |
| `_ingestion_ts` | `TIMESTAMP` | Wall-clock time Bronze wrote the row |
| `_source_file` | `STRING` | Exact file path ingested (audit/debug trail) |
| `_ingestion_date` | `STRING` | Partition column — the day this file was *landed*, not necessarily the day the business event happened (see `raw_payments` late-arrival note, Section 4) |
| `_is_quarantined` | `BOOLEAN` | True if this row failed schema-drift or corrupt-record checks |
| `_schema_drift_classification` | `STRING` | `none` / `additive` / `breaking` — set once per batch |

---

## 3. Per-Source Schema Summary

Full column-level types live in `schema_registry.yaml`; this table is the
navigable index. **File format**, **partition column**, **natural key**,
**CDC strategy**, and **retention** are the columns most worth scanning —
they're the actual design decisions.

| Bronze table | Source system | Format | Partition col | Natural key | CDC strategy | Retention |
|---|---|---|---|---|---|---|
| `raw_crm` | CRM | CSV | `source_updated_at` | `customer_id` | upsert | 7 yr (2,555d) |
| `raw_collectors_daily` | Collections Platform | CSV | `source_updated_at` | `collector_id` | upsert | 3 yr |
| `raw_servicing_applications` | Risk Engine | CSV | `application_date` | `application_id` | append-only | 7 yr |
| `raw_servicing_loans` | Loan Servicing | CSV | `origination_date` | `loan_id` | upsert | 7 yr |
| `raw_servicing_daily_status` | Loan Servicing | CSV | `snapshot_date` | `loan_id`+`snapshot_date` | append-only | 7 yr |
| `raw_servicing_loan_events` | Loan Servicing | CSV | `event_date` | `loan_id`+`event_type`+`event_date` | append-only | 7 yr |
| `raw_servicing_loan_applicant_bridge` | Loan Servicing | CSV | *(full snapshot)* | `loan_id`+`customer_id` | full-snapshot overwrite | 1 yr |
| `raw_payments` | Payment System | CSV | `ingestion_date` | `payment_id` | upsert | 7 yr |
| `raw_call_center` | Call Center | JSON (streaming) | `contact_date` | `contact_id` | append-only | 3 yr |
| `raw_collections` | Collections Platform | JSON (streaming) | `contact_date` | `contact_id` | append-only | 3 yr |
| `raw_collections_ptp` | Collections Platform | JSON (streaming) | `ptp_created_date` | `ptp_id` | upsert | 3 yr |
| `raw_bureau` | Credit Bureau | CSV | `source_updated_at` | `customer_id`+`file_date` | append-only | 3 yr |
| `raw_risk_scores` | Risk Engine | CSV | `file_date` | `loan_id`+`file_date` | append-only | 3 yr |

**Why 7-year retention on customer/loan/payment tables specifically:**
mirrors GLBA/general banking-records-retention norms (Phase 1 NFR
Regulatory Compliance) — these are exactly the tables an auditor or
examiner could plausibly request years later. Contact/bureau/risk tables
get 3 years, reflecting their role as supporting/derived signal rather
than the system-of-record transaction itself. The bridge table gets 1
year because only the *current* joint-applicant relationship matters
operationally; historical bridge state isn't a regulatory requirement
here (documented assumption, revisit if that changes).

---

## 4. Landing Strategy Notes Worth Calling Out

- **`raw_payments` partitions by `ingestion_date`, not `payment_date`.**
  This is deliberate, not an oversight: Bronze partitioning should reflect
  *when the data arrived* (so a late-arriving payment lands in the
  partition matching the day the file showed up), while `effective_date`
  (the true business date) is preserved as a normal column and is what
  Phase 7's Silver merge actually keys its CDC logic on. Partitioning by
  business date instead would mean late-arriving corrections silently
  rewrite old partitions — exactly the kind of quiet historical mutation
  Bronze is supposed to prevent (Phase 2 Principle 1).
- **`raw_call_center` and `raw_collections` land as JSON via the
  streaming path** (Event Hubs → Structured Streaming, Phase 2 Section
  4.2), not CSV batch — reflected directly in the registry's
  `landing_path_pattern` and `file_format`.
- **`raw_servicing_loan_applicant_bridge` is the one full-snapshot
  table** (no `dt=` partitioning) — it's small, low-cardinality reference
  data where "current state" is all that's operationally needed; every
  other table is append-only-per-day by design.

---

## 5. Schema Drift Handling — proven against real data, including a real bug

`pyspark/bronze/validate_registry_local.py` reads the registry and the
**actual Phase 5 output** and classifies every landed file as `none` /
`additive` / `breaking`, entirely independent of the Spark ingestion code
(this is the pandas-based, cluster-free stand-in described in Phase 5).
Current, verified result:

```
raw_servicing_daily_status   181 files  ->  none=60, additive=121
    [additive example] dt=2025-03-02: added={'loan_purpose_code'}
raw_collections_ptp          181 files  ->  none=181
raw_collections               181 files  ->  none=181
```

**A real bug this caught while building the registry:** the first version
of `schema_registry.yaml` correctly declared the `collector_id` →
`collector_ref_id` rename as a *known, resolved* drift event for
`raw_collections`, but I forgot to add the equivalent mapping for
`raw_collections_ptp` (same source event, same rename, different table).
Running the validator immediately surfaced it:

```
raw_collections_ptp   181 files  ->  breaking=100, none=81
    [breaking] dt=2025-01-01: added={'collector_id'} missing={'collector_ref_id'}
```

Fixing the registry (adding the missing `known_drift_events` entry) and
re-running turned that into `none=181` — a small, honest example of
**why this validator exists at all**: a documentation-only schema
contract could have shipped that gap silently; a contract that's actually
exercised against real data catches it immediately. This is the same
argument for automated DQ testing made more broadly in Phase 14.

**How the registry resolves a rename vs. flags a genuine break:**
`detect_schema_drift()` (identical logic in both `ingest_bronze.py` and
`validate_registry_local.py`) checks any `known_drift_events` of type
`breaking_rename` first — if the "missing" expected column and an
"added" actual column match a documented old→new pair, it's resolved to
`none` (not even `additive`, since it's a straight substitution, not
new information). Anything left over in `missing` after that check is a
**genuine breaking drift** — quarantined, never silently dropped.

---

## 6. Corrupt Record & Quarantine Handling

Phase 4/5's corrupt-record scenario (`is_corrupt_record` flag already
present on `raw_payments` and contact tables from the generator) is
handled independently of schema-level drift: `ingest_bronze.py` routes
any row where the *source itself* flagged a problem, or where the batch
was classified `breaking`, to `bronze_quarantine.<table_name>` — a
mirror-schema Delta table — rather than dropping it. Nothing is ever
silently lost; it's just not promoted to Silver until reviewed (Phase 14
DQ dashboard is where quarantine volume gets surfaced).

---

## 7. Design Rationale

**Why one YAML registry instead of thirteen hard-coded ingestion
scripts:** this is Phase 2 Principle 4 (metadata-driven ingestion) made
concrete. Adding an 8th source system, or a 14th table from an existing
source, is a registry entry, not a new script — `ingest_bronze.py` is
generic over any table the registry describes. The trade-off (a config
format needs its own validation, as Section 5's bug shows) is real and
worth naming in an interview rather than glossing over.

**Why validate the registry against real generated data instead of
trusting the YAML by inspection:** exactly the same "trust nothing you
haven't measured" principle from Phase 1 (root cause) and Phase 5
(validate.py) — and Section 5 is direct proof it catches real mistakes,
not just a hypothetical one.

**Common interview questions for this phase:**
- *"How do you decide what goes in Bronze vs. gets cleaned up before
  landing?"* → Nothing gets cleaned before Bronze (Section 1); Bronze is
  raw-plus-audit-columns only, by design.
- *"Walk me through what happens when a source renames a column."* →
  Section 5's full case study, including the real bug and fix.
- *"Why partition `raw_payments` by ingestion date instead of the
  business date?"* → Section 4 — prevents late-arriving data from
  mutating historical partitions.
- *"How would you add an 8th source system?"* → One new `schema_registry.yaml`
  entry + a landing path from ADF; no code change to `ingest_bronze.py`.

---

## Next

**Phase 7 — Silver Layer**: conformed entities (`customer`, `loan`,
`account`, `payment`, `contact`, `delinquency`), the identity-resolution/
survivorship logic that turns three different `customer_id` schemes into
one golden record, CDC merge SQL (`MERGE INTO` on natural key +
watermark, as designed in Phase 2), late-arrival reconciliation, and
SCD2 implementation for `customer`/`loan`/`collector`/`risk_band`.

Say **"continue to Phase 7"** (or flag changes to Phase 6) when ready.
