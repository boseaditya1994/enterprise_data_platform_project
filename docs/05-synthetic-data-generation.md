# Phase 5 — Synthetic Data Generation

**Traces to:** Phase 4 (`docs/04-dataset-design.md`) Sections 2–6 — this
phase is the executable implementation of that design. Code lives in
[`data/synthetic/`](../data/synthetic/).

---

## 1. What was built

A deterministic (seeded), modular Python generator that walks the Phase 4
loan-lifecycle state machine for 10,016 approved loans across 8,000
customers over a 6-month window (Jan–Jun 2025), and writes the result out
as **daily-partitioned CSV files that mimic how each source system would
actually land a Bronze extract** — not one flat "clean" table.

| Module | Responsibility |
|---|---|
| `generator/config.py` | Every volumetric, probability, and injection rate — all traced to a specific Phase 4 number |
| `generator/identities.py` | Customers (Faker), collector roster + reorg, loan applications → approved loans, joint-applicant bridge |
| `generator/simulate_lifecycle.py` | The core day-by-day delinquency state machine (Phase 4 §3) |
| `generator/generate_events.py` | Contact attempts, automated reminders, promises-to-pay, derived from the delinquency state |
| `generator/bureau_risk.py` | Monthly Credit Bureau + Risk Engine extracts, including outage/lateness scenarios |
| `generator/messiness.py` | Payment reversals, NSF returns, duplicates, corrupt records, late arrivals |
| `generator/writer.py` | Partitions everything into `dt=YYYY-MM-DD` daily drops; applies schema drift at write time |
| `generate_all.py` | Orchestrates the above, prints a run summary |
| `validate.py` | Reads the output back and reports **actual** achieved scenario rates — see Section 3 |

Run it: see [`data/synthetic/README.md`](../data/synthetic/README.md).

---

## 2. A key design change made *during* implementation (and why)

Phase 4's volumetrics formula implicitly assumed most loans originate at
or near the start of the 6-month window. Implementing it literally that
way produced too little tenure per loan (loans originating mid-window
have few months left to generate activity) and under-shot every target.

**Fix:** ~65% of loans now originate as an already-seasoned "back book"
— origination date 30–365 days *before* the window opens — with only
~35% representing genuinely new originations during the window. This is
also simply **more realistic**: a real bank's collections portfolio on
any given day is overwhelmingly seasoned loans, not day-one originations.
The lifecycle simulator still walks each loan's *pre-window* due-date
cycles (so a seasoned loan can plausibly already be a few payments behind
by the time the window opens), it just no longer *emits* Bronze rows for
those pre-window cycles — only their resulting state carries forward.
This is documented here rather than silently fixed because it's exactly
the kind of "the data didn't look right, here's what I changed and why"
narrative that's valuable to be able to tell in an interview.

---

## 3. Actual vs. target volumetrics

| Table | Phase 4 target | Actual generated | Notes |
|---|---|---|---|
| `customer_dim` (incl. SCD2 versions) | ~8,500 | **8,400** | 8,000 unique customers, 5% relocated |
| `loan_dim` (incl. SCD2 versions) | ~10,800 | **10,089** | 10,016 approved loans (10,870 applications, 92% approval) |
| `collector_dim` (incl. SCD2 versions) | ~140 | **168** | 120 collectors, 40% reassigned at the mid-window reorg |
| `payment_fact` | ~69,000 | **49,967** | see Section 5 limitation note |
| `delinquency_fact` | ~1,800,000 | **1,509,105** | within the right order of magnitude; exact match isn't the goal |
| `contact_fact` | ~40,000 | **39,071** | |
| `promise_to_pay_fact` | ~3,500 | **1,852** | see Section 5 limitation note |
| `loan_applicant_bridge` | ~1,500 | **1,474** | |

**Scenario injection rates — actual, from `validate.py`:**

| Scenario | Target rate | Actual rate |
|---|---|---|
| Payment reversals | ~2% | **1.78%** |
| NSF/returned payments | ~1.5% of ACH (~0.8% of all payments) | **0.80%** |
| Late-arriving payments | ~4% | **3.97%** |
| Duplicate payment events | ~1% | **0.99%** |
| Corrupt payment records | ~0.3% | **0.30%** |
| Bureau late arrivals | ~5% | **4.90%** |
| Charge-offs | ~2% of loans | **201 / 10,016 = 2.0%** |

Schema drift verified present: `loan_purpose_code` appears on
`raw_servicing_daily_status` rows from **2025-03-02** onward (72% of all
rows carry it, matching the fraction of the window after the drift date);
`raw_collections` renames `collector_id` → `collector_ref_id` from
**2025-04-11** onward. Both confirmed programmatically by `validate.py`,
not just by eyeballing a sample.

---

## 4. Sample data walkthrough

Curated, committed examples live in
[`data/synthetic/samples/`](../data/synthetic/samples/) so this scenario
catalog is verifiable without running the generator.

**Schema drift — additive** (`servicing_daily_status_PRE/POST_drift_*.csv`):
pre-drift rows have 9 columns ending in `delinquency_bucket`; post-drift
(2025-03-15) rows have a 10th column, `loan_purpose_code`.

