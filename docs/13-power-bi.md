# Phase 13 — Power BI

**Traces to:** Phase 12 (RBAC/masking model — this phase's RLS mirrors it
exactly), Phase 8/9 (every KPI here has the identical business definition
in SQL, dbt, and now DAX — Section 1 explains why that triple
implementation is deliberate), Phase 1 Section 4 (each of the 9 pages
answers a specific named persona's stated top question). Code:
[`powerbi/`](../powerbi/).

**Scope note (same honesty as Phases 10–12):** `.pbix` is a binary
format; there is no local Power BI Desktop in this sandbox. What's
delivered instead is real, text-based, source-controllable artifacts —
`model.tmdl` (the actual format Power BI/Tabular Editor/Fabric use to
define a semantic model as code), `dax_measures.dax` (syntactically real
DAX), and `rls_roles.dax` — plus this document's full page-by-page
design.

---

## 1. Why DAX Re-Implements KPIs Already Defined in SQL and dbt

`dax_measures.dax`'s 20+ measures are a third independent expression of
KPI logic already defined in `sql/gold/kpi_definitions.sql` (Phase 8) and
`dbt/models/marts/kpis/*.sql` (Phase 9). This is not redundant
duplication — it's what "one governed business definition, consumed
everywhere" (Phase 1's stated root-cause fix) actually requires: the
**business logic** must be identical across all three; the **expression
language** necessarily differs because SQL views, dbt models, and DAX
measures are each read by a different tool. Where DAX's semantics force a
genuinely different construction — e.g. `Contact Success Rate` uses
`TREATAS` against a real fact-to-fact relationship (`model.tmdl`'s
`fct_promise_to_pay`-`fct_contact` relationship) instead of SQL's
`EXISTS` subquery — that's called out directly in the file rather than
silently translated.

---

## 2. Composite Model: Import + DirectQuery, Deliberately Mixed

`model.tmdl` marks every table **Import** except `dim_customer` and
`fct_delinquency`, which are **DirectQuery**. This is a narrow, justified
exception, not the default:

- **Customer Drilldown (Section 10)** is the one page needing
  always-current, row-level, PII-bearing detail — an overnight Import
  refresh cache is the wrong freshness guarantee for "what does this
  specific customer's account look like right now."
- **`fct_delinquency`** is also the largest table by far (1.5M+ rows at
  demo scale, proportionally more at Phase 4's production target) — a
  real performance motivator for DirectQuery independent of the
  freshness argument, since Snowflake's clustering + Search Optimization
  Service (Phase 12 Section 4/6) make the point-lookup queries this page
  needs genuinely fast server-side.
- **Every other page** stays Import — aggregate-heavy KPI queries over a
  cached model are dramatically faster than round-tripping every
  dashboard interaction to Snowflake, and those pages don't need
  per-second freshness (Phase 1 NFR Latency: daily batch is the
  documented SLA for everything except the two streaming sources).

---

## 3. Row-Level Security — Enforced Once, at the Dimension

`rls_roles.dax` mirrors Phase 12's Snowflake role model exactly
(`Executive`, `Collections Manager`, `Collector`, `Compliance Auditor`) —
the same person's Snowflake role and Power BI role always answer "what
can they see" identically, driven by the **same** `collector_team_map`
mapping table both systems read.

**The filter is applied to `dim_collector`, not repeated on every fact
table.** Because every fact relates to `dim_collector` through a
single-direction relationship (`model.tmdl`'s relationship list), an RLS
filter on the dimension propagates automatically to
`fct_delinquency`/`fct_contact`/`fct_promise_to_pay` without needing the
same filter expression written four times — the identical "define once"
principle behind this project's base DAX measures (Section 1) and every
prior phase's config-driven patterns (Bronze registry, ADF's
`pipeline_control`, Snowflake's row access mapping table).

**Column-level PII protection is a separate mechanism from RLS**, stated
explicitly rather than conflated: Power BI RLS filters rows, not columns,
so `Compliance Auditor` (full row visibility, matching Snowflake's grant)
needs **Object-Level Security** via Tabular Editor to hide
`phone_number`/`email`/`ssn_last4` — the DAX-layer analog of Snowflake's
masking policies (Phase 12 Section 9), same defense-in-depth reasoning:
row access answers "which rows," masking/OLS answers "which columns of
the rows you can see."

---

## 4–12. The Nine Pages

For every page: **Visuals**, **Filters**, **Drill-through**, **KPIs**,
**Color logic**, **Interactions**.

### 4. Portfolio Overview
*Persona: VP Collections, Credit Risk Officer (Phase 1 Section 4)*
- **Visuals:** KPI cards (Total Outstanding Balance, PAR 30/60/90, Active
  Loan Count); PAR 30/60/90 trend line (dual-axis, `dim_time` hierarchy);
  balance-by-`loan_type` donut; balance-by-`risk_band` bar.
- **Filters:** date range slicer, `loan_type`, `risk_band` (page-level).
- **Drill-through:** right-click a PAR trend point or risk-band bar →
  Delinquency Analysis, filtered to that date/band.
- **KPIs:** `PAR 30`, `PAR 60`, `PAR 90`, `Total Outstanding Balance`.
- **Color logic:** `PAR 30 Status Color` measure drives KPI card
  background (red ≥10%, amber 7–10%, green <7% — thresholds centralized
  in `dax_measures.dax`, not hard-coded per visual).
- **Interactions:** clicking the risk-band bar cross-filters the trend
  line to that band only.

### 5. Delinquency Analysis
*Persona: Collections Operations Manager*
- **Visuals:** bucket funnel (Current → 1-29 → 30-59 → 60-89 → 90+ →
  Charged-off); matrix (`risk_band` × `delinquency_bucket`, values =
  balance); `Average Days Delinquent` trend; table of the 20
  largest-balance currently-delinquent loans.
- **Filters:** snapshot date, `risk_band`, `loan_type`, collector team.
- **Drill-through:** clicking a loan row → Customer Drilldown for that
  `loan_id`.
- **KPIs:** `Average Days Delinquent`, delinquent loan count, delinquent
  balance.
- **Color logic:** bucket color scale — green (Current) → yellow (1-29)
  → orange (30-59/60-89) → red (90+) → black (Charged-off) — applied
  consistently to the funnel and matrix.
- **Interactions:** clicking a matrix cell filters the largest-loans
  table to that band/bucket combination.

### 6. Roll Rates
*Persona: Collections Strategy Analyst*
- **Visuals:** Sankey-style bucket-transition flow diagram; `Roll Rate`
  and `Cure Rate` dual-axis trend line; heatmap (`risk_band` × month,
  values = roll rate).
- **Filters:** date range, `risk_band`.
- **Drill-through:** → Delinquency Analysis.
- **KPIs:** `Roll Rate`, `Cure Rate`.
- **Color logic:** `Roll Rate Status Color` (red ≥5%, amber 3–5%, green
  <3% — calibrated against Phase 8's actual observed 3.25% baseline
  sitting just inside the amber/green boundary, a deliberately tight
  band since roll rate is this platform's single most-watched early-
  warning signal per Phase 1 Section 2).
- **Interactions:** clicking a heatmap cell opens a tooltip page listing
  the specific loans that rolled in that band/month.

### 7. Recovery
*Persona: Finance/FP&A, VP Collections*
- **Visuals:** `Recovery Rate` trend; stacked bar (Settlement $ vs.
  un-recovered charge-off $ by month); recovery rate by `loan_type`;
  table of settled loans.
- **Filters:** date range, `loan_type`.
- **Drill-through:** → Customer Drilldown.
- **KPIs:** `Recovery Rate`, `Recovered Amount`, `Charged Off Original
  Balance`.
- **Color logic:** green-intensity scale on the recovery-rate-by-type bar
  (darker = higher recovery).
- **Interactions:** clicking a bar filters the settled-loans table.

### 8. Collector Productivity
*Persona: Collections Operations Manager, individual Collector*
- **Visuals:** leaderboard table (collector, contacts made, PTPs
  obtained, kept $, **kept $ per contact**); scatter plot (contacts made
  × kept $) — deliberately built to make the Phase 1 Section 2.1 root-
  cause problem ("collectors measured by call volume, not $ collected")
  visually obvious: a high-volume/low-$ collector and a lower-volume/
  high-$ collector should be visually distinguishable, not just
  numerically buried in a sorted table.
- **Filters:** team, date range.
- **Drill-through:** → Call Outcomes, filtered to that collector.
- **KPIs:** `Kept Dollars Collected`, `PTP Fulfillment Rate`, `Contacts
  Made`, `Kept Dollars Per Contact`.
- **Color logic:** data bars on the `Kept Dollars Per Contact` column
  specifically (not raw contact count) — reinforces the same
  quality-over-quantity framing at the conditional-formatting level.
- **RLS note:** this page is exactly where `Collector` vs. `Collections
  Manager` roles diverge visibly — a Collector sees only their own row;
  a Manager sees their whole team's leaderboard (Section 3).

### 9. Call Outcomes
*Persona: Collections Operations Manager, Compliance*
- **Visuals:** contact funnel (Attempted → Right Party Contact → PTP
  obtained → Kept); channel-effectiveness bar (RPC rate by
  `channel_code`); complaint-flag trend line; call-duration histogram.
- **Filters:** channel, date range, collector.
- **Drill-through:** → Collector Productivity.
- **KPIs:** `Call Connect Rate`, `Contact Success Rate`, complaint count.
- **Color logic:** complaint trend line turns red if the 7-day moving
  average rises — a direct, visual FDCPA/UDAAP monitoring signal (Phase 1
  Section 7 NFR Regulatory Compliance) surfaced on the page a Compliance
  stakeholder would actually look at.
- **Interactions:** clicking a funnel stage cross-filters the channel bar
  to attempts at that stage only.

### 10. Risk Segmentation
*Persona: Credit Risk Officer*
- **Visuals:** risk-band treemap (sized by balance); PAR-by-`risk_band`
  bar; fraud-flagged loan count callout.
- **Filters:** `risk_band`, `loan_type`.
- **Drill-through:** → Delinquency Analysis.
- **KPIs:** PAR by band, fraud-flagged count.
- **Color logic:** `risk_band` color scale, green (R1 Super Prime) → red
  (R7 High Risk), applied consistently across the treemap and bar so a
  viewer learns the color-to-risk mapping once and it holds everywhere.

### 11. Customer Drilldown
*Persona: individual Collector, Collections Manager (case escalation)*
- **Visuals:** customer header card (name, masked/unmasked phone per RLS
  — Section 3); loan list; payment history table; contact-history
  timeline; PTP history.
- **Filters:** customer/loan search box (parameter-driven, not a slicer
  over a huge dimension).
- **Drill-through:** the *target* of drill-through from every other page
  (Sections 4–10), not a source itself.
- **KPIs:** none aggregate — this page is entirely detail-level by
  design.
- **Color logic:** bucket color (Section 5's scale) applied per loan row.
- **This is the DirectQuery page** (Section 2) — the only one where
  "what does Power BI show" and "what's actually in Snowflake right now"
  are guaranteed to match to the second.

### 12. Executive Summary
*Persona: VP Collections & Recovery (Phase 1's executive sponsor)*
- **Visuals:** large RAG-status KPI cards (`PAR 30` with `PAR 30 Trend
  vs 90D` arrow, `Roll Rate`, `Cure Rate`, `Recovery Rate`); Smart
  Narrative visual (auto-generated plain-English summary of the period's
  movement); portfolio balance trend.
- **Filters:** date range only — deliberately minimal (Phase 1's
  executive persona wants a fast read, not a filtering exercise).
- **Drill-through:** → Portfolio Overview, for anyone who wants more
  detail than the summary gives.
- **KPIs:** all four headline metrics, no others.
- **Color logic:** RAG (red/amber/green) status cards using the same
  centralized threshold measures as every other page.
- **RLS interaction:** because `Executive` role has zero row access to
  any fact/dim table (Section 3), this page — built entirely on
  aggregate KPI measures — is the one page that renders fully for an
  executive; every other page would show empty visuals for that role.
  This page is set as the **default landing page** for the `Executive`
  RLS role specifically because of that.

---

## 13. Bookmarks

Three saved bookmarks, each capturing filter state + visual focus rather
than duplicating pages:

- **"90+ Focus"** — Delinquency Analysis, `delinquency_bucket` filtered
  to `90+`/`Charged-off`, matrix sorted by balance descending. Used in
  the weekly collections leadership review (Phase 1 Section 4's RACI:
  Collections VP accountable for KPI sign-off).
- **"This Month vs Last"** — Portfolio Overview, date range set to
  month-over-month comparison mode.
- **"Compliance Review"** — Call Outcomes, complaint-flag trend
  highlighted, channel filter cleared (full population).

---

## 14. Performance Optimization

- **Import mode aggregation tables** for `fct_delinquency`'s daily-grain
  history beyond a 90-day rolling window (older history summarized
  weekly) — direct application of Power BI's Aggregations feature over
  the same rolling-retention idea Phase 3 Section 3.2 and Phase 10
  Section 4's `build_rolling_par_trend` already established.
- **Incremental refresh** on `fct_payment`/`fct_contact`/
  `fct_promise_to_pay` (Import tables) — only the trailing N days
  re-pull each refresh, not full history, keeping the nightly refresh
  window short and predictable (feeds into Phase 15's deployment
  scheduling).
- **DirectQuery-specific**: `fct_delinquency`'s DirectQuery relies
  directly on Phase 12's `CLUSTER BY (snapshot_date_sk, loan_sk)` and
  Search Optimization Service on `loan_id` — this page's interactive
  performance is a direct, traceable consequence of decisions made two
  phases earlier, not something Power BI solves on its own.

---

## 15. Tableau — Comparison Artifact (per Phase 2's stated secondary deliverable)

A full second dashboard build is out of scope for this portfolio's time
budget, but the structural translation is real and worth stating
precisely, since "how would this differ in Tableau" is a fair interview
question for anyone who's used both:

| Concern | Power BI (built above) | Tableau equivalent |
|---|---|---|
| Semantic model | `model.tmdl`, star schema, DAX measures | Same star schema (Phase 3 unchanged); **Calculated Fields** replace DAX, e.g. `Roll Rate` becomes `SUM(IF [roll_flag] THEN 1 END) / SUM(IF [bucket_index] >= 1 THEN 1 END)` |
| Storage mode | Import / DirectQuery composite (Section 2) | Extract (≈ Import) vs. Live (≈ DirectQuery) — identical tradeoff, same page-by-page decision (Customer Drilldown stays Live) |
| RLS | DAX role filters + `USERPRINCIPALNAME()` (Section 3) | **User Filters** or **Row-Level Security via data source filters**, driven by the same `collector_team_map` table — same design, different mechanism name |
| Saved states | Bookmarks (Section 13) | Tableau doesn't have a direct bookmark equivalent; closest is a saved **custom view** per user, or a dashboard **"Initial View"** setting — narrower than Power BI's bookmark-as-object-you-can-link-to |
| Drill-through | Native drill-through pages | **Dashboard Actions** (Filter/URL actions) — same end-user behavior, configured as inter-sheet actions rather than a first-class "drillthrough page" object |
| Performance | Aggregation tables + incremental refresh (Section 14) | Extract-level aggregation + **Context Filters** to force filter order and shrink the working data set before expensive calculations run |

**Honest bottom line:** every design decision made for Power BI in this
phase translates directly — nothing about the star schema, RLS model, or
page structure is Power-BI-specific. The tool choice genuinely doesn't
change the analytics engineering; it changes which button you click to
implement the same idea, which is exactly the argument for designing the
semantic layer (Phase 3, Phase 12) independent of the BI tool in the
first place.

---

## Next

**Phase 14 — Testing & Data Quality**: the full DQ framework (formalizing
Phase 6/10's quarantine/check patterns), the test suite across every
layer, and the DQ dashboard this project's `dq.check_results` table
(Phase 10 Section 5) feeds.

Say **"continue to Phase 14"** (or flag changes to Phase 13) when ready.
