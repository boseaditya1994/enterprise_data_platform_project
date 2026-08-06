# Phase 17 — Resume & Interview Preparation

**Traces to:** the entire project. Every claim below is drawn from something
actually built and, where possible, actually executed and measured across
Phases 1–16 — no number here is invented for effect.

---

## 1. Project Description (portfolio site / resume header)

**Loan Delinquency & Collections Command Center** — an end-to-end,
enterprise-grade data platform built to demonstrate senior data
engineering, analytics engineering, and data architecture capability.
Designed and implemented the full modern data stack — medallion
architecture on Azure Data Lake/Databricks/Delta Lake, dbt on Snowflake,
Power BI — for a simulated Fortune-500 bank's loan collections function,
including a from-scratch synthetic data generator with realistic
production messiness (schema drift, duplicates, late-arriving data,
reversals, charge-offs), a governed KPI layer, row-level security, CI/CD,
and full enterprise documentation across 17 phases.

---

## 2. Resume Bullet Points

- Designed and built an end-to-end lakehouse platform (medallion
  architecture: Bronze/Silver/Gold) processing a synthetic 10,000-loan,
  8,000-customer, 6-month banking dataset, including CDC ingestion,
  SCD Type 2 history tracking, and a governed 12-KPI semantic layer
  consumed identically across SQL, dbt, and Power BI DAX.
- Built a metadata-driven ingestion framework (13 source systems, one
  generic PySpark job + schema registry) that classifies schema drift as
  additive (auto-merge) vs. breaking (quarantine), catching and
  correcting a real schema-drift registry bug through automated
  validation rather than manual review.
- Implemented and executed (via DuckDB as a Snowflake/Databricks
  stand-in) a full Silver-layer CDC/SCD2 pipeline, diagnosing and fixing
  a production-realistic SCD2 boundary bug (`BETWEEN` vs. half-open
  interval) that was causing a 0.05% row-level fan-out in the Gold star
  schema — verified by exact row-count reconciliation against Silver.
- Built a 35-model, 40-test dbt project (staging → intermediate → marts
  → KPI layer) on the dbt-duckdb adapter, including a genuine two-run
  proof of dbt's snapshot SCD2 mechanism that independently reproduced a
  5.0% customer-relocation rate matching the source data's known
  ground truth.
- Designed and implemented Snowflake RBAC (5-role hierarchy), row access
  policies, and dynamic data masking enforcing a documented
  collector/manager/executive visibility model — mirrored identically
  into Power BI RLS reading the same mapping table, so a person's access
  is consistent across both tools.
- Built a metadata-driven enterprise Data Quality framework (35 checks
  across completeness, uniqueness, referential integrity, business rules,
  and outlier detection) that caught a real, previously-unknown data
  defect on first run, root-caused it to a specific upstream scenario,
  and converted three separate findings (a payment-join-loss rate, a
  registry gap, an RBAC key mismatch) into permanent regression tests and
  tracked migrations rather than one-off fixes.
- Designed full CI/CD (GitHub Actions across dbt/PySpark/ADF/Snowflake
  migrations, Databricks Asset Bundles, environment-gated promotion with
  required-reviewer approval) and authored the complete enterprise
  documentation suite (architecture, runbook, disaster recovery, security,
  cost optimization) for the platform.

---

## 3. LinkedIn Project Summary

> I spent the last stretch building something I'd been meaning to do for
> a while: a genuinely enterprise-shaped data platform, from a blank
> requirements doc all the way through CI/CD and interview prep — 17
> phases, one at a time, each one actually built and (wherever the tool
> allowed) actually run and verified.
>
> The domain is loan collections at a simulated bank: which customers are
> likely to cure, which are rolling toward charge-off, which collectors
> and channels are actually effective. The stack is the one most large
> banks actually run — Azure Data Lake, Databricks/PySpark/Delta Lake for
> ingestion and CDC, dbt on Snowflake for transformation, Power BI for
> the exec layer — plus a from-scratch synthetic data generator that
> deliberately injects the messy stuff real pipelines have to survive:
> schema drift, duplicate events, late-arriving payments, reversals,
> fraud flags, a mid-year team reorg.
>
> The part I'm most glad I did: wherever I could actually execute code
> instead of just writing it, I did — DuckDB standing in for Snowflake,
> a real dbt project with 40 passing tests, a real data quality suite
> that caught a genuine defect on its first run. That surfaced real bugs
> (an SCD2 date-boundary bug, a schema-registry gap, an RBAC key
> mismatch) that I fixed the way you'd fix them on a real team — root
> cause, fix, regression test — instead of a portfolio project that only
> ever shows things working.
>
> Full write-up, code, and docs in the repo. Happy to walk through any
> piece of it.

