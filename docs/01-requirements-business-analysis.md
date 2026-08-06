# Phase 1 — Requirements & Business Analysis

**Project:** Loan Delinquency & Collections Command Center
**Role framing:** as if chartered by a Fortune 500 bank's Collections & Recovery division, sponsored jointly by the Chief Risk Officer (CRO) and Chief Data & Analytics Officer (CDAO).

---

## 1. Executive Summary

Collections is one of the highest-leverage functions in consumer/commercial
banking: a 1–2 point improvement in cure rate or a few days' reduction in
average days-to-contact can be worth tens of millions of dollars a year in
a large portfolio, while getting it wrong drives charge-offs, regulatory
scrutiny (UDAAP/FDCPA complaints), and customer attrition.

Today that function is data-starved by fragmentation, not by lack of data.
Loan servicing, payments, CRM, the collections platform, the call center,
credit bureau feeds, and the risk engine each hold a piece of the truth,
refresh on different cadences, and use different keys and definitions for
the same customer or loan. Collections managers currently stitch together
spreadsheets and platform-native reports that disagree with each other,
which erodes trust and slows decisions.

This project builds a governed, medallion-architecture analytics platform
(Bronze → Silver → Gold → Semantic/KPI → Power BI) that gives collections
managers, strategy analysts, and executives one reconciled view of
portfolio risk, collector productivity, and recovery performance — refreshed
daily (with a streaming path for near-real-time delinquency-bucket
transitions) and built to scale to millions of loans.

---

## 2. Business Problem (detailed)

### 2.1 Symptoms observed in the business
- Collections managers cannot rank accounts by "likelihood to cure vs.
  likelihood to roll" because risk scores (Risk Engine), contact history
  (CRM/Call Center), and payment behavior (Payments/Servicing) live in
  separate systems with no common daily-refreshed join.
- Roll-rate and cure-rate numbers reported by the collections platform,
  finance, and risk teams **don't match**, because each computes "days
  past due" and bucket boundaries slightly differently and on different
  data cuts.
- Collector productivity is measured by call volume in the dialer tool,
  not by promises-to-pay obtained or dollars recovered — this produces
  perverse incentives (quantity over quality).
- Channel effectiveness (SMS vs. IVR vs. live agent vs. letter) is not
  measured at all; channel selection is based on tradition, not data.
- Executives get a lagging, manually-assembled monthly deck instead of a
  live dashboard, so intervention (e.g., re-staffing collectors toward a
  cohort about to roll to 60+ DPD) happens too late to matter.
- Data quality issues (duplicate payment events, late-arriving bureau
  files, reversed/returned payments, corrected servicing records) are
  currently "solved" by ad hoc analyst judgment calls that aren't
  documented or repeatable.

### 2.2 Root cause
No conformed, governed data layer exists between the seven operational
systems and the people who need to make prioritization decisions. Each
report is effectively a one-off ETL job with its own business logic.

### 2.3 Cost of inaction
- Continued disagreement between Risk, Finance, and Collections on
  portfolio health numbers (credibility/audit risk).
- Missed opportunity to reduce roll-to-60/90 rates through earlier,
  better-targeted contact.
- Inefficient collector staffing and channel spend.
- Slower response to macro shocks (rate changes, unemployment spikes,
  natural disasters) that shift portfolio risk quickly.

---

## 3. Domain Primer (context needed before requirements make sense)

A brief shared vocabulary, since later phases assume it:

| Term | Definition |
|---|---|
| **DPD** | Days Past Due — days since the missed payment due date. |
| **Delinquency bucket** | Standard banking buckets: Current, 1–29 DPD, 30–59 DPD (PAR 30), 60–89 DPD (PAR 60), 90+ DPD (PAR 90), Charge-off. |
| **Roll rate** | % of accounts that move from one bucket to a worse bucket (e.g., 30→60) in a period. |
| **Cure rate** | % of delinquent accounts that return to Current status. |
| **PAR (Portfolio At Risk)** | % of total outstanding balance that is in a given delinquency bucket or worse. |
| **Promise to Pay (PTP)** | A commitment obtained from a customer to pay by a specific date; PTP *fulfillment rate* is a core collector KPI. |
| **Charge-off** | Balance written off as a loss after a defined delinquency threshold (policy-driven, typically 120–180 DPD depending on product). |
| **Recovery** | Cash collected on a charged-off or written-down balance, often post-settlement or via a recovery agency. |
| **Right-party contact (RPC)** | A call/SMS/etc. that reaches the actual borrower (not voicemail, wrong number, or a third party). |

