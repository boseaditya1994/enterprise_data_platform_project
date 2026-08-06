# Quick Start

Gets the full local build chain running end to end. Prerequisite:
Python 3.11+ and pip. Run these in order from the repo root — several
steps build on the previous one's output.

## 1. Generate the synthetic dataset (Phase 5)

```bash
cd data/synthetic
pip install -r requirements.txt --break-system-packages   # Faker, pandas, numpy
pip install duckdb pyyaml --break-system-packages          # needed by later steps too
python3 generate_all.py     # ~75s, writes ./output/ (~2,300 CSV files, ~150MB, gitignored)
python3 validate.py         # sanity-checks the injected messiness rates against Phase 4 targets
```

## 2. Bronze schema registry validation (Phase 6) — optional, quick

```bash
cd ../../pyspark/bronze
python3 validate_registry_local.py
```

## 3. Build Silver, then Gold, into a local DuckDB warehouse (Phases 7–8)

These build **into the same file**, in order — the Gold harness reuses
the warehouse the Silver harness creates.

```bash
cd ../../sql/silver/local_execution
python3 run_silver_build_duckdb.py     # creates warehouse.duckdb, loads bronze + builds silver

cd ../../gold/local_execution
python3 run_gold_build_duckdb.py       # opens the same warehouse.duckdb, adds gold schema + KPIs
```

You now have a real, queryable warehouse at
`sql/silver/local_execution/warehouse.duckdb` (`bronze`/`silver`/`gold`
schemas populated, gitignored — rebuild anytime with the two commands
above). Query it directly, e.g.:

```bash
python3 -c "
import duckdb
con = duckdb.connect('sql/silver/local_execution/warehouse.duckdb', read_only=True)
print(con.execute('SELECT * FROM gold.vw_par_by_date ORDER BY snapshot_date DESC LIMIT 5').df())
"
```

## 4. Run the dbt project (Phase 9)

dbt needs its own copy of that warehouse (it writes new schemas into it):

```bash
cd ../../../dbt
cp ../sql/silver/local_execution/warehouse.duckdb dbt_warehouse.duckdb
pip install dbt-core dbt-duckdb --break-system-packages

DBT_PROFILES_DIR=. dbt seed
DBT_PROFILES_DIR=. dbt run
DBT_PROFILES_DIR=. dbt test
```

For the snapshot mechanism demo (Phase 9 Section 4), run twice with
different `crm_current_as_of_ingestion_day` vars — see
`docs/09-dbt-models.md` Section 4 for the exact commands.

## 5. Run the DQ suite and generate the dashboard (Phase 14)

```bash
cd ../dq
python3 run_dq_checks_duckdb.py       # runs 35 checks against sql/silver/.../warehouse.duckdb
python3 generate_dq_dashboard.py      # renders dq_dashboard.html -- open it in a browser
```

## 6. Run the health check (Phase 16 runbook)

```bash
cd ../ops
python3 health_check.py
```

## Optional, standalone (no dependency chain)

```bash
python3 sql/silver/local_execution/identity_resolution_demo.py   # Phase 7's matching-algorithm proof
```

## What's NOT runnable locally

`pyspark/`, `adf/`, `snowflake/`, `powerbi/`, and `.github/workflows/`
contain real, reviewed code/config for Databricks, Azure Data Factory,
Snowflake, and Power BI/GitHub Actions respectively — none of these have
a local execution mode, so there's nothing to run for them here. See
each phase's doc (`docs/06`, `docs/10`–`13`, `docs/15`) for what was
validated instead (JSON/YAML well-formedness, syntax checks) and why.
