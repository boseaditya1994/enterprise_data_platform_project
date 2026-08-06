# Phase 16 — Documentation

**Traces to:** every prior phase. This phase's job is to **consolidate**
what's already been built (diagrams, deployment process, assumptions
already live in Phases 1–15) rather than duplicate it, and to add the
operational documents that don't have a natural home in any single
earlier phase: runbook, monitoring guide, disaster recovery, and
consolidated security/cost summaries. Code: [`ops/health_check.py`](../ops/health_check.py),
[`docs/glossary.md`](glossary.md).

**Why indexing instead of duplicating**: this project has applied "one
governed definition, referenced everywhere" at every layer — the Bronze
schema registry (Phase 6), the DQ rules catalog (Phase 14), KPI
definitions implemented identically in SQL/dbt/DAX (Phase 8/9/13).
Copy-pasting the architecture diagram into a fresh "Phase 16 master doc"
would violate that same principle and create exactly the kind of
drift-prone duplicate documentation Phase 1's root-cause analysis (Section
2.1) identified as the original problem. So Section 1 indexes; Sections
2–6 are genuinely new material.

---

## 1. Documentation Index

| Document type (original brief) | Where it actually lives |
|---|---|
| Architecture diagram | `docs/02-architecture.md` Section 2 (Mermaid, full Bronze→Gold flow) |
| Data flow diagram | `docs/02-architecture.md` Section 3 (source-to-target table) |
| ER diagram | `docs/03-data-modeling.md` Section 1 (Mermaid `erDiagram`) |
| Pipeline diagrams | `docs/11-adf-pipelines.md` Section 2 (pipeline structure), `docs/10-databricks.md` Section 2 (streaming sequence diagram, Phase 2 Section 4.2) |
| Deployment guide | `docs/15-deployment-cicd.md`, in full |
| Assumptions | `docs/01-requirements-business-analysis.md` Section 9, `docs/04-dataset-design.md` Section 1 (scale-profile assumptions) |
| CI/CD strategy | `docs/15-deployment-cicd.md` Sections 3–4 |
| README | [`/README.md`](../README.md) (repo root) |
| Business glossary | `docs/glossary.md` (new this phase) |
| Runbook | Section 3, below (new) |
| Monitoring guide | Section 4, below (new) |
| Disaster recovery | Section 5, below (new) |
| Security architecture | Section 6, below (consolidated synthesis, new framing) |
| Cost optimization | Section 7, below (consolidated synthesis, new framing) |

---

## 2. Reading Order for a New Team Member

Not every phase needs to be read to be productive — a suggested on-ramp
by role:

- **New Analytics Engineer**: Phase 3 (data model) → Phase 9 (dbt) →
  Phase 8 (KPI definitions) → this doc's glossary.
- **New Data Engineer**: Phase 2 (architecture) → Phase 6 (Bronze) →
  Phase 7 (Silver) → Phase 10 (Databricks) → Phase 11 (ADF).
- **New BI Developer**: Phase 3 (data model) → Phase 12 Section 5 (RBAC,
  needed to understand RLS) → Phase 13 (Power BI).
- **On-call, responding to a page**: skip straight to Section 3 below.

---

## 3. Runbook

### 3.1 First response to ANY alert: run the health check

```bash
cd ops
python3 health_check.py
```

