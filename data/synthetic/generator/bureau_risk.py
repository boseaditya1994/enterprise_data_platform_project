"""
Generates Credit Bureau and Risk Engine monthly refresh extracts.

Implements Phase 4 scenario #2 (late-arriving / missing bureau files):
two full outage days with zero bureau records, plus ~5% of customers
delayed 1-2 weeks beyond the normal monthly file.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

RISK_BAND_SCORE_MID = {b[0]: (b[2] + b[3]) / 2 for b in cfg.RISK_BANDS}
RISK_BAND_BY_CODE = {b[0]: b for b in cfg.RISK_BANDS}


def _score_to_band(score: float) -> str:
    for code, name, lo, hi, _ in cfg.RISK_BANDS:
        if lo <= score <= hi:
            return code
    return cfg.RISK_BANDS[-1][0] if score < cfg.RISK_BANDS[-1][2] else cfg.RISK_BANDS[0][0]


def generate_bureau_extracts(loans_df: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.RANDOM_SEED + 3)
    window_start = pd.Timestamp(cfg.WINDOW_START)
    outage_dates = {window_start + pd.Timedelta(days=o) for o in cfg.BUREAU_OUTAGE_DAY_OFFSETS}

    # one customer-level bureau refresh per month
    month_starts = pd.date_range(cfg.WINDOW_START, cfg.WINDOW_END, freq="MS")
    customers = loans_df[["primary_customer_id", "risk_band_code"]].drop_duplicates("primary_customer_id")

    rows = []
    for month_start in month_starts:
        # nominal file date = 3rd of the month
        nominal_date = month_start + pd.Timedelta(days=2)
        if nominal_date in outage_dates:
            continue  # scenario #2: whole-file outage, nothing lands this month
        delayed_mask = rng.random(len(customers)) < cfg.PCT_BUREAU_CUSTOMERS_DELAYED
        for delayed, (_, cust) in zip(delayed_mask, customers.iterrows()):
            file_date = nominal_date + pd.Timedelta(days=int(rng.integers(7, 15))) if delayed else nominal_date
            base_mid = RISK_BAND_SCORE_MID.get(cust["risk_band_code"], 680)
            score = int(np.clip(rng.normal(base_mid, 12), 300, 850))
            rows.append({
                "customer_id": cust["primary_customer_id"],
                "file_date": nominal_date,
                "source_updated_at": file_date,
                "fico_score": score,
                "risk_band_code": _score_to_band(score),
                "is_late_arrival": bool(delayed),
                "source_system": "CREDIT_BUREAU",
            })
    return pd.DataFrame(rows)


def generate_risk_engine_extracts(loans_df: pd.DataFrame, loan_events_df: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.RANDOM_SEED + 4)
    month_starts = pd.date_range(cfg.WINDOW_START, cfg.WINDOW_END, freq="MS")

    rows = []
    for month_start in month_starts:
        file_date = month_start + pd.Timedelta(days=1)
        for _, loan in loans_df.iterrows():
            base_mid = RISK_BAND_SCORE_MID.get(loan["risk_band_code"], 680)
            score = int(np.clip(rng.normal(base_mid, 8), 300, 850))
            rows.append({
                "loan_id": loan["loan_id"], "customer_id": loan["primary_customer_id"],
                "file_date": file_date, "internal_risk_score": score,
                "risk_band_code": _score_to_band(score),
                "source_system": "RISK_ENGINE",
            })

    # fraud events surfaced as their own risk-engine records (scenario #11)
    fraud_events = loan_events_df[loan_events_df["event_type"] == "FRAUD_FLAG"]
    for _, e in fraud_events.iterrows():
        rows.append({
            "loan_id": e["loan_id"], "customer_id": None,
            "file_date": e["event_date"], "internal_risk_score": None,
            "risk_band_code": None, "fraud_flag": True,
            "source_system": "RISK_ENGINE",
        })

    df = pd.DataFrame(rows)
    if "fraud_flag" not in df.columns:
        df["fraud_flag"] = False
    df["fraud_flag"] = df["fraud_flag"].fillna(False)
    return df
