# Phase 10 — Databricks

**Traces to:** Phase 2 (streaming/CDC architecture), Phase 6 (Bronze
ingestion job, already built there), Phase 7 (hand-rolled Silver SQL,
translated here into PySpark/Delta-native form). Code: [`pyspark/`](../pyspark/).

**Honest scope note, stated upfront:** unlike Phases 5–9, this phase's
code is **not executed in this sandbox** — there is no Spark cluster
available here (Phase 1's stated constraint: "we don't have a live
Azure/Snowflake tenant in this environment"). Every file below is real,
syntactically-correct, idiomatic Databricks/PySpark/Delta Lake code,
reviewed for correctness against the actual logic already *proven*
working in Phases 6–9's DuckDB/dbt executions — but it should be read as
deployment-ready design, not as something with a green checkmark from
this session. Where a design choice was validated elsewhere (e.g., the
SCD2 merge logic), this document says so explicitly.

---

## 1. What's Here vs. What Was Already Built in Phase 6

Phase 6 already delivered the Bronze ingestion job
(`pyspark/bronze/ingest_bronze.py`) and its schema registry — that's not
repeated here. Phase 10 adds everything downstream and adjacent that
needs Spark specifically rather than SQL:

| File | Purpose |
|---|---|
| `pyspark/streaming/stream_call_center_collections.py` | Event Hubs → Bronze + Silver, watermarked, checkpointed (Section 2) |
| `pyspark/silver/scd2_merge_deltalake.py` | SCD2 merge via `DeltaTable.merge()` Python API — contrasts with Phase 7's raw-SQL version (Section 3) |
| `pyspark/gold/build_gold_aggregates.py` | The two Gold use cases that genuinely need PySpark, not dbt (Section 4) |
| `pyspark/dq/dq_framework.py` | Reusable DQ check library, called from Bronze ingestion and previewed fully in Phase 14 (Section 5) |
| `pyspark/optimization/optimize_and_maintain.py` | `OPTIMIZE`/`ZORDER`/`VACUUM` maintenance job (Section 6) |

---

## 2. Streaming Ingestion — Watermarking and Checkpointing in Detail

`stream_call_center_collections.py` implements the design from Phase 2
Section 4.2 as running code:

- **Watermark**: `withWatermark("event_time", "30 minutes")` — bounds how
  long Spark holds streaming state waiting for late events, using
  `event_time` (when the contact actually happened) rather than
  `ingestion_time` (when Event Hubs received it), exactly the event-time-
  vs-processing-time distinction Phase 2 specified.
- **Late events are never dropped**: the watermark only affects
  *aggregation* correctness, not Bronze landing — every event, on-time or
  late, gets written to Bronze via `foreachBatch`, with a `late_arrival`
  flag computed by comparing `event_time` to `ingestion_time` directly
  (not relying on Spark's internal watermark state, which isn't
  accessible per-row). Late rows get picked up by Silver's separate
  batch-reconciliation pass rather than forcing the live streaming
  aggregation to handle out-of-order correction.
- **Two independent `foreachBatch` sinks** (Bronze write, Silver merge)
  each get their **own checkpoint location**
  (`{CHECKPOINT_ROOT}/{table}/bronze` vs. `/silver`). This is
  deliberate: if the Silver merge job needs to be fixed and restarted
  independently of Bronze (a very common real operational need — Bronze
  landing logic rarely changes, Silver business logic does), each stream
  can be stopped/restarted without disturbing the other's committed
  offsets.
- **Idempotent restart**: Structured Streaming checkpointing guarantees
  a micro-batch that already committed won't be re-read from Event Hubs
  after a restart; the Silver `MERGE` on `contact_id` additionally
  guarantees that *even if* a batch were somehow replayed, the merge is
  a safe no-op (`whenNotMatchedInsert` only — nothing changes for a key
  that's already present). This two-layer protection (checkpoint +
  idempotent merge) is why the combination is called "effectively-once"
  rather than relying on checkpointing alone.

---

## 3. SCD2 via the DeltaTable API vs. Raw SQL — Both, Deliberately

`pyspark/silver/scd2_merge_deltalake.py` re-implements the exact same
two-pass SCD2 pattern as `sql/silver/01_customer_scd2_merge.sql` (Phase 7)
— **already proven correct** by that phase's executed DuckDB run — but
expressed via the `DeltaTable.merge()` Python API and parameterized as a
reusable function (`natural_key`, `compare_cols`, `watermark_col`)
instead of a table-specific SQL string.

**Why ship both instead of picking one:** the SQL version is what an
analyst reviewing this repo can read and verify line-by-line against
Phase 7's documented logic; the parameterized Python version is what a
data engineer would actually write for a Databricks job that needs to run
the *same* merge pattern against `customer`, `collector`, and any future
SCD2 entity without copy-pasting SQL per table. Being able to produce
both, and explain when each is the better tool, is a stronger signal than
picking one without discussing the tradeoff.

**`silver.loan` deliberately does NOT use this generic function** — same
reasoning as Phase 7 Section 2 (monotonic lifecycle flags need a
windowed full-history query, not a repeated-attribute-row merge). The
module's closing comment states this explicitly rather than silently
omitting a loan-specific wrapper.

---

## 4. Gold in PySpark — the Two Legitimate Exceptions to "dbt owns Gold"

Phase 2's architecture puts Silver→Gold in dbt (Phase 9). This notebook
exists for exactly two cases where that's the wrong call at real scale,
both implemented:

1. **`build_rolling_par_trend`**: 90-day and 365-day trailing rolling
   averages over a partitioned Delta table. At Phase 4's production
   target (billions of fact rows once `delinquency_fact` has years of
   history at "millions of loans" scale), a Spark window function over
   already-partitioned/Z-ordered Parquet outperforms the equivalent
   Snowflake correlated-window query — the crossover point is real, not
   hypothetical, and is exactly why Phase 2 kept Databricks in the stack
   at all rather than going pure-Snowflake.
2. **`build_collections_worklist`**: a wide, pre-joined, pre-ranked table
   Power BI's *operational* dashboard (Phase 13) reads directly, refreshed
   on its own tighter SLA independent of the nightly dbt DAG — the
   priority ranking logic (`ORDER BY dpd DESC, outstanding_balance DESC`)
   directly encodes the collections floor's actual stated prioritization
   need from Phase 1's Operations Manager persona.

Everything else — the 10 KPI views, the standard dims/facts — stays in
dbt, unduplicated. This notebook is the documented exception, not a
second, competing Gold implementation.

---

## 5. DQ Framework — Implementation Layer for Phase 14

`pyspark/dq/dq_framework.py` is the actual PySpark code Phase 6's
`ingest_bronze.py` and Phase 14's broader DQ design call into: reusable
check functions for completeness, uniqueness, referential integrity,
balance reconciliation, negative-value detection, and IQR-based outlier
flagging (informational, not a hard gate — an unusually large payment is
review-worthy, not automatically wrong). Every check returns a structured
`DQCheckResult` logged to `dq.check_results`, which is what Phase 14's DQ
dashboard is built on top of. Full framework design (thresholds,
quarantine-table architecture, alerting) is Phase 14's job — this is
where the checks actually execute.

---

## 6. Optimization — Z-Order Columns Chosen From This Project's Own Queries

`pyspark/optimization/optimize_and_maintain.py`'s `ZORDER_COLUMNS`
mapping isn't guessed — every entry matches the actual `WHERE`/`JOIN`
pattern already proven in Phase 8's executed KPI SQL (`gold.vw_par_by_date`
filters by `snapshot_date` first, joins to `loan_sk` second; the mapping
reflects exactly that). **VACUUM retention** is intentionally asymmetric:
Bronze gets 30 days (Bronze's entire purpose per Phase 2 Principle 1 is
being the reprocessing fallback if a downstream bug is found — vacuuming
it aggressively would defeat that), Silver/Gold get Delta's 7-day default
(time-travel/concurrent-reader safety floor, no reason to hold longer
once Bronze already preserves the raw history).

