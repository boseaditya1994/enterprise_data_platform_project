"""
Post-processes the "clean" simulated event streams to inject the
realistic messiness scenarios from Phase 4 Section 5:
  #1 late-arriving payments      #5 duplicate events
  #6 payment reversals           #7 returned (NSF) payments
  #13 corrupt records            (extra/curtailment payments, for realism)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg


def finalize_payments(payments_df: pd.DataFrame, loans_df: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.RANDOM_SEED + 5)
    df = payments_df.copy()

    # --- assign payment method ---
    df["payment_method"] = rng.choice(
        cfg.PAYMENT_METHODS, size=len(df), p=cfg.PAYMENT_METHOD_WEIGHTS
    )
    df["payment_status"] = "Posted"
    df["is_reversal_flag"] = False
    df["nsf_flag"] = False
    df["original_payment_id"] = None

    # --- extra / curtailment payments (realism, not a listed defect scenario) ---
    loan_ids = loans_df["loan_id"].tolist()
    n_extra = int(len(df) * cfg.PCT_PAYMENTS_EXTRA)
    extra_loan_ids = rng.choice(loan_ids, size=n_extra)
    window_start, window_end = pd.Timestamp(cfg.WINDOW_START), pd.Timestamp(cfg.WINDOW_END)
    extra_rows = []
    for lid in extra_loan_ids:
        cust = loans_df.loc[loans_df["loan_id"] == lid, "primary_customer_id"].iloc[0]
        pay_date = window_start + pd.Timedelta(days=int(rng.integers(0, (window_end - window_start).days)))
        amt = round(rng.uniform(25, 400), 2)
        extra_rows.append({
            "loan_id": lid, "customer_id": cust, "payment_date": pay_date,
            "payment_amount": amt, "scheduled_amount": 0.0, "payment_type": "Extra",
            "payment_method": rng.choice(cfg.PAYMENT_METHODS, p=cfg.PAYMENT_METHOD_WEIGHTS),
            "payment_status": "Posted", "is_reversal_flag": False, "nsf_flag": False,
            "original_payment_id": None,
        })
    df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)

    df = df.sort_values("payment_date").reset_index(drop=True)
    df.insert(0, "payment_id", [f"PMT-{9000000 + i}" for i in range(len(df))])

    # --- scenario #6: reversals on ~2% of Scheduled payments ---
    scheduled_idx = df.index[df["payment_type"] == "Scheduled"]
    n_reversed = int(len(scheduled_idx) * cfg.PCT_PAYMENTS_REVERSED)
    reversed_idx = rng.choice(scheduled_idx, size=n_reversed, replace=False)
    reversal_rows = []
    for idx in reversed_idx:
        orig = df.loc[idx]
        rev_date = orig["payment_date"] + pd.Timedelta(days=int(rng.integers(1, 4)))
        reversal_rows.append({
            "payment_id": f"{orig['payment_id']}-REV", "loan_id": orig["loan_id"],
            "customer_id": orig["customer_id"], "payment_date": rev_date,
            "payment_amount": -orig["payment_amount"], "scheduled_amount": orig["scheduled_amount"],
            "payment_type": orig["payment_type"], "payment_method": orig["payment_method"],
            "payment_status": "Reversed", "is_reversal_flag": True, "nsf_flag": False,
            "original_payment_id": orig["payment_id"],
        })
    df = pd.concat([df, pd.DataFrame(reversal_rows)], ignore_index=True)

    # --- scenario #7: NSF returns on ~1.5% of ACH payments ---
    ach_idx = df.index[(df["payment_method"] == "ACH") & (df["payment_status"] == "Posted")]
    n_returned = int(len(ach_idx) * cfg.PCT_ACH_PAYMENTS_RETURNED_NSF)
    returned_idx = rng.choice(ach_idx, size=n_returned, replace=False)
    df.loc[returned_idx, "payment_status"] = "Returned"
    df.loc[returned_idx, "nsf_flag"] = True

    # --- scenario #1: late-arriving payments (ingestion_date lags payment/effective date) ---
    df["effective_date"] = df["payment_date"]
    df["ingestion_date"] = df["payment_date"]
    late_mask = rng.random(len(df)) < cfg.PCT_LATE_ARRIVING_PAYMENTS
    late_offsets = rng.integers(2, 11, size=late_mask.sum())
    df.loc[late_mask, "ingestion_date"] = (
        df.loc[late_mask, "payment_date"] + pd.to_timedelta(late_offsets, unit="D")
    )
    df["is_late_arrival"] = late_mask

    return df.reset_index(drop=True)


def inject_duplicates(df: pd.DataFrame, pct: float, seed_offset: int) -> pd.DataFrame:
    """Scenario #5: duplicate a random subset of rows with a fresh ingestion retry."""
    rng = np.random.default_rng(cfg.RANDOM_SEED + seed_offset)
    n_dupe = int(len(df) * pct)
    if n_dupe == 0:
        return df
    dupes = df.sample(n=n_dupe, random_state=cfg.RANDOM_SEED + seed_offset).copy()
    return pd.concat([df, dupes], ignore_index=True)


def inject_corrupt_records(df: pd.DataFrame, amount_col: str | None, seed_offset: int) -> pd.DataFrame:
    """
    Scenario #13: ~0.3% of rows get a malformed value simulating an
    upstream extraction glitch (null a required field, or negate a
    normally-positive amount). These rows are intentionally left in the
    raw extract -- Phase 6/14's quarantine logic is what should catch them.
    """
    rng = np.random.default_rng(cfg.RANDOM_SEED + seed_offset)
    df = df.copy()
    n_corrupt = int(len(df) * cfg.PCT_CORRUPT_RECORDS)
    if n_corrupt == 0:
        return df
    idx = rng.choice(df.index, size=n_corrupt, replace=False)
    half = len(idx) // 2
    if amount_col and amount_col in df.columns:
        df.loc[idx[:half], amount_col] = -abs(df.loc[idx[:half], amount_col].fillna(1))
    null_target_col = "customer_id" if "customer_id" in df.columns else df.columns[0]
    df.loc[idx[half:], null_target_col] = None
    df.loc[idx, "is_corrupt_record"] = True
    df["is_corrupt_record"] = df["is_corrupt_record"].fillna(False)
    return df
