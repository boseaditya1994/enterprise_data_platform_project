"""
Central configuration for the synthetic data generator.

Every parameter here traces to a specific number in
docs/04-dataset-design.md (Section 4 Volumetrics, Section 5 Scenario
Catalog). Change scale here to move between "smoke test" and
"demo scale" runs without touching generator logic.
"""
from datetime import date

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Scale profile (Phase 4, Section 1 "Demo Scale")
# Set SCALE_PROFILE = "demo" for the full 10k-loan run described in the
# docs, or "smoke" for a fast local sanity-check run.
# ---------------------------------------------------------------------------
import os as _os
SCALE_PROFILE = _os.environ.get("SYN_SCALE_PROFILE", "demo")

SCALE_PROFILES = {
    "smoke": {"n_customers": 400, "n_loans": 500},
    "demo": {"n_customers": 8_000, "n_loans": 10_000},
}

N_CUSTOMERS = SCALE_PROFILES[SCALE_PROFILE]["n_customers"]
N_LOANS = SCALE_PROFILES[SCALE_PROFILE]["n_loans"]

# ---------------------------------------------------------------------------
# Time window (Phase 4 Section 1)
# ---------------------------------------------------------------------------
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 6, 30)  # inclusive
N_DAYS = (WINDOW_END - WINDOW_START).days + 1

# US bank holidays observed in the window (Phase 4 scenario #14)
US_BANK_HOLIDAYS_2025 = [
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents Day
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
]

# ---------------------------------------------------------------------------
# Loan mix (Phase 3 loan_dim.loan_type)
# ---------------------------------------------------------------------------
LOAN_TYPES = {
    "Auto": 0.42,
    "Personal": 0.28,
    "Credit Card": 0.18,
    "HELOC": 0.08,
    "Mortgage": 0.04,
}
LOAN_TYPE_TERMS = {  # (min_months, max_months)
    "Auto": (36, 72),
    "Personal": (12, 60),
    "Credit Card": (0, 0),  # revolving, modeled as term=0
    "HELOC": (60, 180),
    "Mortgage": (180, 360),
}
LOAN_TYPE_AMOUNT_RANGE = {  # (min, max) origination amount USD
    "Auto": (8_000, 55_000),
    "Personal": (2_000, 35_000),
    "Credit Card": (500, 25_000),
    "HELOC": (10_000, 150_000),
    "Mortgage": (120_000, 650_000),
}
LOAN_TYPE_RATE_RANGE = {  # (min, max) APR
    "Auto": (0.045, 0.11),
    "Personal": (0.08, 0.22),
    "Credit Card": (0.15, 0.26),
    "HELOC": (0.06, 0.10),
    "Mortgage": (0.055, 0.075),
}

# ---------------------------------------------------------------------------
# Application / origination funnel (Phase 4 Section 3 state machine)
# ---------------------------------------------------------------------------
APPROVAL_RATE = 0.92  # 8% declined

# ---------------------------------------------------------------------------
# Customer relationship structure (Phase 4 scenario #18, #19)
# ---------------------------------------------------------------------------
PCT_CUSTOMERS_WITH_2_LOANS = 0.20
PCT_CUSTOMERS_WITH_3PLUS_LOANS = 0.05
PCT_LOANS_JOINT = 0.15
PCT_CUSTOMERS_RELOCATED = 0.05  # scenario #17

# ---------------------------------------------------------------------------
# Risk bands (Phase 3 risk_band_dim)
# ---------------------------------------------------------------------------
RISK_BANDS = [
    # code, name, score_low, score_high, approx population weight
    ("R1", "Super Prime", 780, 850, 0.14),
    ("R2", "Prime Plus", 740, 779, 0.18),
    ("R3", "Prime", 700, 739, 0.22),
    ("R4", "Near Prime", 660, 699, 0.20),
    ("R5", "Subprime", 620, 659, 0.15),
    ("R6", "Deep Subprime", 580, 619, 0.08),
    ("R7", "High Risk", 300, 579, 0.03),
]
RISK_BAND_DEFINITION_VERSION = "v2.1"

# Base monthly probability a due-date is missed, by risk band (worse band
# -> higher miss probability). Calibrated so ~30% of loans experience at
# least one delinquency episode across the 6-month window (Phase 4 Section 4).
MISS_PAYMENT_PROB_BY_BAND = {
    "R1": 0.010,
    "R2": 0.018,
    "R3": 0.028,
    "R4": 0.045,
    "R5": 0.075,
    "R6": 0.110,
    "R7": 0.160,
}