Four sections, in order: layer row counts (does data exist where
expected), most recent DQ run summary (Phase 14), SCD2 uniqueness sanity
(Phase 7/8's boundary-bug class of problem), and a referential-integrity
spot check. **This is deliberately the same first step regardless of
what the alert says** — a consistent starting point means an on-call
engineer never has to guess which of fifteen tools to check first.

### 3.2 DQ FAIL-severity alert

1. Run `ops/health_check.py` — it prints the specific failing check(s)
   from `dq.check_results` directly.
2. Cross-reference `dq/dq_rules_catalog.yaml` for that check's `detail`
   field — most rules document *why* the check exists, which usually
   points at the right next query.
3. **Before assuming it's a new bug**, check whether the failing rows
   are `is_corrupt_record = TRUE` or otherwise match a known, documented
   scenario (Phase 14 Section 4 is the worked example of exactly this
   triage — a real FAIL that turned out to be expected test data,
   confirmed by query, not assumed).
4. If genuinely novel: check `pyspark/bronze/ingest_bronze.py`'s
   quarantine table for that source/date, and Phase 11's
   `pipeline_run_log` for whether the Bronze ingestion itself reported
   success.

### 3.3 Pipeline failure (ADF or Databricks)

1. ADF Monitoring → find the failed activity → note which stage failed
   (`pl_ingest_source_generic`'s Copy Activity vs. Databricks Notebook
   Activity — Phase 11 Section 2 — tells you immediately whether it's a
   source-connectivity issue or a code/logic issue).
2. If Copy Activity failed after exhausting its configured retries
   (`pipeline_control.max_retries`, Phase 11 Section 3): likely a
   genuine source-system outage — check the source system's own status
   page before re-triggering.
3. If the Databricks Notebook Activity failed: check the Databricks job
   run's error output directly — Phase 6/10's code raises specific,
   readable exceptions (schema drift, corrupt record thresholds) rather
   than opaque stack traces where avoidable.
4. **Backfill a single day**: re-run `pl_ingest_source_generic` via ADF's
   "Rerun from failed activity," or manually trigger with
   `run_date` set to the missed date — every ingestion job is
   idempotent on natural key (Phase 6/7's MERGE patterns), so a
   re-run of an already-succeeded day is always safe, never a duplicate risk.

### 3.4 Bureau file missing (expected, tolerated scenario)

Per Phase 4 Section 5 scenario #2 and Phase 6's registry
(`freshness_sla_minutes: 50400` — 35 days), a missing bureau file is
**not** an incident until it exceeds that window. `ops/health_check.py`
and the DQ catalog both mark this `WARN`, not `FAIL`, deliberately — do
not page anyone for a single missed bureau day.

### 3.5 Suspected data quality issue a user reported (not caught by automated checks)

1. Identify the specific KPI/number in question and its governed
   definition (`sql/gold/kpi_definitions.sql`, cross-checked against
   `dbt/models/marts/kpis/` and `powerbi/dax_measures.dax` — Phase 13
   Section 1 explains why all three should agree).
2. Reproduce the number directly against Gold, then trace backward
   through Silver to Bronze if it doesn't match expectation — the same
   layer-by-layer verification technique this project's own build phases
   used repeatedly (Phase 8 Section 3, Phase 14 Section 4).
3. If a genuine gap is found, add a check for it to
   `dq/dq_rules_catalog.yaml` before closing the investigation — every
   manually-found issue in this project (Phase 6's registry bug, Phase 8's
   SCD2 boundary bug, Phase 9's regression test) became a standing,
   automated check, not just a one-time fix.

---

## 4. Monitoring Guide

| Layer | Where to look | What "healthy" looks like |
|---|---|---|
| Bronze ingestion | ADF Monitoring (`pl_ingest_source_generic` runs) + Databricks job run history | All 13 sources' daily runs Succeeded; `dq.check_results` freshness checks passing |
| Silver/Gold build | `pl_silver_gold_orchestration` run history, dbt Cloud job UI | dbt run/test both green; Phase 9's 40 tests still passing |
| Data quality | `dq/dq_dashboard.html` (or its Snowflake-native equivalent, Phase 14 Section 5) | 0 FAIL-severity failures; WARN count roughly stable run-over-run |
| Streaming (Call Center/Collections) | Databricks Structured Streaming UI (batch duration, input rate, state size) | Micro-batch duration comfortably under the 1-minute trigger interval (Phase 10 Section 2); no growing backlog |
| Snowflake | `WAREHOUSE_LOAD_HISTORY`, `QUERY_HISTORY` system views | No sustained queueing on `WH_BI_SERVING` during business hours (Phase 12 Section 2's whole point) |
| Alerting | Teams webhook channel (`AlertOnAnyFailure`/`LogRunFailureAndAlert`, Phase 11 Section 3; Snowflake Task alert, Phase 12 Section 3) | Silence is good news — every alert path is push, not something requiring active polling |

**Escalation path**: Data Platform Engineering (Phase 1 persona) is
first responder for pipeline/infrastructure alerts; Analytics Engineering
for a KPI-definition discrepancy; Compliance is looped in directly
(not just informed after) for any complaint-flag-trend alert (Phase 13
Section 9's Call Outcomes page color logic).

---

## 5. Disaster Recovery

| Layer | Backup mechanism | RTO (Recovery Time Objective) | RPO (Recovery Point Objective) |
|---|---|---|---|
| Bronze (ADLS) | Native ADLS geo-redundant storage (GRS) + Delta's own transaction log (time travel) | < 1 hour (storage-level failover) | Near-zero (GRS is continuously replicated) |
| Silver/Gold (Delta) | Delta time travel (30-day retention on Bronze, 7-day default elsewhere — Phase 10 Section 6) enables point-in-time restore of any table without a separate backup system | Minutes (a `RESTORE TABLE ... TO TIMESTAMP AS OF` statement) | Up to the last successful write before the incident |
| Snowflake | Time Travel (1–90 days depending on edition) + Fail-safe (7 additional days, Snowflake-managed) | Minutes for Time Travel restore; hours for a Fail-safe request (requires Snowflake support) | Same as above |
| ADF/Databricks/Snowflake config | All infrastructure is code (`adf/*.json`, `databricks.yml`, `snowflake/*.sql` + migrations) — a full environment can be **redeployed from git**, not restored from a config backup | Hours (full CI/CD redeploy, Phase 15) | Zero — config drift can't happen if nothing is hand-edited outside the pipeline |
| Synthetic/source data itself | N/A for this portfolio (no real customer data); a real deployment would rely on source-system-side backups, out of this platform's scope | N/A | N/A |

**The most important DR property this architecture already has, restated
plainly**: because Bronze is deliberately never cleaned or overwritten
(Phase 2 Principle 1) and Silver/Gold are always rebuildable *from*
Bronze (every Silver/Gold build in this project — Phase 7, 8, 9 — is a
full, deterministic transformation of Bronze data), the actual disaster
scenario that matters most is **Bronze data loss**, not Silver/Gold
corruption. A bad Silver/Gold deploy is a redeploy-from-git (Phase 15)
plus a rebuild-from-Bronze away from full recovery; genuine Bronze loss
is the only scenario requiring an actual data restore rather than a
recompute.

---

## 6. Security Architecture (consolidated)

Pulling together decisions made across five earlier phases into one
summary, each pointing back to where it was actually designed:

- **Network isolation**: Private Link/Private Endpoint for
  ADLS/Databricks/Snowflake (Phase 2 Section 7 preview — no public
  internet exposure for data-plane traffic).
- **Secrets management**: Key Vault-referenced credentials everywhere a
  linked service or connector needs one (Phase 11's `ls_control_db`,
  `ls_adls_gen2` — never a hardcoded key in pipeline JSON).
- **Federated cloud auth**: Snowflake ↔ Azure via STORAGE INTEGRATION
  (Phase 12 Section 3) — no stored Azure account key inside Snowflake at
  all.
- **Row-level access**: RBAC role hierarchy + Row Access Policies (Phase
  12 Sections 5/8), mirrored in Power BI RLS (Phase 13 Section 3) so the
  same person's access is consistent across both tools.
- **Column-level PII protection**: Masking Policies (Snowflake, Phase 12
  Section 9) and Object-Level Security (Power BI, Phase 13 Section 3) —
  a deliberately separate mechanism from row access (defense in depth,
  Phase 12 Section 7).
- **Prod deployment identity**: service principal, never a human login
  (Phase 15 `databricks.yml`'s `run_as`).
- **A documented, not hidden, gap**: Phase 12 Section 6's surrogate-key
  policy mismatch, and its actual fix as a tracked migration (Phase 15
  `V1.8`) — the honest position this document takes throughout is that a
  security architecture summary is only trustworthy if it also states
  what was wrong and how it got fixed, not just the intended end state.

---

## 7. Cost Optimization (consolidated)

- **Compute**: job clusters (not all-purpose) for every scheduled
  Databricks job (Phase 10 Section 7); four workload-isolated Snowflake
  warehouses, each auto-suspending in 60–300 seconds (Phase 12 Section
  2) — idle compute is the single largest controllable cost in this
  stack, and every compute resource in this design defaults to
  suspended/terminated.
- **Storage**: asymmetric Delta VACUUM retention (30 days Bronze, 7 days
  Silver/Gold — Phase 10 Section 6) balances the reprocessing-safety
  value of Bronze history against not paying to retain Silver/Gold file
  versions nobody will time-travel to.
- **Query efficiency**: clustering/Z-order + Search Optimization Service
  (Phase 10 Section 6, Phase 12 Section 4) reduce bytes scanned per
  query — directly reduces both Databricks DBU cost and Snowflake credit
  consumption for the identical query pattern.
- **Materialization discipline**: only the two highest-traffic KPI
  queries are materialized views (Phase 12 Section 4) — materializing
  everything would trade compute cost for storage+maintenance cost
  without the traffic to justify it.
- **CI cost containment**: ephemeral, auto-torn-down PR-scoped Snowflake
  schemas (Phase 15 Section 3) — CI runs never accumulate orphaned
  storage cost across many PRs over time.
- **The single highest-leverage lever, stated plainly**: none of the
  above matters as much as the storage/compute separation decision made
  all the way back in Phase 2 — every other cost optimization in this
  list is a refinement within a workload; that original architectural
  choice is what makes workloads separable (and therefore
  cost-attributable and independently scalable) in the first place.

---

## Next

**Phase 17 — Resume & Interview Preparation**: turning this entire
17-phase build into resume bullets, a LinkedIn summary, STAR stories,
elevator pitch, and a 5-minute architecture walkthrough script.

Say **"continue to Phase 17"** (or flag changes to Phase 16) when ready
— this is the final phase.
