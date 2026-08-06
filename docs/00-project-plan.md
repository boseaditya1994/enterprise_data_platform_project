# Project Plan & Phase Tracker

This project is built in 17 sequential phases. Each phase produces real
artifacts in this repo (not just narrative) and is signed off before the
next one starts.

| # | Phase | Key deliverables | Status |
|---|-------|-------------------|--------|
| 1 | Requirements & Business Analysis | Problem statement, personas, RACI, functional/non-functional requirements, scope, risks | ✅ Complete |
| 2 | Architecture | Medallion architecture diagram, source-to-target flow, tech stack justification, lineage | ✅ Complete |
| 3 | Data Modeling | Star schema (facts/dims), SCD strategy, keys, sample records, ERD | ✅ Complete |
| 4 | Dataset Design | Entity list, event scenarios, volumetrics, data dictionary | ✅ Complete |
| 5 | Synthetic Data Generation | Faker-based Python generators, 6–12 months of interconnected data | ✅ Complete |
| 6 | Bronze Layer | Raw schemas per source, landing strategy, audit columns, PySpark ingestion | ✅ Complete |
| 7 | Silver Layer | Conformed models, dedup, survivorship, CDC merge, late-arrival handling | ✅ Complete |
| 8 | Gold Layer | Delinquency mart, KPI SQL, rolling windows, snapshots | ✅ Complete |
| 9 | dbt Models | Project structure, sources, snapshots, tests, macros, docs | ✅ Complete |
| 10 | Databricks | Bronze/Silver/Gold notebooks, streaming, checkpointing, Delta optimizations | ✅ Complete |
| 11 | ADF Pipelines | Pipeline JSON, triggers, parameterization, retry/error handling | ✅ Complete |
| 12 | Snowflake | Warehouses, schemas, Streams/Tasks, RBAC, clustering | ✅ Complete |
| 13 | Power BI | Page-by-page dashboard spec, DAX, RLS, drill-through | ✅ Complete |
| 14 | Testing & Data Quality | DQ framework, quarantine tables, test suite | ✅ Complete |
| 15 | Deployment & CI/CD | CI/CD pipeline design, environments, promotion strategy | ✅ Complete |
| 16 | Documentation | Runbook, DR plan, security architecture, cost optimization, glossary | ✅ Complete |
| 17 | Resume & Interview Prep | Resume bullets, STAR stories, elevator pitch, walkthrough script | ✅ Complete |

**Working agreement:** each phase is delivered in full, saved to disk under
the appropriate folder, and I wait for your go-ahead ("continue to Phase 2")
before starting the next one. If you want to revise a completed phase later,
just say so — later phases will be checked for consistency against the change.