# Once delinquent, monthly probability of curing (returning to Current) by
# how many buckets deep the loan currently is (0=1-29, 1=30-59, 2=60-89, 3=90+)
CURE_PROB_BY_DEPTH = [0.55, 0.35, 0.20, 0.08]

# Once delinquent, monthly probability the missed-payment / no-cure loan
# additionally receives a restructuring offer it accepts (only offered at
# 30-59 depth or worse) -- Phase 4 scenario #9
RESTRUCTURE_PROB_PER_CYCLE = 0.06

# Once at 90+ (depth 3) and not cured/restructured, probability per 30-day
# cycle spent at 90+ that the loan charges off once it has been at 90+ for
# at least one full cycle -- Phase 4 scenario #8 (target ~2% of loans overall)
CHARGE_OFF_PROB_PER_CYCLE_AT_90PLUS = 0.35

# Of charged-off loans, fraction that reach a settlement (Phase 4 scenario #10)
PCT_CHARGED_OFF_SETTLED = 0.30

# Fraud flag (Phase 4 scenario #11) - independent random event
PCT_LOANS_FRAUD_FLAGGED = 0.005

# ---------------------------------------------------------------------------
# Collectors (Phase 3 collector_dim)
# ---------------------------------------------------------------------------
N_COLLECTORS = 120
COLLECTOR_TEAMS = ["Early Stage 1-29", "Mid Stage 30-59", "Late Stage 60-89",
                    "Late Stage 90+", "Recovery"]
COLLECTOR_REORG_DAY_OFFSET = 120  # ~month 4 into the window (scenario #12)
PCT_COLLECTORS_REASSIGNED_AT_REORG = 0.40

# ---------------------------------------------------------------------------
# Channels (Phase 3 channel_dim)
# ---------------------------------------------------------------------------
CHANNELS = [
    # code, name, category, is_digital, is_outbound
    ("OUTBOUND_CALL", "Outbound Agent Call", "Live Agent", False, True),
    ("INBOUND_CALL", "Inbound Customer Call", "Live Agent", False, False),
    ("SMS", "SMS Reminder", "Automated", True, True),
    ("EMAIL", "Email Reminder", "Automated", True, True),
    ("IVR", "Interactive Voice Response", "Automated", False, True),
    ("LETTER", "Collections Letter", "Written", False, True),
    ("MOBILE_PUSH", "Mobile App Push Notification", "Digital Self-Serve", True, True),
    ("ACH", "ACH Payment", "Digital Self-Serve", True, False),
    ("BRANCH", "In-Branch Payment", "Live Agent", False, False),
]

RPC_PROB_BY_CHANNEL_CATEGORY = {  # right-party-contact probability
    "Live Agent": 0.55,
    "Automated": 0.85,  # SMS/email/IVR "delivered" counted generously as RPC-ish; see contact_outcome logic
    "Digital Self-Serve": 0.0,  # payment channels, not contact attempts
    "Written": 0.30,
}
PTP_PROB_GIVEN_RPC_OUTBOUND_LIVE_AGENT = 0.55
PTP_KEEP_PROB = 0.65  # of PTPs made, fraction ultimately Kept (vs Broken/Partial)

# ---------------------------------------------------------------------------
# Payment behavior (Phase 3 payment_fact)
# ---------------------------------------------------------------------------
PCT_PAYMENTS_EXTRA = 0.10          # extra/principal-curtailment payments
PCT_PAYMENTS_REVERSED = 0.02       # scenario #6
PCT_ACH_PAYMENTS_RETURNED_NSF = 0.015  # scenario #7
PAYMENT_METHODS = ["ACH", "Debit Card", "Check", "Wire", "Cash"]
PAYMENT_METHOD_WEIGHTS = [0.55, 0.20, 0.15, 0.05, 0.05]

# ---------------------------------------------------------------------------
# Data messiness injection rates (Phase 4 Section 5)
# ---------------------------------------------------------------------------
PCT_LATE_ARRIVING_PAYMENTS = 0.04          # scenario #1
PCT_BUREAU_CUSTOMERS_DELAYED = 0.05        # scenario #2
BUREAU_OUTAGE_DAY_OFFSETS = [45, 46]       # 2 days with zero bureau file, scenario #2
SCHEMA_DRIFT_ADD_COLUMN_DAY_OFFSET = 60    # scenario #3
SCHEMA_DRIFT_RENAME_DAY_OFFSET = 100       # scenario #4
PCT_DUPLICATE_PAYMENT_EVENTS = 0.01        # scenario #5
PCT_DUPLICATE_CONTACT_EVENTS = 0.01        # scenario #5
PCT_CORRUPT_RECORDS = 0.003                # scenario #13

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
OUTPUT_DIR = "data/synthetic/output"
