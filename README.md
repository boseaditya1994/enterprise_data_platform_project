# Loan Delinquency & Collections Command Center

An enterprise-grade, Fortune-500-style analytics platform for monitoring
loan portfolio health, prioritizing collections work, and measuring
collector/channel effectiveness — built end-to-end as a portfolio project
for Senior Data Engineer / Analytics Engineer / Data Architect interviews.

This repo is being built **phase by phase**. Each phase is complete and
reviewed before the next begins. See [`docs/00-project-plan.md`](docs/00-project-plan.md)
for status and [`docs/`](docs/) for all deliverables.

**Status: all 17 phases complete.** Start with
[`docs/17-resume-interview-prep.md`](docs/17-resume-interview-prep.md)
for the project summary, or [`docs/00-project-plan.md`](docs/00-project-plan.md)
for the full phase-by-phase index. To actually run the pipeline locally,
see [`QUICKSTART.md`](QUICKSTART.md).

## Repo layout

```
loan-delinquency-command-center/
├── docs/            # requirements, architecture, data model, runbooks, glossary, resume material (17 phase docs)
├── data/synthetic/  # Python/Faker synthetic data generator (generator/, samples/); output/ is gitignored, regenerate locally
├── sql/silver/      # hand-rolled Silver CDC/SCD2 SQL + DuckDB proof-of-concept harness
├── sql/gold/        # KPI view SQL + DuckDB Gold-build harness
├── pyspark/         # Databricks/PySpark: bronze ingestion, streaming, silver SCD2, gold, DQ, optimization
├── dbt/             # dbt project — models, sources, snapshots, seeds, macros, tests (35 models, 40 tests)
├── adf/             # Azure Data Factory pipeline JSON, control table, Airflow comparison DAG
├── snowflake/       # warehouse/schema/RBAC/masking DDL + versioned migrations
├── powerbi/         # TMDL semantic model, DAX measures, RLS roles
├── dq/              # enterprise DQ rules catalog + executable check runner + HTML dashboard
├── ops/             # runbook tooling (health_check.py)
├── resources/, databricks.yml   # Databricks Asset Bundle (job deployment)
└── .github/workflows/           # CI/CD (dbt, PySpark, ADF, Snowflake migrations, release promotion)
```

Every folder above contains real, and in most cases actually-executed,
artifacts — not just design docs. See `docs/00-project-plan.md` for
which phase built what, and `docs/17-resume-interview-prep.md` for a
guided tour of what's most worth reading first.

## Status

🟢 Phase 1 — Requirements & Business Analysis — **complete**
🟢 Phase 2 — Architecture — **complete**
🟢 Phase 3 — Data Modeling — **complete**
🟢 Phase 4 — Dataset Design — **complete**
🟢 Phase 5 — Synthetic Data Generation — **complete**
🟢 Phase 6 — Bronze Layer — **complete**
🟢 Phase 7 — Silver Layer — **complete**
🟢 Phase 8 — Gold Layer — **complete**
🟢 Phase 9 — dbt Models — **complete**
🟢 Phase 10 — Databricks — **complete**
🟢 Phase 11 — ADF Pipelines — **complete**
🟢 Phase 12 — Snowflake — **complete**
🟢 Phase 13 — Power BI — **complete**
🟢 Phase 14 — Testing & Data Quality — **complete**
🟢 Phase 15 — Deployment & CI/CD — **complete**
🟢 Phase 16 — Documentation — **complete**
🟢 Phase 17 — Resume & Interview Preparation — **complete**