**Schema drift — breaking rename** (`collections_PRE/POST_rename_*.csv`):
2025-02-01 rows have a `collector_id` column; 2025-04-15 rows have
`collector_ref_id` instead — a naive column-position mapping in Bronze
ingestion would silently break here, which is exactly the point (Phase 6
handles this via schema-drift detection, not silent absorption).

**Loan events** (`loan_events_examples.csv`) — real generated rows:
```
loan_id,event_type,event_date,details
LN-504270,RESTRUCTURE,2025-01-02,new_rate_reduction=0.02;new_term_months=66
LN-505161,CHARGE_OFF,2025-01-02,balance=21462.03
LN-507816,SETTLEMENT,2025-01-03,settled_amount=12267.50
LN-505346,FRAUD_FLAG,2025-01-07,
```

**Customer relocation** (`crm_relocation_examples.csv`) — each relocated
customer has two CRM rows: an `INITIAL_LOAD` and a later `RELOCATION` row
with a new city/state/zip and a later `source_updated_at`, exactly the
shape Phase 3's `customer_dim` SCD2 versioning expects.

**Payment messiness** (`payments_messiness_examples.csv`) — five each of
reversed, NSF-returned, late-arriving, and corrupt-record payment rows
side by side.

---

## 5. Known simplifications (stated, not hidden)

- **Straight-line amortization**, not a true actuarial schedule —
  `outstanding_balance` decreases by a flat estimated principal portion
  per payment rather than a compounding-interest schedule. Adequate for
  believable portfolio-level analytics; would need a real amortization
  engine if loan-level payoff-schedule accuracy mattered.
- **`payment_fact` and `promise_to_pay_fact` came in below target**
  (49,967 vs. ~69,000; 1,852 vs. ~3,500). Root cause: Phase 4's formulas
  assumed a higher fraction of loans carry a full 6 monthly cycles inside
  the window than the (more realistic) seasoned/new mix in Section 2
  produces on closer inspection, and PTP volume is naturally gated by
  contact volume × RPC rate × PTP-given-RPC rate, three compounding
  probabilities. Rather than keep tuning probabilities to chase an
  arbitrary target number, the honest choice was to document the actual
  achieved figures here — the dataset is still large enough (tens of
  thousands of payment and contact rows, ~1.5M delinquency snapshots) to
  fully exercise every downstream phase.
- **PTP fulfillment payments aren't separately linked back** to
  `payment_fact.payment_id` in this generation pass (Phase 3's
  `promise_to_pay_fact.actual_payment_id` is left null here) — Phase 7's
  Silver-layer matching logic is the natural place to actually implement
  that join/reconciliation, rather than having the generator pre-solve it.
- **No literal duplicate bureau/risk-engine records or genuinely
  malformed CSV structure** (e.g. wrong delimiter, truncated rows) — the
  corrupt-record scenario is implemented as bad *values* (negative
  amounts, nulled required fields), which is what Phase 14's DQ checks
  are designed to catch; truly malformed file structure would be a
  parsing-layer concern more than a data-quality one and is out of scope.

---

## 6. Design Rationale

**Why partition output as `dt=YYYY-MM-DD/part-000.csv` per source instead
of one big CSV per table:** this *is* what Bronze ingestion in Phase 6
will actually read — one file per source per day, landed by ADF on its
own schedule. Generating it this way (rather than one flat table sliced
later) forces the generator to get late-arrival and schema-drift timing
right at the point of "landing," which is the only place those scenarios
are actually real.

**Why a deterministic seed:** reproducibility. Anyone cloning this repo
and running `generate_all.py` gets byte-identical output, which matters
for the "trust" property from Phase 1 (Section 11) — one benefit of
synthetic-but-realistic data over "randomly regenerate every time" is
that downstream phases (Bronze schemas, DQ thresholds, dbt tests) can be
built and tested against a stable target.

**Why validate the generator's own output instead of trusting the
generation logic:** the same principle that governs the whole platform
(Phase 1's root cause: nobody trusted numbers nobody could trace) applies
to the synthetic data itself — `validate.py` exists so every claim in
Section 3 is a measured fact, not an assertion.

**Common interview questions for this phase:**
- *"How did you make sure your synthetic data wasn't just random noise?"*
  → Section 4's sample walkthrough plus the `validate.py` report — every
  scenario is independently checkable, not just narrated.
- *"What would you do differently with more time?"* → Section 5's stated
  simplifications — a real amortization schedule and generator-side
  PTP↔payment reconciliation are the two honest answers.
- *"Why not commit the generated data to the repo?"* → `data/synthetic/README.md`
  — generated data is a build artifact; only the generator is source.
- *"Walk me through one scenario end to end."* → Pick schema drift: designed
  in Phase 4 §5 scenario #4 → implemented in `writer.collections_schema_drift`
  → verified in `validate.py` → sample committed in
  `collections_PRE/POST_rename_*.csv` → will be caught by Phase 6's
  schema-drift detection rather than silently breaking downstream models.

---

## Next

**Phase 6 — Bronze Layer**: formal per-source raw table schemas (matching
exactly what `writer.py` produced above), metadata/audit columns, landing
strategy, file formats, partitioning, and retention policy — plus the
PySpark ingestion notebooks that read this generated data in.

Say **"continue to Phase 6"** (or flag changes to Phase 5) when ready.