---

## 7. Job Orchestration & Cluster Configuration (preview — full detail Phase 11)

- **Job clusters, not all-purpose clusters**, for every scheduled job in
  this list — job clusters spin up for the run and terminate after,
  which is the entire cost-control mechanism between "engineering
  compute" and idle spend (Phase 1 NFR Cost).
- **Autoscaling** min/max workers per job sized to each table's actual
  data volume from Phase 5's real volumetrics (e.g., the
  `servicing_daily_status` ingestion job, at ~1.5M rows/day at demo
  scale and proportionally more at production scale, gets a wider
  autoscale range than the `raw_bureau` job, which handles tens of
  thousands of rows on a monthly cadence).
- **Photon** enabled on Gold-aggregation and optimization jobs
  specifically (compute-heavy window functions and `OPTIMIZE`/`ZORDER`
  benefit most); not necessarily worth the incremental cost on light
  Bronze-ingestion jobs that are I/O-bound, not compute-bound.
- **One job per source table** (Phase 6 design already established this)
  means a schema-drift quarantine or a transient failure on one source
  never blocks the other twelve — full dependency graph is Phase 11's
  deliverable.

---

## 8. Design Rationale

**Why be explicit that this phase's code isn't executed, when every
prior phase proved its work:** the same "trust nothing unmeasured"
principle this whole project has followed — claiming a Spark job runs
correctly without a way to prove it would be exactly the kind of
overclaiming this project's throughline argues against. The credible
claim here is narrower and true: *this logic is the same logic already
proven in Phases 6–9, re-expressed for the execution engine it's
actually designed to run on.*

**Why two checkpoint locations instead of one shared checkpoint for both
sinks:** Section 2 — independent restart/recovery for Bronze vs. Silver
sinks reading the same stream is a real operational need, and sharing a
checkpoint would couple their failure/recovery behavior unnecessarily.

**Common interview questions for this phase:**
- *"How do you guarantee exactly-once processing in a streaming
  pipeline?"* → Section 2's two-layer answer (checkpoint + idempotent
  merge), and the honest "effectively-once" framing rather than
  overclaiming true exactly-once.
- *"When would you choose PySpark over dbt for a Gold-layer table?"* →
  Section 4's two concrete, scale-justified exceptions — not "PySpark is
  more powerful," a specific crossover argument.
- *"How do you decide Z-order columns for a Delta table?"* → Section 6 —
  from actual observed query patterns, not guessed, with the paper trail
  back to Phase 8's real executed SQL.
- *"Why different VACUUM retention for Bronze vs. Silver/Gold?"* →
  Section 6's asymmetric-retention rationale tied directly to Bronze's
  architectural purpose (Phase 2 Principle 1).

---

## Next

**Phase 11 — ADF Pipelines**: Azure Data Factory pipeline design —
activities, dependencies, triggers, parameterization, retry/error
handling, and the full per-table orchestration graph this phase's jobs
slot into (including the Airflow comparison artifact from Phase 2's
tech-stack discussion).

Say **"continue to Phase 11"** (or flag changes to Phase 10) when ready.
