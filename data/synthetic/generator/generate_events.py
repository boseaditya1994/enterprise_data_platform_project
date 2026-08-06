"""
Generates contact_fact-feeding events (Call Center + Collections Platform
contact attempts, plus routine automated reminders) and
promise_to_pay_fact-feeding events, driven by the daily delinquency state
produced by simulate_lifecycle.simulate().
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

BUCKET_TO_TEAM = {
    1: "Early Stage 1-29",
    2: "Mid Stage 30-59",
    3: "Late Stage 60-89",
    4: "Late Stage 90+",
    5: "Recovery",
}

CONTACT_CHANNELS = ["OUTBOUND_CALL", "SMS", "IVR", "EMAIL", "LETTER"]
CONTACT_CHANNEL_WEIGHTS = [0.35, 0.25, 0.15, 0.15, 0.10]
CHANNEL_CATEGORY = {c[0]: c[2] for c in cfg.CHANNELS}

CONTACT_DAILY_PROB_BY_DEPTH = {1: 0.09, 2: 0.16, 3: 0.22, 4: 0.28, 5: 0.10}
REMINDER_DAILY_PROB = 0.015  # routine automated reminders to any active loan

LIVE_AGENT_OUTCOMES = ["Right Party Contact", "Wrong Party", "No Answer", "Voicemail", "Busy"]
LIVE_AGENT_OUTCOME_WEIGHTS = [0.55, 0.10, 0.20, 0.10, 0.05]
AUTOMATED_OUTCOMES = ["Delivered", "Undeliverable"]
AUTOMATED_OUTCOME_WEIGHTS = [0.85, 0.15]
WRITTEN_OUTCOMES = ["Delivered", "Returned Mail"]
WRITTEN_OUTCOME_WEIGHTS = [0.90, 0.10]


def _build_collector_lookup(collectors_df: pd.DataFrame):
    reorg_date = pd.Timestamp(cfg.WINDOW_START) + pd.Timedelta(days=cfg.COLLECTOR_REORG_DAY_OFFSET)
    pre = collectors_df[collectors_df["change_reason"] == "INITIAL_LOAD"]
    post = collectors_df.sort_values("source_updated_at").groupby("collector_id").last().reset_index()

    pre_by_team = pre.groupby("team_name")["collector_id"].apply(list).to_dict()
    post_by_team = post.groupby("team_name")["collector_id"].apply(list).to_dict()
    return reorg_date, pre_by_team, post_by_team


def _pick_collector(team, date, reorg_date, pre_by_team, post_by_team, rng):
    lookup = pre_by_team if date < reorg_date else post_by_team
    pool = lookup.get(team) or pre_by_team.get(team) or ["COL-1000"]
    return pool[int(rng.integers(0, len(pool)))]


def generate_contacts(daily_df: pd.DataFrame, collectors_df: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.RANDOM_SEED + 1)
    reorg_date, pre_by_team, post_by_team = _build_collector_lookup(collectors_df)

    rows = []

    # --- Delinquency-driven contacts ---
    delinquent = daily_df[daily_df["bucket_index"].between(1, 5)]
    for depth, prob in CONTACT_DAILY_PROB_BY_DEPTH.items():
        subset = delinquent[delinquent["bucket_index"] == depth]
        if subset.empty:
            continue
        mask = rng.random(len(subset)) < prob
        chosen = subset[mask]
        for _, r in chosen.iterrows():
            channel = str(rng.choice(CONTACT_CHANNELS, p=CONTACT_CHANNEL_WEIGHTS))
            category = CHANNEL_CATEGORY[channel]
            team = BUCKET_TO_TEAM[depth]
            collector_id = _pick_collector(team, r["snapshot_date"], reorg_date,
                                            pre_by_team, post_by_team, rng) if category == "Live Agent" else None

            if category == "Live Agent":
                outcome = str(rng.choice(LIVE_AGENT_OUTCOMES, p=LIVE_AGENT_OUTCOME_WEIGHTS))
                is_rpc = outcome == "Right Party Contact"
                duration = int(rng.integers(45, 720)) if is_rpc else int(rng.integers(5, 45))
            elif category == "Automated":
                outcome = str(rng.choice(AUTOMATED_OUTCOMES, p=AUTOMATED_OUTCOME_WEIGHTS))
                is_rpc = outcome == "Delivered"
                duration = None
            else:  # Written
                outcome = str(rng.choice(WRITTEN_OUTCOMES, p=WRITTEN_OUTCOME_WEIGHTS))
                is_rpc = outcome == "Delivered"
                duration = None

            complaint = bool(rng.random() < 0.003)

            rows.append({
                "loan_id": r["loan_id"], "customer_id": r["customer_id"],
                "contact_date": r["snapshot_date"], "collector_id": collector_id,
                "channel_code": channel, "contact_direction": "Outbound",
                "contact_outcome": outcome, "is_rpc_flag": is_rpc,
                "call_duration_seconds": duration, "complaint_flag": complaint,
                "source_system": "CALL_CENTER" if channel == "OUTBOUND_CALL" else "COLLECTIONS_PLATFORM",
            })

    # --- Routine automated reminders (not delinquency-gated) ---
    active = daily_df[daily_df["bucket_index"] == 0]
    if len(active):
        mask = rng.random(len(active)) < REMINDER_DAILY_PROB
        reminders = active[mask]
        for _, r in reminders.iterrows():
            channel = str(rng.choice(["SMS", "EMAIL", "MOBILE_PUSH"], p=[0.5, 0.35, 0.15]))
            outcome = str(rng.choice(AUTOMATED_OUTCOMES, p=AUTOMATED_OUTCOME_WEIGHTS))
            rows.append({
                "loan_id": r["loan_id"], "customer_id": r["customer_id"],
                "contact_date": r["snapshot_date"], "collector_id": None,
                "channel_code": channel, "contact_direction": "Outbound",
                "contact_outcome": outcome, "is_rpc_flag": outcome == "Delivered",
                "call_duration_seconds": None, "complaint_flag": False,
                "source_system": "COLLECTIONS_PLATFORM",
            })

    contacts_df = pd.DataFrame(rows)
    contacts_df.insert(0, "contact_id", [f"CTC-{60000000 + i}" for i in range(len(contacts_df))])
    return contacts_df


def generate_promises_to_pay(contacts_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.RANDOM_SEED + 2)

    eligible = contacts_df[
        (contacts_df["channel_code"] == "OUTBOUND_CALL")
        & (contacts_df["contact_outcome"] == "Right Party Contact")
    ]
    mask = rng.random(len(eligible)) < cfg.PTP_PROB_GIVEN_RPC_OUTBOUND_LIVE_AGENT
    chosen = eligible[mask].copy()

    dpd_lookup = daily_df.set_index(["loan_id", "snapshot_date"])["dpd"].to_dict()

    rows = []
    for i, (_, c) in enumerate(chosen.iterrows()):
        promised_offset = int(rng.integers(2, 15))
        promised_date = c["contact_date"] + pd.Timedelta(days=promised_offset)
        dpd_now = dpd_lookup.get((c["loan_id"], c["contact_date"]), 30)
        ptp_amount = round(max(50.0, dpd_now * rng.uniform(3, 9)), 2)

        kept = rng.random() < cfg.PTP_KEEP_PROB
        if kept:
            status = "Kept"
            fulfillment_offset = int(rng.integers(0, promised_offset + 3))
            fulfillment_date = c["contact_date"] + pd.Timedelta(days=fulfillment_offset)
            amount_paid = ptp_amount
        else:
            partial = rng.random() < 0.4
            status = "Partial" if partial else "Broken"
            fulfillment_date = promised_date if partial else pd.NaT
            amount_paid = round(ptp_amount * rng.uniform(0.2, 0.7), 2) if partial else 0.0

        rows.append({
            "ptp_id": f"PTP-{700000 + i}",
            "loan_id": c["loan_id"], "customer_id": c["customer_id"],
            "contact_id": c["contact_id"], "collector_id": c["collector_id"],
            "ptp_created_date": c["contact_date"], "ptp_promised_date": promised_date,
            "ptp_amount": ptp_amount, "ptp_status": status,
            "amount_paid_against_ptp": amount_paid,
            "fulfillment_date": fulfillment_date,
        })

    return pd.DataFrame(rows)
