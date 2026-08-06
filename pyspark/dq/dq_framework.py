"""
Reusable Data Quality check library, called from ingest_bronze.py (Phase 6)
and the Silver merge jobs. Full DQ framework design (quarantine tables,
thresholds, dashboards, business-rule catalog) is Phase 14 -- this module
is the actual PySpark implementation the checks in Phase 6's
schema-drift/corrupt-record handling and Phase 14's broader framework both
call into, so it's built here where the execution layer lives.
"""
from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dataclass
class DQCheckResult:
    check_name: str
    table_name: str
    passed: bool
    failed_row_count: int
    total_row_count: int
    detail: str


def check_completeness(df: DataFrame, table_name: str, required_cols: list[str],
                        null_threshold_pct: float = 0.0) -> list[DQCheckResult]:
    """Fails if any required column's null rate exceeds threshold."""
    total = df.count()
    results = []
    for col in required_cols:
        null_count = df.filter(F.col(col).isNull()).count()
        null_pct = null_count / total if total else 0
        results.append(DQCheckResult(
            check_name=f"completeness__{col}", table_name=table_name,
            passed=null_pct <= null_threshold_pct, failed_row_count=null_count,
            total_row_count=total, detail=f"{null_pct:.2%} null (threshold {null_threshold_pct:.2%})",
        ))
    return results


def check_uniqueness(df: DataFrame, table_name: str, key_cols: list[str]) -> DQCheckResult:
    total = df.count()
    distinct = df.select(*key_cols).distinct().count()
    dupes = total - distinct
    return DQCheckResult(
        check_name=f"uniqueness__{'_'.join(key_cols)}", table_name=table_name,
        passed=(dupes == 0), failed_row_count=dupes, total_row_count=total,
        detail=f"{dupes} duplicate key(s) on {key_cols}",
    )


def check_referential_integrity(child_df: DataFrame, child_key: str,
                                 parent_df: DataFrame, parent_key: str,
                                 table_name: str) -> DQCheckResult:
    """E.g.: every payment_fact.loan_sk must exist in dim_loan."""
    orphans = child_df.join(parent_df, child_df[child_key] == parent_df[parent_key], "left_anti")
    orphan_count = orphans.count()
    return DQCheckResult(
        check_name=f"referential_integrity__{child_key}", table_name=table_name,
        passed=(orphan_count == 0), failed_row_count=orphan_count, total_row_count=child_df.count(),
        detail=f"{orphan_count} orphaned {child_key} value(s)",
    )


def check_balance_reconciliation(df: DataFrame, table_name: str, amount_col: str,
                                  expected_total: float, tolerance_pct: float = 0.001) -> DQCheckResult:
    """Compares a Silver/Gold aggregate against a source-system control total (Phase 1 FR-2.2)."""
    actual_total = df.agg(F.sum(amount_col)).collect()[0][0] or 0.0
    diff_pct = abs(actual_total - expected_total) / expected_total if expected_total else 0
    return DQCheckResult(
        check_name="balance_reconciliation", table_name=table_name,
        passed=(diff_pct <= tolerance_pct), failed_row_count=0, total_row_count=df.count(),
        detail=f"actual={actual_total:,.2f} expected={expected_total:,.2f} diff={diff_pct:.4%}",
    )


def check_negative_balance(df: DataFrame, table_name: str, balance_col: str) -> DQCheckResult:
    """Scenario: negative outstanding_balance should never happen outside a reversal row."""
    negatives = df.filter(F.col(balance_col) < 0).count()
    return DQCheckResult(
        check_name="negative_balance", table_name=table_name,
        passed=(negatives == 0), failed_row_count=negatives, total_row_count=df.count(),
        detail=f"{negatives} row(s) with negative {balance_col}",
    )


def check_outliers_iqr(df: DataFrame, table_name: str, numeric_col: str,
                        iqr_multiplier: float = 3.0) -> DQCheckResult:
    """
    Flags (doesn't reject) statistical outliers via IQR -- e.g. a payment
    amount 10x any other payment on the same loan warrants review, not
    automatic rejection (could be legitimate).
    """
    q1, q3 = df.approxQuantile(numeric_col, [0.25, 0.75], 0.01)
    iqr = q3 - q1
    lower, upper = q1 - iqr_multiplier * iqr, q3 + iqr_multiplier * iqr
    outliers = df.filter((F.col(numeric_col) < lower) | (F.col(numeric_col) > upper)).count()
    return DQCheckResult(
        check_name=f"outliers_iqr__{numeric_col}", table_name=table_name,
        passed=True,  # informational, not a hard gate -- see docstring
        failed_row_count=outliers, total_row_count=df.count(),
        detail=f"{outliers} outlier(s) outside [{lower:.2f}, {upper:.2f}]",
    )


def write_dq_results(spark, results: list[DQCheckResult], run_id: str) -> None:
    """Logs every check result to a queryable Delta table -- this is what
    Phase 14's DQ dashboard reads from."""
    rows = [(r.check_name, r.table_name, r.passed, r.failed_row_count, r.total_row_count, r.detail, run_id)
            for r in results]
    df = spark.createDataFrame(
        rows, ["check_name", "table_name", "passed", "failed_row_count", "total_row_count", "detail", "run_id"]
    ).withColumn("checked_at", F.current_timestamp())
    df.write.format("delta").mode("append").saveAsTable("dq.check_results")

    failures = [r for r in results if not r.passed]
    if failures:
        # Phase 11/16 alerting hook -- page on-call, don't fail silently.
        print(f"[DQ ALERT] {len(failures)} check(s) failed: {[f.check_name for f in failures]}")
