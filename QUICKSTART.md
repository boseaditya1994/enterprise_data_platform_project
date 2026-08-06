# Quick Start

Gets the full local build chain running end to end. Prerequisite:
Python 3.11+ and pip.

**Every command block below starts from the repo root** (the folder
containing this file) — copy-paste each block as-is, in order. None of
them assume you're still sitting in the previous block's directory.

## 1. Generate the synthetic dataset (Phase 5)

```bash
cd data/synthetic
pip install -r requirements.txt --break-system-packages   # Faker, pandas, numpy
pip install duckdb pyyaml --break-system-packages          # needed by later steps too
python3 generate_all.py     # ~75s, writes ./output/ (~2,300 CSV files, ~150MB, gitignored)
python3 validate.py         # sanity-checks the injected messiness rates against Phase 4 targets
cd ../..                    # back to repo root
```

## 2. Bronze schema registry validation (Phase 6) — optional, quick

```bash
cd pyspark/bronze
python3 validate_registry_local.py
cd ../..
```

## 3. Build Silver, then Gold, into a local DuckDB warehouse (Phases 7–8)

These build **into the same file**, in order — the Gold harness reuses
the warehouse the Silver harness creates.

```bash
cd sql/silver/local_execution
python3 run_silver_build_duckdb.py     # creates warehouse.duckdb, loads bronze + builds silver
cd ../../..

cd sql/gold/local_execution
python3 run_gold_build_duckdb.py       # opens the same warehouse.duckdb, adds gold schema + KPI views
cd ../../..
```

You now have a real, queryable warehouse at
`sql/silver/local_execution/warehouse.duckdb` (`bronze`/`silver`/`gold`
schemas populated, plus the `gold.vw_*` KPI views from
`sql/gold/kpi_definitions.sql`, gitignored — rebuild anytime with the two
commands above). Query it directly from the repo root:

```bash
python3 -c "
import duckdb
con = duckdb.connect('sql/silver/local_execution/warehouse.duckdb', read_only=True)
print(con.execute('SELECT * FROM gold.vw_par_by_date ORDER BY snapshot_date DESC LIMIT 5').df())
"
```

## 4. Run the dbt project (Phase 9)

dbt needs its own copy of that warehouse (it writes new schemas into it).

**Use a virtual environment for this step** — installing `dbt-core`/
`dbt-duckdb` with `--break-system-packages` against your system Python
(especially on macOS, where it's common to have several Pythons on PATH)
can silently install into a different Python than the one the `dbt`
command actually runs from, producing `Error importing adapter: No
module named 'dbt.adapters.duckdb'` even though the install appeared to
succeed. A venv avoids that entirely:

```bash
python3 -m venv .venv
source .venv/bin/activate       # run this again in any new terminal session
pip install dbt-core dbt-duckdb

cp sql/silver/local_execution/warehouse.duckdb dbt/dbt_warehouse.duckdb

cd dbt
DBT_PROFILES_DIR=. dbt seed
DBT_PROFILES_DIR=. dbt run
DBT_PROFILES_DIR=. dbt test
cd ..
```

**If you hit that "No module named 'dbt.adapters.duckdb'" error anyway**
(e.g. installed without a venv first): confirm the mismatch with
`which dbt`, `which python3`, and `python3 -m pip show dbt-duckdb` — if
the last one comes back empty, `dbt` and `pip` are resolving to different
Pythons. Fastest fix without a venv:
```bash
python3 -m pip install --break-system-packages --force-reinstall dbt-core dbt-duckdb
```

For the snapshot mechanism demo (Phase 9 Section 4), run twice with
different `crm_current_as_of_ingestion_day` vars from inside `dbt/` — see
`docs/09-dbt-models.md` Section 4 for the exact commands.

## 5. Run the DQ suite and generate the dashboard (Phase 14)

```bash
cd dq
python3 run_dq_checks_duckdb.py       # runs 35 checks against sql/silver/.../warehouse.duckdb
python3 generate_dq_dashboard.py      # renders dq_dashboard.html -- open it in a browser
cd ..
```

## 6. Run the health check (Phase 16 runbook)

```bash
cd ops
python3 health_check.py
cd ..
```

## Optional, standalone (no dependency chain)

```bash
cd sql/silver/local_execution
python3 identity_resolution_demo.py   # Phase 7's matching-algorithm proof
cd ../../..
```

## If a command errors with "database does not exist" or a similar path error

Almost always means the working directory is wrong for that command —
every block above is written to run from the repo root, and each ends by
`cd`-ing back there. Run `pwd` to check where you actually are, and
compare against the block you're running; `ls` should show `README.md`,
`docs/`, `sql/`, etc. if you're at the root.

## What's NOT runnable locally

`pyspark/`, `adf/`, `snowflake/`, `powerbi/`, and `.github/workflows/`
contain real, reviewed code/config for Databricks, Azure Data Factory,
Snowflake, and Power BI/GitHub Actions respectively — none of these have
a local execution mode, so there's nothing to run for them here. See
each phase's doc (`docs/06`, `docs/10`–`13`, `docs/15`) for what was
validated instead (JSON/YAML well-formedness, syntax checks) and why.
