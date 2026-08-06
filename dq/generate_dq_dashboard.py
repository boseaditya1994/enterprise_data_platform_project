"""
Renders dq.check_results (populated by run_dq_checks_duckdb.py) as a
static HTML dashboard -- a lightweight stand-in for what a real DQ
dashboard (Databricks SQL dashboard, or a Power BI page fed by
dq.check_results) would show operationally. Real numbers, real run.

Usage:
    cd dq
    python3 run_dq_checks_duckdb.py      # populate dq.check_results first
    python3 generate_dq_dashboard.py
"""
import os

import duckdb

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "sql", "silver", "local_execution", "warehouse.duckdb")
OUTPUT_PATH = os.path.join(HERE, "dq_dashboard.html")

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Loan Delinquency & Collections Command Center — DQ Dashboard</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 32px; background: #f5f6f8; color: #1a1a2e; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #666; margin-bottom: 24px; font-size: 13px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 28px; }}
  .card {{ background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1; }}
  .card .num {{ font-size: 28px; font-weight: 700; }}
  .card .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.03em; }}
  .pass {{ color: #27AE60; }} .warn {{ color: #E67E22; }} .fail {{ color: #C0392B; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th {{ text-align: left; background: #1a1a2e; color: white; padding: 10px 14px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .badge-pass {{ background: #e8f8f0; color: #27AE60; }}
  .badge-warn {{ background: #fdf1e3; color: #E67E22; }}
  .badge-fail {{ background: #fbe9e7; color: #C0392B; }}
  .table-name {{ font-family: monospace; font-size: 12px; color: #444; }}
</style>
</head>
<body>
  <h1>Data Quality Dashboard</h1>
  <div class="subtitle">Run ID: {run_id} &middot; Generated {generated_at} &middot; Source: dq.check_results
  (docs/14-testing-data-quality.md)</div>

  <div class="summary">
    <div class="card"><div class="num">{total}</div><div class="label">Checks Run</div></div>
    <div class="card"><div class="num pass">{passed}</div><div class="label">Passed</div></div>
    <div class="card"><div class="num fail">{fail_failures}</div><div class="label">FAIL-severity failures</div></div>
    <div class="card"><div class="num warn">{warn_failures}</div><div class="label">WARN-severity failures</div></div>
  </div>

  <table>
    <tr><th>Status</th><th>Table</th><th>Check</th><th>Severity</th><th>Detail</th></tr>
    {rows}
  </table>
</body>
</html>
"""

ROW_TEMPLATE = """<tr>
  <td><span class="badge badge-{badge_class}">{status}</span></td>
  <td class="table-name">{table_name}</td>
  <td>{check_name}</td>
  <td>{severity}</td>
  <td>{detail}</td>
</tr>"""


def main():
    con = duckdb.connect(DB_PATH, read_only=True)
    latest_run = con.execute("SELECT run_id FROM dq.check_results ORDER BY checked_at DESC LIMIT 1").fetchone()
    if not latest_run:
        print("No dq.check_results found -- run run_dq_checks_duckdb.py first.")
        return
    run_id = latest_run[0]

    results = con.execute("""
        SELECT table_name, check_name, severity, passed, detail
        FROM dq.check_results
        WHERE run_id = ?
        ORDER BY passed ASC, severity DESC, table_name
    """, [run_id]).fetchall()

    total = len(results)
    passed = sum(1 for r in results if r[3])
    fail_failures = sum(1 for r in results if not r[3] and r[2] == "FAIL")
    warn_failures = sum(1 for r in results if not r[3] and r[2] == "WARN")

    rows_html = []
    for table_name, check_name, severity, is_passed, detail in results:
        if is_passed:
            status, badge_class = "PASS", "pass"
        elif severity == "FAIL":
            status, badge_class = "FAIL", "fail"
        else:
            status, badge_class = "WARN", "warn"
        rows_html.append(ROW_TEMPLATE.format(
            badge_class=badge_class, status=status, table_name=table_name,
            check_name=check_name, severity=severity, detail=detail,
        ))

    from datetime import datetime
    html = HTML_TEMPLATE.format(
        run_id=run_id, generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total=total, passed=passed, fail_failures=fail_failures, warn_failures=warn_failures,
        rows="\n    ".join(rows_html),
    )

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"Dashboard written to {OUTPUT_PATH}")
    print(f"  {total} checks, {passed} passed, {fail_failures} FAIL-severity failures, {warn_failures} WARN-severity failures")
    con.close()


if __name__ == "__main__":
    main()
