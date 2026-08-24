"""
Advances the real-time loan simulation by exactly one calendar day.
"""
import sys
import os
import uuid
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))
import config  # noqa: E402

BUCKET_NAMES = {0: "Current", 1: "1-29", 2: "30-59", 3: "60-89", 4: "90+", 5: "Charged-off"}
TEAM_BY_BUCKET = {1: "Early Stage 1-29", 2: "Mid Stage 30-59", 3: "Late Stage 60-89", 4: "Late Stage 90+"}

RNG = np.random.default_rng()


def _scheduled_payment(origination_amount, annual_rate, term_months, outstanding_balance, loan_type=None):
    if term_months == 0 or loan_type == "Credit Card":
        return max(outstanding_balance * 0.02, 25.0)
    r = annual_rate / 12
    if r == 0:
        return origination_amount / term_months
    return origination_amount * r / (1 - (1 + r) ** (-term_months))


def advance_one_day(state_df: pd.DataFrame, pending_ptps_df: pd.DataFrame,
                     collector_roster: pd.DataFrame, target_date: pd.Timestamp, rng=None):
    rng = rng or RNG
    day_of_month = target_date.day
    state = state_df.copy()
    team_collectors = {team: grp["collector_id"].tolist() for team, grp in collector_roster.groupby("team_name")}

    payments, contacts, ptps_new, ptps_resolved = [], [], [], []

    still_pending = []
    for _, ptp in pending_ptps_df.iterrows():
        if pd.Timestamp(ptp["ptp_promised_date"]) <= target_date:
            kept = rng.random() < config.PTP_KEEP_PROB
            status = "Kept" if kept else ("Partial" if rng.random() < 0.3 else "Broken")
            amount_paid = ptp["ptp_amount"] if status == "Kept" else (ptp["ptp_amount"] * rng.uniform(0.2, 0.8) if status == "Partial" else 0.0)
            ptps_resolved.append({**ptp.to_dict(), "ptp_status": status,
                                   "amount_paid_against_ptp": round(amount_paid, 2),
                                   "fulfillment_date": target_date.date().isoformat() if status != "Broken" else None})
        else:
            still_pending.append(ptp)
    new_pending_ptps_df = pd.DataFrame(still_pending) if still_pending else pd.DataFrame(columns=pending_ptps_df.columns)

    due_today = state["due_day_of_month"] == day_of_month
    n_due = due_today.sum()

    for idx in state[due_today].index:
        row = state.loc[idx]
        risk_band = row["risk_band_code"]
        bucket = int(row["bucket_index"])
        sched_pmt = _scheduled_payment(row["origination_amount"], row["interest_rate"],
                                        row["loan_term_months"], row["outstanding_balance"], row["loan_type"])

        if bucket == 0:
            miss_prob = config.MISS_PAYMENT_PROB_BY_BAND[risk_band]
            if rng.random() < miss_prob:
                state.loc[idx, "bucket_index"] = 1
                state.loc[idx, "delinquency_bucket"] = BUCKET_NAMES[1]
                state.loc[idx, "dpd"] = rng.integers(1, 30)
            else:
                state.loc[idx, "dpd"] = 0
                payments.append(_make_payment_row(row, target_date, sched_pmt))

        elif 1 <= bucket <= 4:
            depth = bucket - 1
            cure_prob = config.CURE_PROB_BY_DEPTH[depth]

            if rng.random() < cure_prob:
                state.loc[idx, "bucket_index"] = 0
                state.loc[idx, "delinquency_bucket"] = BUCKET_NAMES[0]
                state.loc[idx, "dpd"] = 0
                payments.append(_make_payment_row(row, target_date, sched_pmt))
            else:
                if bucket >= 2 and not row["restructured_flag"] and rng.random() < config.RESTRUCTURE_PROB_PER_CYCLE:
                    state.loc[idx, "restructured_flag"] = True

                if bucket == 4 and rng.random() < config.CHARGE_OFF_PROB_PER_CYCLE_AT_90PLUS:
                    state.loc[idx, "bucket_index"] = 5
                    state.loc[idx, "delinquency_bucket"] = BUCKET_NAMES[5]
                    state.loc[idx, "charge_off_flag"] = True
                else:
                    new_bucket = min(bucket + 1, 4)
                    state.loc[idx, "bucket_index"] = new_bucket
                    state.loc[idx, "delinquency_bucket"] = BUCKET_NAMES[new_bucket]
                    state.loc[idx, "dpd"] = row["dpd"] + 30

                if rng.random() < 0.6:
                    team = TEAM_BY_BUCKET.get(bucket, "Mid Stage 30-59")
                    collector_id = rng.choice(team_collectors.get(team, collector_roster["collector_id"].tolist()))
                    contact_row = _make_contact_row(row, target_date, collector_id, rng)
                    contacts.append(contact_row)
                    if contact_row["is_rpc_flag"] and rng.random() < config.PTP_PROB_GIVEN_RPC_OUTBOUND_LIVE_AGENT:
                        ptps_new.append(_make_open_ptp_row(row, target_date, contact_row["contact_id"], collector_id, rng))

    snapshot = state[["loan_id", "customer_id", "bucket_index", "delinquency_bucket", "dpd",
                       "outstanding_balance", "restructured_flag", "fraud_flag"]].copy()
    snapshot["snapshot_date"] = target_date.date().isoformat()

    all_ptp_rows = ptps_new + ptps_resolved
    if ptps_new:
        new_pending_ptps_df = pd.concat([new_pending_ptps_df, pd.DataFrame(ptps_new)], ignore_index=True)

    events = {
        "delinquency_snapshot": snapshot,
        "payments": pd.DataFrame(payments) if payments else pd.DataFrame(),
        "contacts": pd.DataFrame(contacts) if contacts else pd.DataFrame(),
        "ptp": pd.DataFrame(all_ptp_rows) if all_ptp_rows else pd.DataFrame(),
    }

    print(f"  {target_date.date()}: {n_due} due, {len(payments)} payments, {len(contacts)} contacts, "
          f"{len(ptps_new)} new PTPs, {len(ptps_resolved)} PTPs resolved, "
          f"bucket dist -> {state['bucket_index'].value_counts().sort_index().to_dict()}")

    return state, new_pending_ptps_df, events


