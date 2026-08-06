# Phase 15 — Deployment & CI/CD

**Traces to:** every prior phase — this is the release mechanism that
takes dbt (Phase 9), PySpark/Databricks (Phase 6/10), ADF (Phase 11),
and Snowflake (Phase 12) from "code in this repo" to "running in an
actual environment." Code: [`.github/workflows/`](../.github/workflows/),
[`databricks.yml`](../databricks.yml), [`resources/`](../resources/),
[`snowflake/migrations/`](../snowflake/migrations/).

**Scope note:** GitHub Actions requires a GitHub repository and live
cloud credentials to actually execute — these workflows are real,
schema-valid YAML (every file parsed and validated, Section 6), reviewed
for correctness, not run end-to-end in this sandbox. Same honesty
standard as Phases 10–14.

---

## 1. Environment & Promotion Strategy

**Three environments — dev, test, prod — physically isolated per tool,**
not just logically namespaced:

| Tool | Isolation mechanism |
|---|---|
| Snowflake | Separate database per environment (`LOAN_DELINQUENCY_CC_DEV`/`_TEST`/prod), separate Snowflake user credentials per environment (`SNOWFLAKE_DEV_USER` vs. `SNOWFLAKE_TEST_USER` vs. `SNOWFLAKE_PROD_USER`) |
| Databricks | Separate workspace per environment (`adb-loandelinqcc-dev/test/prod`), `databricks.yml`'s `targets` block — prod additionally runs jobs as a service principal, never a human identity |
| ADF | Separate Data Factory resource per environment (`adf-loandelinqcc-dev/test/prod`), separate resource group |
| dbt | Separate `target` per environment in `profiles.yml` (not committed — real credentials live in CI secrets, Section 6) |