---

## 4. Stakeholders & Personas

| Persona | Role | What they need from this platform | Primary artifact |
|---|---|---|---|
| **VP, Collections & Recovery** (Executive sponsor) | Owns portfolio recovery performance | Real-time portfolio health, roll/cure trend vs. plan, recovery $ vs. target | Executive Summary dashboard page |
| **Collections Operations Manager** | Runs day-to-day collector floor | Prioritized worklist logic inputs, collector productivity, queue health | Collector Productivity + Portfolio Overview pages |
| **Collections Strategy Analyst** | Designs treatment strategies & segmentation | Roll-rate/cure-rate by segment, channel effectiveness, A/B test readouts | Roll Rates, Recovery, Call Outcomes pages |
| **Credit Risk Officer** | Owns portfolio risk appetite & provisioning inputs (CECL/ALLL) | PAR 30/60/90 trend, risk-band migration, early-warning signals | Risk Segmentation page |
| **Compliance / Legal (FDCPA, UDAAP, Reg B)** | Ensures fair, compliant collections practice | Contact-frequency compliance, complaint correlation, right-party-contact controls, auditability of every metric | Data lineage docs, audit trail |
| **Individual Collector** | Front-line agent | Their own PTP rate, connect rate, recovery $, ranked worklist | Collector Productivity drill-through |
| **Finance / FP&A** | Forecasts charge-offs & recovery for the P&L | Recovery rate trend, charge-off forecasting inputs | Recovery page, Gold layer extracts |
| **Data Platform Engineering (us)** | Builds & operates the platform | Reliable pipelines, DQ SLAs, cost control, lineage/observability | All of Phases 2–16 |

### 4.1 RACI (illustrative, for the platform build itself)

| Activity | Collections VP | Risk Officer | Compliance | Data Engineering | Analytics Engineering | BI/Dashboard Owner |
|---|---|---|---|---|---|---|
| Define KPI business logic | A | C | C | I | R | C |
| Approve delinquency bucket definitions | A | R | C | I | C | I |
| Source system access & data contracts | C | I | I | R/A | C | I |
| Data quality thresholds & sign-off | C | C | C | R | A | I |
| Dashboard design & sign-off | A | C | I | I | C | R |
| Regulatory review of collections metrics | I | C | A/R | I | I | I |

*(R = Responsible, A = Accountable, C = Consulted, I = Informed)*

---

## 5. Business Objectives → Requirements Traceability

| Business Objective | Translated Requirement | Where it's built |
|---|---|---|
| Reduce delinquency | Early-warning KPIs (roll-rate, risk-band migration) refreshed daily; segment-level trend | Gold KPI layer, Risk Segmentation dashboard page |
| Improve collections prioritization | Unified customer/loan/contact/risk view at daily grain (streaming for bucket transitions) | Silver conformed layer, Gold delinquency mart |
| Monitor portfolio risk | PAR 30/60/90, portfolio snapshots, historical trend | Gold: `delinquency_fact`, portfolio snapshot tables |
| Measure collector productivity | Collector-level PTP rate, connect rate, recovery $, calls-to-cure | `collector_dim`, `contact_fact`, `promise_to_pay_fact` |
| Improve recovery rates | Recovery KPI, channel effectiveness, settlement tracking | `payment_fact`, Recovery dashboard page |
| Track customer interactions | Full contact history across channels, RPC flag | `contact_fact`, `channel_dim` |
| Support operational dashboards | Daily-refreshed Power BI with drill-through to account level | Semantic/KPI layer + Power BI (Phase 13) |
| Support executive reporting | Executive Summary page, trend vs. plan, narrative-ready exports | Power BI Executive Summary page |
| Scale to millions of loans | Delta Lake + partitioning + Z-order/clustering, incremental models, Snowflake compute separation | Bronze/Silver/Gold engineering (Phases 6–12) |