---

## 4. STAR Stories

### Story 1: The SCD2 Boundary Bug (Phase 8)
- **Situation**: Building the Gold star schema by joining Silver's SCD2
  dimensions (customer, loan) to daily fact tables on effective-date
  ranges.
- **Task**: Get `gold.delinquency_fact` to match Silver's row count
  exactly — any mismatch means the join is either dropping or
  duplicating rows.
- **Action**: First build produced 753 more rows than Silver. Rather than
  guess, I isolated it: the SCD2 rows close the old version's
  `effective_end_date` at exactly the new version's `effective_start_date`,
  and my join used inclusive `BETWEEN` on both bounds — so a day landing
  precisely on that boundary matched *both* the closing and opening
  version. Fixed by switching every SCD2 join to a half-open interval
  (`>= start AND < end`).
- **Result**: Re-ran and got an exact match — 1,509,105 rows on both
  sides, to the row. Documented the bug, root cause, and fix directly in
  the phase's docs rather than silently correcting it, since it's a
  genuinely common real-world SCD2 mistake worth being able to explain.

### Story 2: A Registry Gap Caught by Its Own Validator (Phase 6)
- **Situation**: Built a schema registry (YAML) as the single source of
  truth for Bronze ingestion, including handling a deliberate,
  documented schema-drift scenario — a column rename from `collector_id`
  to `collector_ref_id` partway through the data window.
- **Task**: Make sure the registry correctly resolves that rename for
  *every* table it affects, not just the one I was thinking about while
  writing it.
- **Action**: I'd added the rename-resolution mapping for `raw_collections`
  but forgot the identical mapping for `raw_collections_ptp` — the same
  underlying source event, a different table. Running my own validation
  script (which reads the registry and classifies every real data
  partition as none/additive/breaking drift) immediately flagged 100
  files as unresolved breaking drift.
- **Result**: Fixed the registry, re-ran, got a clean `none=181` across
  every affected file. The lesson I take from it: a documentation-only
  contract could have shipped that gap silently forever; a contract
  that's actually exercised against real data catches it on the first run.

### Story 3: Turning a Data Quality Finding Into Permanent Infrastructure (Phase 8 → 9 → 14)
- **Situation**: Investigating why ~1.5% of staged payments weren't
  landing in the Gold `payment_fact` table.
- **Task**: Determine whether this was a real defect or expected
  behavior, and make sure the answer didn't just live in my head.
- **Action**: Split the gap by root cause via a targeted query: 74 rows
  had a nulled `customer_id` — a deliberately-injected corrupt-record
  test scenario, correctly excluded — and 656 were "Extra" payments dated
  independently of their loan's actual origination date, a real (if
  minor) synthetic-data-generator limitation. Documented both causes
  explicitly rather than quietly patching the generator and invalidating
  every downstream row-count I'd already written up.
- **Result**: Converted the finding into a dbt regression test
  (`assert_payment_join_loss_within_baseline`) that fails if the loss
  rate ever drifts materially above the observed baseline, and later
  re-implemented the identical check a third time in a standalone DQ
  framework (Phase 14) — three independent layers now guarding the same
  known issue, which is what real defense-in-depth looks like rather
  than three redundant copies of the same code.

### Story 4: Identity Resolution, Proven Independently of the Main Dataset (Phase 7)
- **Situation**: My synthetic data generator used one shared customer ID
  across all source systems — a documented simplification — but a real
  bank's CRM, servicing, and bureau systems each mint their own local ID,
  and Silver's identity-resolution step needs to actually solve that
  matching problem.
- **Task**: Prove the matching algorithm works without needing to rebuild
  the whole generator around it.
