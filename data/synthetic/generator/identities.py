"""
Generates the "identity" layer: customers, collectors, loan applications
and resulting loans, and the joint-applicant bridge.

This corresponds to Phase 4 Section 2 entities #1-4 (Application, Customer,
Approval/Decline, Loan) and Section 5 scenarios #17 (relocation), #18
(multiple loans per customer), #19 (joint applicants).
"""
from __future__ import annotations

import random
import numpy as np
import pandas as pd
from faker import Faker

from . import config as cfg

fake = Faker()
Faker.seed(cfg.RANDOM_SEED)
random.seed(cfg.RANDOM_SEED)
np.random.seed(cfg.RANDOM_SEED)


def _weighted_choice(options, weights, size):
    return np.random.choice(options, size=size, p=np.array(weights) / np.sum(weights))


def generate_customers() -> pd.DataFrame:
    """One row per customer's ORIGINAL (pre-relocation) CRM record."""
    rows = []
    segments = ["Mass", "Affluent", "Private Bank"]
    segment_weights = [0.72, 0.24, 0.04]
    employment = ["Employed", "Self-Employed", "Retired", "Unemployed"]
    employment_weights = [0.72, 0.14, 0.10, 0.04]

    for i in range(cfg.N_CUSTOMERS):
        customer_id = f"CUST-{100000 + i}"
        first, last = fake.first_name(), fake.last_name()
        rows.append({
            "customer_id": customer_id,
            "first_name": first,
            "last_name": last,
            "date_of_birth": fake.date_of_birth(minimum_age=21, maximum_age=78),
            "ssn_last4": f"{random.randint(0, 9999):04d}",
            "email": f"{first.lower()}.{last.lower()}{random.randint(1,999)}@{fake.free_email_domain()}",
            "phone_number": fake.numerify("###-###-####"),
            "mailing_city": fake.city(),
            "mailing_state": fake.state_abbr(),
            "mailing_zip": fake.zipcode(),
            "customer_segment": np.random.choice(segments, p=segment_weights),
            "employment_status": np.random.choice(employment, p=employment_weights),
            "source_updated_at": pd.Timestamp(cfg.WINDOW_START),
            "source_system": "CRM",
            "change_reason": "INITIAL_LOAD",
        })
    return pd.DataFrame(rows)


def apply_relocations(customers_df: pd.DataFrame) -> pd.DataFrame:
    """
    Scenario #17: ~5% of customers relocate mid-window. Produces a SECOND
    CRM record (a later source_updated_at) with a new address -- this is
    the raw CDC-style change event Bronze/Silver will need to conform via
    SCD2 on customer_dim (Phase 3 Section 2.1).
    """
    n_relocated = int(len(customers_df) * cfg.PCT_CUSTOMERS_RELOCATED)
    relocated = customers_df.sample(n=n_relocated, random_state=cfg.RANDOM_SEED).copy()

    relocated["mailing_city"] = [fake.city() for _ in range(len(relocated))]
    relocated["mailing_state"] = [fake.state_abbr() for _ in range(len(relocated))]
    relocated["mailing_zip"] = [fake.zipcode() for _ in range(len(relocated))]
    offsets = np.random.randint(30, cfg.N_DAYS - 10, size=len(relocated))
    relocated["source_updated_at"] = [
        pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(days=int(o)) for o in offsets
    ]
    relocated["change_reason"] = "RELOCATION"

    return pd.concat([customers_df, relocated], ignore_index=True).sort_values(
        ["customer_id", "source_updated_at"]
    ).reset_index(drop=True)


def generate_collectors() -> pd.DataFrame:
    """
    Collector roster with a mid-window reorg event (scenario #12).
    Returns long-format: one row per (collector, effective version).
    """
    rows = []
    for i in range(cfg.N_COLLECTORS):
        collector_id = f"COL-{1000 + i}"
        team = random.choice(cfg.COLLECTOR_TEAMS)
        rows.append({
            "collector_id": collector_id,
            "collector_name": fake.name(),
            "hire_date": fake.date_between(start_date="-6y", end_date="-30d"),
            "team_name": team,
            "collector_level": np.random.choice(
                ["Junior", "Senior", "Team Lead"], p=[0.55, 0.35, 0.10]
            ),
            "manager_name": fake.name(),
            "is_active_flag": True,
            "source_updated_at": pd.Timestamp(cfg.WINDOW_START),
            "change_reason": "INITIAL_LOAD",
        })
    base = pd.DataFrame(rows)

    # Reorg: reassign ~40% of collectors to a different team mid-window
    reorg_date = pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(days=cfg.COLLECTOR_REORG_DAY_OFFSET)
    n_reassigned = int(len(base) * cfg.PCT_COLLECTORS_REASSIGNED_AT_REORG)
    reassigned = base.sample(n=n_reassigned, random_state=cfg.RANDOM_SEED).copy()
    reassigned["team_name"] = reassigned["team_name"].apply(
        lambda t: random.choice([x for x in cfg.COLLECTOR_TEAMS if x != t])
    )
    reassigned["source_updated_at"] = reorg_date
    reassigned["change_reason"] = "REORG"

    return pd.concat([base, reassigned], ignore_index=True).sort_values(
        ["collector_id", "source_updated_at"]
    ).reset_index(drop=True)