---

## 6. Functional Requirements

**FR-1 Ingestion**
- FR-1.1: Ingest batch extracts (daily) from Loan Servicing, Payments, CRM, Collections Platform, Credit Bureau, Risk Engine.
- FR-1.2: Ingest near-real-time events (Call Center dispositions, Collections Platform actions) via streaming (Event Hubs) where sub-day latency materially changes prioritization decisions.
- FR-1.3: Support CDC (insert/update/delete capture) from source systems using natural business keys + source update timestamp, with soft-delete handling.
- FR-1.4: Handle late-arriving events (e.g., a payment posted with an effective date in the past) without corrupting historical snapshots.

**FR-2 Data Quality & Governance**
- FR-2.1: Every Bronze→Silver promotion must pass configurable DQ checks (completeness, referential integrity, business-rule validation); failures route to quarantine, not silently drop.
- FR-2.2: All monetary fields reconcile to source system control totals daily (balance reconciliation).
- FR-2.3: Every Gold metric must be traceable back to source records (lineage) for audit and regulatory response.

**FR-3 Modeling**
- FR-3.1: Conform customer, loan, and account identities across source systems that don't share a common key (identity resolution / survivorship rules).
- FR-3.2: Maintain full history of loan risk-band and delinquency-bucket changes (SCD Type 2) to support roll-rate and migration analysis.
- FR-3.3: Support point-in-time portfolio snapshots (as-of any historical date) for regulatory/audit reconstruction.

**FR-4 KPIs & Reporting**
- FR-4.1: Calculate PAR 30/60/90, roll rate, cure rate, recovery rate, PTP fulfillment rate, collector productivity, contact success rate, call connect rate, average days delinquent, collection efficiency — all with documented, versioned business definitions (Phase 8/KPI layer).
- FR-4.2: Provide drill-through from any aggregate KPI down to the account and event level.
- FR-4.3: Support both operational (daily, near-real-time bucket transitions) and executive (weekly/monthly trend) reporting cadences from the same governed layer.

**FR-5 Alerting & Monitoring**
- FR-5.1: Alert on pipeline failure, SLA breach, and DQ threshold breach.
- FR-5.2: Alert business users on material portfolio risk changes (e.g., PAR 30 change > X% week-over-week) — stretch goal, not MVP.

---

## 7. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Scale** | Design for millions of loans / tens of millions of payment & contact events; Gold queries must return in dashboard-acceptable time (<5s for standard Power BI page load) via pre-aggregation and Snowflake/BI-layer caching. |
| **Latency** | Batch layers refreshed daily (T-1) at minimum; streaming path for call-center/collections-action events targets <15 min end-to-end for bucket-transition-relevant signals. |
| **Availability** | Gold layer availability target 99.5% during business hours; documented RTO/RPO for disaster recovery (Phase 16). |
| **Security & Access Control** | Role-based access (a front-line collector should not see the full portfolio; an executive should not need PII drill-down); PII (SSN, DOB, account numbers) masked/tokenized outside of need-to-know layers. |
| **Regulatory Compliance** | Must support **FDCPA** (Fair Debt Collection Practices Act — contact frequency/timing rules), **UDAAP** (fair treatment, no deceptive metrics-driven pressure), **ECOA/Reg B** (no disparate treatment by protected class — risk-band and treatment logic must be auditable for fair-lending review), **GLBA** (customer financial data privacy/safeguarding), and internal model-risk governance (**SR 11-7**-style documentation) for any scoring logic touched. This is a portfolio project, so we will *document* these controls (data classification, access model, lineage, retention) rather than integrate with real regulatory infrastructure. |
| **Auditability** | Every KPI must have a documented, versioned SQL definition (no "tribal knowledge" metrics); every Gold record traceable to Bronze source. |
| **Data Retention** | Bronze: retain raw history per source-system-specific policy (documented per table in Phase 6). Silver/Gold: retain full history via SCD2 + snapshotting to support multi-year trend and audit reconstruction. |
| **Extensibility** | Adding an 8th source system or a new KPI should not require redesigning the medallion layers — metadata-driven ingestion and a documented semantic layer are required. |
| **Cost** | Favor incremental processing over full reprocessing; separate storage (ADLS/Delta) from compute (Databricks/Snowflake) so idle time doesn't burn compute cost — addressed fully in Phase 16 cost section. |

