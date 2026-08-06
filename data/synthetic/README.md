# Synthetic Data Generator

Implements the design in [`docs/04-dataset-design.md`](../../docs/04-dataset-design.md)
and [`docs/05-synthetic-data-generation.md`](../../docs/05-synthetic-data-generation.md).

## Run it

```bash
cd data/synthetic
pip install -r requirements.txt --break-system-packages   # Faker, pandas, numpy
python3 generate_all.py        # ~75s, writes ./output/ (demo scale: ~2,300 files, ~150MB)
python3 validate.py            # reads ./output/ back and reports actual scenario rates
```

Set `SYN_SCALE_PROFILE=smoke` (400 customers / 500 loans, a few seconds)
for a fast sanity-check run while iterating on generator code, or
`SYN_SCALE_PROFILE=demo` (default; 8,000 customers / 10,000 loans) for the
full portfolio-scale dataset described in Phase 4.

## Output is not committed to git

`./output/` is in `.gitignore` on purpose — generated data is a build
artifact (regenerate it any time with the command above), the same way a
real pipeline's landed files are never checked into source control. What
*is* committed is the generator code that produces it deterministically
(`RANDOM_SEED` in `generator/config.py`), plus a small `samples/` folder
with hand-picked illustrative rows for anyone reviewing this repo without
running the generator.

## Structure

```
data/synthetic/
├── generator/
│   ├── config.py            # every volumetric/rate/probability, traced to Phase 4
│   ├── identities.py        # customers (Faker), collectors, applications, loans, joint-applicant bridge
│   ├── simulate_lifecycle.py# the core day-by-day delinquency state machine (Phase 4 Section 3)
│   ├── generate_events.py   # contact attempts, automated reminders, promises-to-pay
│   ├── bureau_risk.py       # Credit Bureau + Risk Engine monthly extracts (incl. outages/lateness)
│   ├── messiness.py         # reversals, NSF returns, duplicates, corrupt records, late arrivals
│   └── writer.py            # partitions everything into daily Bronze-style CSV drops + schema drift
├── generate_all.py          # orchestrator / entry point
├── validate.py               # reads generated output back, reports actual vs. target scenario rates
├── samples/                  # curated example rows (committed) — see docs/05 for a guided tour
└── output/                   # full generated dataset (gitignored, regenerate locally)
```

## Output layout (mirrors Bronze landing pattern from Phase 2)

```
output/raw_<source_table>/dt=YYYY-MM-DD/part-000.csv
output/raw_<reference_table>/full_snapshot.csv   # small non-time-partitioned tables
```