- **Action**: Built a standalone demo with a deliberately fragmented
  13-record, 3-source, 6-person sample — including intentional traps: two
  different real people sharing a last name (must stay separate) and a
  record with no SSN on file (needs a fallback match path). Implemented
  blocking on SSN+DOB, fuzzy name scoring, and Union-Find clustering.
- **Result**: Correctly resolved to exactly 6 golden IDs, correctly kept
  the two different Kims apart, and correctly matched the no-SSN record
  via the fallback path — a small, fast, fully independent proof that the
  design works, without the cost of reworking Phase 5's generator.

---

## 5. Business Impact Narrative

Framed the way a hiring manager actually cares about — in terms of the
Phase 1 problem, not the tech stack:

> Collections is one of the highest-leverage functions in a bank — a
> couple points of cure-rate improvement is worth millions annually in a
> large portfolio — but it's routinely data-starved by fragmentation, not
> by lack of data. This platform's core value is replacing "collections
> managers can't rank accounts by cure-likelihood because risk, contact
> history, and payment behavior live in five different systems with no
> shared daily view" with one governed, reconciled portfolio view. The
> collector-productivity design specifically makes visible what raw call
> volume hides: which collectors and channels actually recover money, not
> just which make the most calls — directly targeting the root-cause
> problem identified in Phase 1's requirements analysis.

---

## 6. Architecture Explanation (concise, ~150 words)

> Seven source systems — loan servicing, payments, CRM, collections
> platform, call center, credit bureau, risk engine — feed a medallion
> lakehouse on Azure. Batch sources land via Azure Data Factory; two
> streaming sources (call center, collections actions) come through Event
> Hubs with watermarked Structured Streaming. Bronze preserves raw
> fidelity with full audit columns and a metadata-driven schema registry
> that classifies drift as safe-to-merge or quarantine-worthy. Silver
> conforms identity, applies CDC merges and SCD2 versioning, and resolves
> deduplication. Gold is a Kimball star schema — four fact tables, six
> dimensions — built by dbt, serving a governed 12-KPI layer consumed
> identically by SQL, dbt, and Power BI. Snowflake handles BI-serving
> compute, isolated from Databricks' engineering compute for cost and
> blast-radius reasons. Every layer's design choice is justified against
> either a stated business requirement or a real, measured finding from
> actually running the pipeline.

---

## 7. Elevator Pitch (30 seconds, ~85 words)

> I built an enterprise-grade loan collections analytics platform from
> scratch — the same stack a large bank actually runs: Databricks and
> Delta Lake for ingestion, dbt on Snowflake for transformation, Power BI
> for the executive layer. What makes it different from a typical
> portfolio project is that I actually executed almost everything instead
> of just writing SQL that looks right — which caught real bugs, like an
> SCD2 date-boundary issue and a schema-registry gap, that I diagnosed,
> fixed, and turned into permanent regression tests. Happy to walk
> through any piece of it.

---

## 8. Two-Minute Interview Explanation (~280 words)

> It's called the Loan Delinquency & Collections Command Center — a
> full-stack data platform for a simulated bank's collections function.
> The business problem is real: collections teams can't prioritize
> accounts well because customer, payment, risk, and contact data live in
> disconnected systems, so nobody trusts a shared number for something as
> basic as "what's our roll rate this month."
>
> I built the whole stack top to bottom, in phases, the way a real team
> would sequence it: requirements and architecture first, then a
> from-scratch synthetic data generator — not just random data, but a
> loan-lifecycle state machine that deliberately injects the messy stuff
> real pipelines survive: schema drift, duplicate events, late-arriving
> payments, a mid-year collector reorg. Then Bronze ingestion with a
> metadata-driven schema registry, Silver with CDC merges and SCD2
> history, a dbt project on top of that — 35 models, 40 tests, all
> actually passing — and a Gold star schema serving twelve governed KPIs.
>
> The part I'm proudest of is that wherever I could actually run
> something instead of just writing it, I did. I used DuckDB as a stand-in
> for Snowflake and Databricks so I could execute real MERGE and SCD2
> logic against real data, not just describe it. That's how I found and
> fixed a genuine SCD2 boundary bug — an off-by-one on date ranges that
> was silently duplicating rows — verified by getting an exact row-count
> match afterward, not just "looks right."
>
> On top of that: Snowflake RBAC and row-level security mirrored into
> Power BI so access is consistent across tools, a data quality framework
> that caught a real defect on its first run, and full CI/CD with
> environment-gated promotion. It's meant to hold up to the kind of
> "why did you do it this way" questions a senior engineer should expect
> — every design decision in the repo has a documented reason and, where
> possible, a measured result behind it.