---

## 8. Scope

### In scope
- The 7 named source systems (synthetic, Faker-generated, but schema-realistic).
- Full medallion pipeline: Bronze → Silver → Gold → Semantic/KPI → Power BI.
- Batch + one streaming ingestion path (Call Center / Collections Platform events via Event Hubs).
- Star schema with the 4 named fact tables and 6 named dimension tables (extendable in Phase 3 if a gap is found).
- dbt for Silver/Gold transformation and testing; PySpark/Databricks for Bronze ingestion, streaming, and heavier transformations; Snowflake as the serving warehouse for BI.
- Full synthetic dataset generation (6–12 months, interconnected, with realistic messiness).
- DQ framework, CI/CD design, documentation, and resume/interview materials.

### Out of scope (explicitly, with rationale)
- **Real customer/production data** — synthetic only, for legal and portfolio-safety reasons.
- **Actual collections treatment/dialer software integration** — we model the *data* produced by such systems, not build the dialer.
- **Machine learning cure-probability / propensity models** — noted as a natural Phase-18-style extension, but out of scope for this build so the project stays reviewable in an interview timeframe. (We will still create the risk-band/segmentation structures that would feed such a model.)
- **Real-time (sub-second) streaming** — near-real-time (minutes) is sufficient for collections use cases; sub-second adds infrastructure complexity with no business justification here.
- **Multi-region / multi-currency** — single-region, single-currency (USD) for scope control; will be noted as an extension point in architecture docs.

---

## 9. Assumptions

1. Source systems provide (or can be simulated to provide) a natural business key and a `source_updated_at`/`event_timestamp` for CDC purposes.
2. "Daily" is an acceptable batch cadence for most KPIs; only call-center/collections-action events need near-real-time treatment.
3. Delinquency bucket definitions (30/60/90) follow standard US consumer-lending convention; commercial/mortgage-specific bucket rules are out of scope unless noted.
4. Power BI is the target BI tool (Tableau artifacts are also produced per the original spec, as a secondary/comparison deliverable, not the primary dashboard).
5. Azure + Databricks + Snowflake is an intentionally hybrid, "best of both worlds" stack chosen to be **interview-relevant** across common enterprise patterns (lakehouse + separate cloud DW), not because a real bank would necessarily run both — this trade-off is documented explicitly in Phase 2.

## 10. Constraints

- Must be buildable and explainable by one engineer in a portfolio-project timeframe — drives the "synthetic but realistic" approach rather than requiring real infrastructure procurement.
- All infrastructure-as-code/pipeline artifacts must be reviewable as *code* (JSON/SQL/Python) since we don't have a live Azure/Snowflake tenant in this environment — Phases 10–13 will produce deployable-quality artifacts with clear deployment instructions rather than a live running cluster.
- Must remain internally consistent across 17 phases — every later phase must trace back to a requirement defined here.

---

## 11. Success Metrics for the Platform (not to be confused with the business KPI catalog, which is Phase 8)