def _assign_loan_owners(n_loans: int, customer_ids: list[str]) -> list[str]:
    """
    Implements scenario #18: ~20% of customers get 2 loans, ~5% get 3+.
    Returns a list of length n_loans of owning customer_ids.
    """
    n_customers = len(customer_ids)
    n_two = int(n_customers * cfg.PCT_CUSTOMERS_WITH_2_LOANS)
    n_three_plus = int(n_customers * cfg.PCT_CUSTOMERS_WITH_3PLUS_LOANS)

    shuffled = customer_ids.copy()
    random.shuffle(shuffled)
    two_loan_custs = shuffled[:n_two]
    three_plus_custs = shuffled[n_two:n_two + n_three_plus]
    one_loan_custs = shuffled[n_two + n_three_plus:]

    owners = list(one_loan_custs)  # 1 loan each
    owners += [c for c in two_loan_custs for _ in range(2)]
    owners += [c for c in three_plus_custs for _ in range(random.choice([3, 4]))]

    random.shuffle(owners)
    # Trim or pad to exactly n_loans
    if len(owners) > n_loans:
        owners = owners[:n_loans]
    else:
        extra = np.random.choice(customer_ids, size=n_loans - len(owners)).tolist()
        owners += extra
    return owners


def generate_applications_and_loans(customer_ids: list[str]):
    """
    Generates the full application funnel (scenario: Application ->
    Approval/Decline -> Loan) per Phase 4 Section 3 state machine.
    Returns (applications_df, loans_df, joint_applicant_bridge_df).
    """
    n_applications = int(round(cfg.N_LOANS / cfg.APPROVAL_RATE))
    owners = _assign_loan_owners(n_applications, customer_ids)

    loan_types = list(cfg.LOAN_TYPES.keys())
    loan_type_weights = list(cfg.LOAN_TYPES.values())
    risk_codes = [b[0] for b in cfg.RISK_BANDS]
    risk_weights = [b[4] for b in cfg.RISK_BANDS]

    app_rows = []
    loan_rows = []
    bridge_rows = []

    for i in range(n_applications):
        app_id = f"APP-{200000 + i}"
        customer_id = owners[i]
        loan_type = np.random.choice(loan_types, p=loan_type_weights)
        risk_band_code = np.random.choice(risk_codes, p=risk_weights)
        approved = np.random.random() < cfg.APPROVAL_RATE

        # ~65% of applications represent an already-seasoned back-book loan
        # (originated before the analysis window even opens, so it has
        # full 6-month tenure inside the window); ~35% are new originations
        # that happen during the window itself. This mirrors a real,
        # live portfolio far better than assuming every loan is brand new.
        if np.random.random() < 0.65:
            app_date = pd.Timestamp(cfg.WINDOW_START) - pd.Timedelta(
                days=int(np.random.randint(30, 365))
            )
        else:
            app_date = pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(
                days=int(np.random.randint(0, max(1, cfg.N_DAYS - 30)))
            )
        decision = "Approved" if approved else "Declined"

        app_rows.append({
            "application_id": app_id,
            "customer_id": customer_id,
            "loan_type": loan_type,
            "requested_amount": round(np.random.uniform(*cfg.LOAN_TYPE_AMOUNT_RANGE[loan_type]), 2),
            "risk_band_code_at_decision": risk_band_code,
            "application_date": app_date,
            "decision": decision,
            "decision_date": app_date + pd.Timedelta(days=int(np.random.randint(1, 5))),
            "source_system": "RISK_ENGINE",
        })

        if not approved:
            continue

        loan_id = f"LN-{500000 + len(loan_rows)}"
        amt_lo, amt_hi = cfg.LOAN_TYPE_AMOUNT_RANGE[loan_type]
        rate_lo, rate_hi = cfg.LOAN_TYPE_RATE_RANGE[loan_type]
        term_lo, term_hi = cfg.LOAN_TYPE_TERMS[loan_type]

        origination_amount = round(np.random.uniform(amt_lo, amt_hi), 2)
        interest_rate = round(np.random.uniform(rate_lo, rate_hi), 4)
        term_months = int(np.random.randint(term_lo, term_hi + 1)) if term_lo else 0
        origination_date = app_rows[-1]["decision_date"] + pd.Timedelta(days=1)
        disbursement_date = origination_date + pd.Timedelta(days=int(np.random.randint(0, 3)))

        loan_rows.append({
            "loan_id": loan_id,
            "application_id": app_id,
            "primary_customer_id": customer_id,
            "loan_type": loan_type,
            "loan_sub_product": f"{loan_type} Standard",
            "origination_date": origination_date,
            "disbursement_date": disbursement_date,
            "origination_amount": origination_amount,
            "interest_rate": interest_rate,
            "loan_term_months": term_months,
            "is_secured_flag": loan_type in ("Auto", "HELOC", "Mortgage"),
            "collateral_type": {"Auto": "Vehicle", "HELOC": "Real Estate",
                                 "Mortgage": "Real Estate"}.get(loan_type, "None"),
            "due_day_of_month": int(np.random.randint(1, 29)),
            "risk_band_code": risk_band_code,
            "source_system": "LOAN_SERVICING",
        })

        # Joint applicant (scenario #19)
        if np.random.random() < cfg.PCT_LOANS_JOINT:
            co_customer_id = np.random.choice(customer_ids)
            tries = 0
            while co_customer_id == customer_id and tries < 5:
                co_customer_id = np.random.choice(customer_ids)
                tries += 1
            bridge_rows.append({
                "loan_id": loan_id,
                "customer_id": co_customer_id,
                "applicant_role": "Co-Applicant",
            })

    applications_df = pd.DataFrame(app_rows)
    loans_df = pd.DataFrame(loan_rows)
    bridge_df = pd.DataFrame(bridge_rows)
    return applications_df, loans_df, bridge_df