**Promotion is a human decision, not automatic.** Every merge to `main`
auto-deploys to **dev only** (`ci_dbt.yml`/`ci_pyspark.yml`/`ci_adf.yml`'s
`push` triggers). Promotion to **test** and **prod** happens exclusively
through `release.yml`, triggered by a published GitHub Release —
`environment: test`/`environment: prod` in that workflow map to GitHub
Environments configured with **required reviewers** (1 for test, 2 for
prod — a deliberately higher bar for the environment executives and real
customers' data actually depend on). This is the concrete mechanism
behind "promotion beyond dev always requires human approval," not just a
stated policy with nothing enforcing it.

---

## 2. Branching Strategy

Trunk-based, not GitFlow: short-lived feature branches → PR against
`main` → CI validates (Section 3) → merge → auto-deploy to dev → tag a
GitHub Release when ready to promote further → `release.yml` gates test
then prod. No long-lived `develop`/`release` branches to keep in sync —
every environment beyond dev traces back to a specific, tagged commit on
`main`, which is also what makes rollback well-defined (redeploy the
previous tag, Section 5).

---

## 3. CI — What Runs on Every Pull Request

| Workflow | Validates |
|---|---|
| `ci_dbt.yml` | `dbt seed`/`run`/`test` against an **ephemeral, PR-number-scoped Snowflake schema** (`ci_pr_{number}`) — concurrent PRs never collide, nothing touches dev/test/prod, and the schema is torn down even on failure (`if: always()`) so failed PRs don't accumulate orphaned Snowflake storage cost. Also `sqlfluff` lint. |
| `ci_pyspark.yml` | `ruff` lint, unit tests against pure-logic functions only (`detect_schema_drift()`, DQ helper functions — anything needing a real `SparkSession` is validated by the Phase 7/8 DuckDB harnesses instead, deliberately **not** re-run here — see Section 4's reasoning), and `databricks bundle validate` (dry-run, no deploy). |
| `ci_adf.yml` | Every pipeline/dataset/linkedService/trigger JSON parses (the exact check performed manually in Phase 11 Section 6, now a **standing CI gate** — same "convert a manual check into permanent infrastructure" pattern as Phase 9's regression test). |
| `ci_snowflake_migrations.yml` | Migration filename convention, `sqlfluff` lint, and a `schemachange deploy --dry-run` against dev (validates the migration *would* apply cleanly without actually applying it). |

**Why the DuckDB/dbt proof-of-design harnesses from Phases 7–9 aren't
re-run in CI**: those runs already proved the *logic* is correct
(exact-match row counts, cross-validated KPI values) — re-running a
multi-minute DuckDB build on every PR would slow feedback for validation
that doesn't change unless the underlying business logic itself changes
(in which case, the PR touching that logic should update and re-verify
the harness manually, the same way any of this project's phases were
built). CI's job is fast, cheap regression protection on config/syntax;
deep logic validation is a design-time activity, not a per-PR one.

---

## 4. CD — What Happens on Merge and on Release

**On merge to `main`**: dev-only auto-deploy for whichever tool's files
changed (path-filtered triggers — a PR touching only `dbt/` never
triggers the ADF or Databricks workflows). Each deploy is followed by a
smoke test specific to that tool:
- dbt: `dbt test --target dev` (the full 40-test suite, Phase 9)
- Databricks: `databricks bundle run bronze_ingestion_smoke_test` against
  the smallest, fastest real source (`raw_servicing_loan_applicant_bridge`
  — same choice made independently by `ci_adf.yml`'s own smoke pipeline,
  Section 6 confirms this wasn't a coincidence)
- ADF: trigger a single-source pipeline run via `az datafactory
  pipeline create-run`

**On a published GitHub Release** (`release.yml`): sequential
`deploy-test` → `deploy-prod`, each gated by its own required-reviewer
approval, each running the full dbt test suite against that specific
environment before moving on. Prod's ADF deploy note is worth reading
closely: **the daily trigger deploys in a stopped state** (standard ADF
ARM template behavior) and needs an explicit activation step — so a prod
release can never accidentally start firing a new/changed schedule
before someone's confirmed the deploy looks right first.

---

## 5. Rollback

Because every environment beyond dev traces to a tagged release
(Section 2), rollback is "redeploy the previous tag" — re-running
`release.yml` against an older `github.event.release.tag_name` restores
dbt models, the Databricks bundle, and the ADF factory to that commit's
exact state. **Snowflake schema rollback is the one asymmetric case**,
called out directly rather than glossed over: `schemachange` migrations
(Section 7) are forward-only by convention — `V1.8`'s own migration file
documents its manual rollback SQL in a comment specifically *because*
schemachange doesn't auto-generate down-migrations. This is a real,
common limitation of the schemachange/Flyway migration style (vs. tools
that require symmetric up/down scripts) worth naming plainly.

---

## 6. Validation Performed

Every workflow YAML and the Databricks bundle config were parsed and
confirmed well-formed (same bar as Phase 11's JSON validation):

```
OK   .github/workflows/ci_adf.yml
OK   .github/workflows/ci_dbt.yml
OK   .github/workflows/ci_pyspark.yml
OK   .github/workflows/release.yml
OK   .github/workflows/ci_snowflake_migrations.yml
OK   databricks.yml
OK   resources/jobs.yml
```

**A real bug caught by this validation**: the first draft of
`release.yml` and `resources/jobs.yml` used unquoted `${{ ... }}`/
`${...}` template expressions inside YAML flow-mapping syntax (`with: {
ref: ${{ ... }} }`) — YAML's parser reads the inner `{{` as the start of
a *nested* flow mapping, not as GitHub Actions' template delimiter, and
fails to parse. Fixed by quoting the expression
(`with: { ref: "${{ ... }}" }`). This is a genuinely common real-world
GitHub Actions authoring mistake — the same "actually run the validation
instead of trusting the file looks right" discipline this project has
applied at every layer (Phase 6's registry bug, Phase 8's SCD2 boundary
bug, Phase 14's DQ investigation) caught it here too, in configuration
rather than in a data pipeline.

---

## 7. Design Rationale

**Why `schemachange`/versioned migrations for Snowflake specifically,
when dbt/Databricks/ADF each deploy their "current state" directly**:
Snowflake DDL (roles, masking policies, row access policies — Phase 12)
is fundamentally different from a dbt model or a notebook: it's
*stateful, security-sensitive infrastructure*, not a rebuildable
artifact. Re-running `09_masking_policies.sql` idempotently is easy;
re-running a full RBAC grant script against prod without tracking what
already happened risks transient over- or under-privileging during the
run. A migration tool's whole purpose is making changes to that kind of
state auditable and incremental — exactly why `V1.8`
(`snowflake/migrations/`) exists as a real, worked example rather than a
hypothetical description.

**Why smoke tests use the smallest source, independently, in two
different workflows**: not a coincidence — both `ci_adf.yml` and
`resources/jobs.yml`'s `bronze_ingestion_smoke_test` job reasoned to the
identical choice (`raw_servicing_loan_applicant_bridge`, Phase 6's
smallest/fastest table) because the same underlying question — "what's
the cheapest real proof this deployment actually works" — has one right
answer regardless of which tool is asking it.

**Common interview questions for this phase:**
- *"How do you prevent a bad PR from ever touching production data?"* →
  Section 3's ephemeral, PR-scoped CI schema, plus Section 1's
  environment-credential isolation — two independent barriers, not one.
- *"Walk me through what happens when you tag a release."* → Section 4,
  in full, including the deliberately-stopped prod trigger.
- *"How would you roll back a bad Snowflake migration?"* → Section 5's
  honest answer about schemachange's forward-only convention and the
  manual rollback SQL pattern.
- *"Tell me about a bug you caught in your own CI/CD config."* → Section
  6's YAML flow-mapping quoting bug — real, specific, and caught by
  actually validating rather than assuming.

---

## Next

**Phase 16 — Documentation**: the enterprise documentation suite this
project has been feeding all along — architecture/data-flow/ER diagrams
consolidated, a deployment guide, business glossary, runbook, monitoring
guide, disaster recovery plan, security architecture summary, and cost
optimization analysis.

Say **"continue to Phase 16"** (or flag changes to Phase 15) when ready.