| Dimension | Metric |
|---|---|
| Data quality | ≥99% of records pass DQ checks pre-Silver; 100% of failures quarantined and logged (not dropped) |
| Freshness | Batch Gold layer refreshed by 6 AM local for prior business day; streaming signals available within 15 min |
| Trust | Zero unreconciled variance between Gold-layer balances and simulated source-system control totals |
| Usability | Every dashboard page answers a specific persona's top-3 stated question (validated against Section 4 personas) |
| Reusability | KPI definitions centralized in one semantic layer, not duplicated per report |

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Identity resolution across systems without a shared key is imperfect (real-world problem) | Duplicate/split customer views | Deterministic + rules-based matching (name+DOB+SSN-last4 style keys), documented survivorship logic, `match_confidence` column carried through (Phase 7) |
| Delinquency bucket definitions disagree across teams (mirrors the real business problem) | Undermines trust in the very platform meant to fix this | Single governed definition in dbt/semantic layer with version history; Compliance/Risk sign-off modeled in RACI |
| Late-arriving/out-of-order events corrupt point-in-time snapshots | Wrong historical PAR/roll-rate figures | Event-time processing + watermarking in streaming path; SCD2 with correct effective-dating in batch path (Phase 7) |
| Synthetic data too "clean" to be a credible interview artifact | Reviewer skepticism | Deliberately inject the messiness scenarios listed in the original brief (duplicates, reversals, schema drift, corrupt records) — Phase 5 |
| Scope creep across 17 phases | Never-finished project | Phase gating with explicit sign-off (this tracker), strict in/out-of-scope list above |

---

## 13. Design Rationale — Why a formal Requirements & Business Analysis phase

**1. Why it's needed:** Without a documented problem statement, persona set,
and requirements traceability, every downstream design choice (schema,
tech stack, KPI definitions) is unjustifiable in an interview — "why did
you build it this way?" needs an answer rooted in a business need, not
"because it's a common stack." This phase is also what separates a
portfolio *toy* from a portfolio *platform*: real banking data platforms
are requirements- and governance-driven because of regulatory exposure.

**2. Alternative approaches considered:**
- *Skip straight to architecture/code* — faster to show something running,
  but produces a project that can't survive "why" questions in an
  interview and often bakes in wrong assumptions (e.g., wrong bucket
  definitions) that are expensive to unwind later.
- *Lightweight one-paragraph problem statement only* — common in smaller
  shops; insufficient here because collections touches compliance
  (FDCPA/UDAAP/Reg B), which a senior interviewer will probe.

**3. Why this approach was selected:** A full requirements pass — problem
statement, personas/RACI, functional + non-functional requirements
(including regulatory), explicit scope, assumptions, and risk register —
mirrors how a real bank's data governance / model-risk process would
require this work to start, and gives every later phase something
concrete to trace back to.

**4. Enterprise best practices reflected here:**
- Requirements traceability matrix (Section 5) so every build artifact
  maps to a business objective — standard in regulated-industry data
  governance.
- RACI matrix to make ownership explicit before building (avoids "shadow
  IT" analytics that regulators/audit flag).
- Explicit non-functional/regulatory requirements captured *before*
  architecture, not retrofitted.
- Documented assumptions and constraints, so scope changes later can be
  evaluated against what was originally agreed.

**5. Common interview questions related to this phase (with short model answers):**
- *"How did you gather requirements for this project?"* → Walk through
  Sections 2–5: problem symptoms observed, personas, objective-to-requirement
  traceability.
- *"How do you handle competing definitions of a metric across teams?"*
  → Single governed definition in the semantic layer with sign-off,
  referencing the roll-rate/cure-rate disagreement in Section 2.1 and the
  RACI in Section 4.1.
- *"What regulatory considerations apply to a collections data platform?"*
  → FDCPA, UDAAP, ECOA/Reg B fair-lending auditability, GLBA privacy —
  Section 7.
- *"How do you know if the platform is successful?"* → Section 11 —
  separate platform-health metrics from business KPIs (Phase 8), and tie
  usability back to named personas.
- *"What would you cut if you had half the time?"* → Point to Section 8's
  out-of-scope list and explain the reasoning (e.g., ML propensity models
  cut first because they're additive, not foundational).

---

## Next

**Phase 2 — Architecture**: medallion architecture diagram, source-to-target
data flow, CDC/streaming ingestion design, and explicit tech-stack
justification (Azure + Databricks + Snowflake + dbt + Power BI) with
alternatives considered.

Say **"continue to Phase 2"** (or note any changes to this phase) when ready.
