"""
Core lifecycle simulator: walks the Phase 4 Section 3 state machine for
every loan across the analysis window, producing:

  * `delinquency_daily_df` — one row per loan per active day
    (feeds Bronze raw_servicing daily extract -> Silver/Gold delinquency_fact)
  * `payment_events_df` — scheduled/extra payment events at/near due dates
    (feeds Bronze raw_payments -> Silver/Gold payment_fact)
  * `loan_events_df` — restructure / charge-off / settlement / fraud events
    (feeds loan_dim SCD2 versioning)

DPD definition: days since the first unpaid due date in the current
delinquency episode. Resets to 0 the instant the loan cures or is
restructured; freezes once charged off.

NOTE ON SIMPLIFICATION: outstanding balance is amortized on a simple
straight-line basis (origination_amount / effective_term), not a true
actuarial amortization schedule -- adequate for realistic-looking
portfolio analytics without needing a full loan-amortization engine.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

BUCKET_LABELS = {
    0: "Current", 1: "1-29", 2: "30-59", 3: "60-89", 4: "90+",
    5: "Charged-off", 6: "Settled",
}


def _due_dates_for_loan(disbursement_date: pd.Timestamp, due_day: int) -> list[pd.Timestamp]:
    dates = []
    # first due date: due_day in the month after disbursement (grace period)
    cursor = (disbursement_date.replace(day=1) + pd.DateOffset(months=1))
    while True:
        try:
            due = cursor.replace(day=min(due_day, 28))
        except ValueError:
            due = cursor.replace(day=28)
        if due > pd.Timestamp(cfg.WINDOW_END):
            break
        if due >= disbursement_date:
            dates.append(due)
        cursor = cursor + pd.DateOffset(months=1)
    return dates


def simulate(loans_df: pd.DataFrame):
    rng = np.random.default_rng(cfg.RANDOM_SEED)

    daily_rows = []
    payment_rows = []
    loan_event_rows = []

    window_start = pd.Timestamp(cfg.WINDOW_START)
    window_end = pd.Timestamp(cfg.WINDOW_END)

    for _, loan in loans_df.iterrows():
        loan_id = loan["loan_id"]
        customer_id = loan["primary_customer_id"]
        risk_band = loan["risk_band_code"]
        disb_date = pd.Timestamp(loan["disbursement_date"])
        due_day = int(loan["due_day_of_month"])
        term_months = loan["loan_term_months"] or 24
        origination_amount = loan["origination_amount"]
        monthly_installment = round(origination_amount / max(term_months, 24), 2)

        miss_prob_base = cfg.MISS_PAYMENT_PROB_BY_BAND[risk_band]
        outstanding = origination_amount

        bucket_index = 0
        dpd = 0
        restructured = False
        charged_off = False
        settled = False
        fraud_flagged = False
        fraud_flag_date = None

        # Independent fraud event, may occur any active day (scenario #11)
        if rng.random() < cfg.PCT_LOANS_FRAUD_FLAGGED:
            active_days = (window_end - max(disb_date, window_start)).days
            if active_days > 0:
                fraud_flag_date = max(disb_date, window_start) + pd.Timedelta(
                    days=int(rng.integers(0, active_days))
                )

        due_dates = _due_dates_for_loan(disb_date, due_day)
        segment_start = max(disb_date, window_start)
        cursor_bucket = 0
        cursor_dpd = 0

        for cycle_idx, due_date in enumerate(due_dates):
            segment_end = min(due_date, window_end)

            # --- fill daily rows for [segment_start, segment_end) at CURRENT cycle state ---
            # (clipped to window_start -- pre-window due-date cycles for seasoned
            # loans still drive state transitions, but must never emit rows
            # dated before the analysis window opens)
            fill_start = max(segment_start, window_start)
            if segment_end > fill_start:
                n = (segment_end - fill_start).days
                for d in range(n):
                    day = fill_start + pd.Timedelta(days=d)
                    if charged_off or settled:
                        continue
                    row_bucket = cursor_bucket
                    days_into_segment = (day - segment_start).days
                    row_dpd = cursor_dpd + days_into_segment if cursor_bucket > 0 else 0
                    daily_rows.append((loan_id, customer_id, day, row_bucket, row_dpd,
                                        restructured, fraud_flagged, outstanding))

            if charged_off or settled:
                segment_start = segment_end
                continue

            in_window = due_date >= window_start

            # activate fraud hold if its date has arrived
            if fraud_flag_date is not None and due_date >= fraud_flag_date and not fraud_flagged:
                fraud_flagged = True
                if in_window:
                    loan_event_rows.append((loan_id, "FRAUD_FLAG", fraud_flag_date, None))

            # --- decision at the due date ---
            if cursor_bucket == 0:
                miss = rng.random() < miss_prob_base
                if miss:
                    cursor_bucket = 1
                    cursor_dpd = 1
                else:
                    if in_window:
                        payment_rows.append((loan_id, customer_id, due_date, monthly_installment,
                                              monthly_installment, "Scheduled"))
                    outstanding = max(0.0, outstanding - monthly_installment * 0.75)
            else:
                depth = cursor_bucket - 1  # 0..3 for buckets 1..4
                cure_p = cfg.CURE_PROB_BY_DEPTH[depth]
                cured = rng.random() < cure_p
                if cured:
                    past_due_catchup = monthly_installment * (cursor_bucket)
                    if in_window:
                        payment_rows.append((loan_id, customer_id, due_date, past_due_catchup,
                                              monthly_installment, "Scheduled"))
                    outstanding = max(0.0, outstanding - monthly_installment * 0.75)
                    cursor_bucket = 0
                    cursor_dpd = 0
                else:
                    do_restructure = (depth >= 1) and (rng.random() < cfg.RESTRUCTURE_PROB_PER_CYCLE) and not restructured
                    if do_restructure:
                        restructured = True
                        if in_window:
                            loan_event_rows.append((loan_id, "RESTRUCTURE", due_date,
                                                     f"new_rate_reduction=0.02;new_term_months={term_months + 12}"))
                        cursor_bucket = 0
                        cursor_dpd = 0
                    elif cursor_bucket == 4:
                        # already at 90+, evaluate charge-off
                        if rng.random() < cfg.CHARGE_OFF_PROB_PER_CYCLE_AT_90PLUS:
                            charged_off = True
                            co_date = due_date
                            if in_window:
                                loan_event_rows.append((loan_id, "CHARGE_OFF", co_date, f"balance={outstanding:.2f}"))
                            # settlement sub-scenario
                            if rng.random() < cfg.PCT_CHARGED_OFF_SETTLED:
                                settle_date = co_date + pd.Timedelta(days=int(rng.integers(15, 60)))
                                if settle_date <= window_end and settle_date >= window_start:
                                    settle_amount = round(outstanding * rng.uniform(0.35, 0.65), 2)
                                    payment_rows.append((loan_id, customer_id, settle_date, settle_amount,
                                                          outstanding, "Settlement"))
                                    settled = True
                                    loan_event_rows.append((loan_id, "SETTLEMENT", settle_date,
                                                             f"settled_amount={settle_amount:.2f}"))
                            # one more delinquency-fact row at the charge-off bucket, then freeze
                            if in_window:
                                daily_rows.append((loan_id, customer_id, co_date, 5, cursor_dpd,
                                                    restructured, fraud_flagged, outstanding))
                        else:
                            cursor_dpd += 30  # stays at 90+, another cycle deeper
                    else:
                        cursor_bucket = min(cursor_bucket + 1, 4)
                        cursor_dpd += 30

            segment_start = segment_end

        # tail: fill remaining days after the last due date to window_end
        tail_start = max(segment_start, window_start)
        if tail_start <= window_end and not charged_off and not settled:
            n = (window_end - tail_start).days + 1
            for d in range(n):
                day = tail_start + pd.Timedelta(days=d)
                days_into_segment = (day - segment_start).days
                row_dpd = cursor_dpd + days_into_segment if cursor_bucket > 0 else 0
                daily_rows.append((loan_id, customer_id, day, cursor_bucket, row_dpd,
                                    restructured, fraud_flagged, outstanding))

    daily_df = pd.DataFrame(daily_rows, columns=[
        "loan_id", "customer_id", "snapshot_date", "bucket_index", "dpd",
        "restructured_flag", "fraud_flag", "outstanding_balance",
    ])
    daily_df["delinquency_bucket"] = daily_df["bucket_index"].map(BUCKET_LABELS)
    daily_df = daily_df.sort_values(["loan_id", "snapshot_date"]).drop_duplicates(
        ["loan_id", "snapshot_date"], keep="last"
    ).reset_index(drop=True)

    payments_df = pd.DataFrame(payment_rows, columns=[
        "loan_id", "customer_id", "payment_date", "payment_amount",
        "scheduled_amount", "payment_type",
    ])

    loan_events_df = pd.DataFrame(loan_event_rows, columns=[
        "loan_id", "event_type", "event_date", "details",
    ])

    return daily_df, payments_df, loan_events_df