def _make_payment_row(loan_row, target_date, amount):
    ts = target_date.date().isoformat()
    return {
        "payment_id": f"PMT-RT-{uuid.uuid4().hex[:10]}",
        "loan_id": loan_row["loan_id"], "customer_id": loan_row["customer_id"],
        "payment_date": ts, "payment_amount": round(amount, 2), "scheduled_amount": round(amount, 2),
        "payment_type": "Scheduled", "payment_method": np.random.choice(config.PAYMENT_METHODS, p=config.PAYMENT_METHOD_WEIGHTS),
        "payment_status": "Posted", "is_reversal_flag": False, "nsf_flag": False, "original_payment_id": None,
        "effective_date": ts, "ingestion_date": ts, "is_late_arrival": False, "is_corrupt_record": False,
    }


def _make_contact_row(loan_row, target_date, collector_id, rng):
    is_rpc = rng.random() < config.RPC_PROB_BY_CHANNEL_CATEGORY["Live Agent"]
    return {
        "contact_id": f"CNT-RT-{uuid.uuid4().hex[:10]}",
        "loan_id": loan_row["loan_id"], "customer_id": loan_row["customer_id"],
        "contact_date": target_date.date().isoformat(), "collector_id": collector_id,
        "channel_code": "OUTBOUND_CALL", "contact_direction": "Outbound",
        "contact_outcome": "RPC" if is_rpc else "No Answer", "is_rpc_flag": is_rpc,
        "call_duration_seconds": int(rng.integers(60, 600)) if is_rpc else 0,
        "complaint_flag": False, "source_system": "CALL_CENTER", "is_corrupt_record": False,
    }


def _make_open_ptp_row(loan_row, target_date, contact_id, collector_id, rng):
    return {
        "ptp_id": f"PTP-RT-{uuid.uuid4().hex[:10]}",
        "loan_id": loan_row["loan_id"], "customer_id": loan_row["customer_id"], "contact_id": contact_id,
        "collector_ref_id": collector_id, "ptp_created_date": target_date.date().isoformat(),
        "ptp_promised_date": (target_date + pd.Timedelta(days=7)).date().isoformat(),
        "ptp_amount": round(loan_row["outstanding_balance"] * 0.1, 2),
        "ptp_status": "Open", "amount_paid_against_ptp": 0.0, "fulfillment_date": None,
    }