---

## 9. Five-Minute Architecture Walkthrough (script)

**[0:00–0:45] The problem and why it's hard**
> Start with Phase 1's root cause, not the tech: "Collections teams at a
> bank need to prioritize which delinquent customers to focus on, but the
> data that would tell them — payment history, risk score, contact
> history, current bucket — lives in five-plus separate systems refreshed
> on different schedules, using different keys, with no shared
> definition of something as basic as 'which bucket is this loan in.'
> That's the actual business problem this platform solves, and it shaped
> every architecture decision that followed."

**[0:45–1:45] The medallion flow**
> Walk the Phase 2 diagram left to right: "Seven source systems feed
> Bronze via ADF for batch, Event Hubs for the two streaming sources —
> call center and collections actions, because those are the two signals
> where minutes actually matter for next-action decisions. Bronze
> preserves raw fidelity — nothing gets cleaned here, just audit columns
> and a schema-drift check that decides whether a change is safe to
> auto-merge or needs to be quarantined for review. Silver is where
> identity gets resolved across systems, CDC merges happen, and I track
> full history with SCD Type 2 on customer and loan. Gold is a Kimball
> star schema — four facts, six dimensions — built by dbt, and that's
> where the twelve governed KPIs live, the same definitions consumed by
> SQL, dbt, and the Power BI DAX layer."

**[1:45–3:00] What makes it different from a typical portfolio build**
> "The thing I want to highlight is that I didn't just write SQL that
> looks correct — wherever the environment allowed it, I actually
> executed the pipeline. I used DuckDB as a stand-in for Snowflake and
> Databricks specifically so I could run real MERGE and window-function
> logic against real generated data, not just describe it in a doc.
> That's how I caught a genuine SCD2 boundary bug: my first Gold build
> had 753 more rows than Silver, traced it to an inclusive BETWEEN on a
> date range that double-counted the exact day a version closed and the
> next one opened, fixed it with a half-open interval, and verified an
> exact row-count match afterward. I also built a real dbt project — 35
> models, 40 tests — and ran a genuine two-run proof of dbt's snapshot
> mechanism that independently reproduced the same 5% customer-relocation
> rate my Silver-layer SCD2 logic found, through a completely different
> code path."

**[3:00–4:00] Security, quality, and operations**
> "Because this handles PII-shaped data even synthetically, I built out
> Snowflake RBAC with row access policies and dynamic masking — a
> collector sees only their own accounts, an executive gets zero raw-table
> access and sees only the governed KPI layer — and mirrored that exact
> model into Power BI's row-level security so the same person's access is
> consistent whether they're in Snowflake or the dashboard. I also built
> a metadata-driven data quality framework — 35 checks across
> completeness, referential integrity, business rules, outlier detection —
> and it actually caught a real, previously unknown issue on its first
> run: 72 rows with a negative payment amount that weren't flagged as
> reversals. I traced it back to my own synthetic corrupt-record injection
> scenario, confirmed it with a query, and kept the check at FAIL severity
> anyway, because the next time that condition fires it might not be test
> data."

**[4:00–5:00] Close**
> "Everything's backed by CI/CD — GitHub Actions for dbt, PySpark,
> ADF, and Snowflake migrations, with environment-gated promotion that
> requires human approval before anything touches test or prod — and a
> full documentation suite: runbook, disaster recovery, security
> architecture, cost optimization. The whole thing is 17 phases, and I
> can go as deep as you want into any single one — the data model, the
> streaming design, the RBAC implementation, any of the bugs I found and
> fixed along the way."

---

## Project Complete

All 17 phases delivered — requirements through resume prep — with code,
docs, and (wherever the environment allowed) real executed proof at
every layer. See [`README.md`](../README.md) and
[`docs/00-project-plan.md`](00-project-plan.md) for the full index.
