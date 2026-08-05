# Loan Delinquency & Collections Command Center

An enterprise-grade, Fortune-500-style analytics platform for monitoring
loan portfolio health, prioritizing collections work, and measuring
collector/channel effectiveness — built end-to-end as a portfolio project
for Senior Data Engineer / Analytics Engineer / Data Architect interviews.

This repo is being built **phase by phase**. Each phase is complete and
reviewed before the next begins. See [`docs/00-project-plan.md`](docs/00-project-plan.md)
for status and [`docs/`](docs/) for all deliverables.

## Repo layout

```
loan-delinquency-command-center/
├── docs/          # requirements, architecture, data model, runbooks, diagrams, resume material
├── sql/           # DDL, MERGE statements, views, stored procs
├── pyspark/       # Databricks/PySpark notebooks — bronze/silver/gold, streaming, CDC, DQ
├── dbt/           # dbt project — models, sources, snapshots, tests, macros
├── adf/           # Azure Data Factory pipeline JSON + design docs
├── snowflake/     # warehouse/schema/task/stream DDL, RBAC, clustering
├── powerbi/       # dashboard spec, DAX measures, page-by-page design
├── data/synthetic/# Faker-based synthetic data generators + sample outputs
├── scripts/       # utility scripts (data gen, DQ checks, orchestration helpers)
└── tests/         # dbt tests, PySpark unit tests, DQ test fixtures
```

## Status

🟢 Phase 1 — Requirements & Business Analysis — **complete**
⚪ Phase 2 — Architecture
⚪ Phase 3 — Data Modeling
⚪ Phase 4 — Dataset Design
⚪ Phase 5 — Synthetic Data Generation
⚪ Phase 6 — Bronze Layer
⚪ Phase 7 — Silver Layer
⚪ Phase 8 — Gold Layer
⚪ Phase 9 — dbt Models
⚪ Phase 10 — Databricks
⚪ Phase 11 — ADF Pipelines
⚪ Phase 12 — Snowflake
⚪ Phase 13 — Power BI
⚪ Phase 14 — Testing & Data Quality
⚪ Phase 15 — Deployment & CI/CD
⚪ Phase 16 — Documentation
⚪ Phase 17 — Resume & Interview Preparation
