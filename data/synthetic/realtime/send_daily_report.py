"""
Queries the live, dbt-refreshed KPI views in Snowflake and emails a daily
HTML report with charts and key numbers. Runs as the last step of the
daily GitHub Actions workflow, right after `dbt run` completes -- so
every number here reflects that day's freshest data.
"""
import os
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import matplotlib
matplotlib.use("Agg")  # no display available in CI
import matplotlib.pyplot as plt
import pandas as pd
import snowflake.connector
from cryptography.hazmat.primitives import serialization


def get_snowflake_connection():
    with open(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"], "rb") as key_file:
        p_key = serialization.load_pem_private_key(key_file.read(), password=None)
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=pkb,
        role="ACCOUNTADMIN",
        warehouse="COMPUTE_WH",
        database="LOAN_DELINQUENCY_CC",
        schema="KPI",
    )


def fetch_kpis(conn):
    par_trend = pd.read_sql(
        "SELECT snapshot_date, par_30, par_60, par_90 FROM KPI.VW_PAR_BY_DATE "
        "ORDER BY snapshot_date DESC LIMIT 30", conn)
    par_trend = par_trend.sort_values("SNAPSHOT_DATE")

    latest_par = par_trend.iloc[-1]
    roll_cure = pd.read_sql(
        "SELECT ROUND(AVG(roll_rate)*100,2) AS ROLL_RATE, "
        "(SELECT ROUND(AVG(cure_rate)*100,2) FROM KPI.VW_CURE_RATE_DAILY) AS CURE_RATE "
        "FROM KPI.VW_ROLL_RATE_DAILY", conn).iloc[0]
    recovery = pd.read_sql("SELECT ROUND(recovery_rate*100,2) AS RATE FROM KPI.VW_RECOVERY_RATE", conn).iloc[0]["RATE"]
    call_connect = pd.read_sql("SELECT ROUND(call_connect_rate*100,2) AS RATE FROM KPI.VW_CALL_CONNECT_RATE", conn).iloc[0]["RATE"]
    ptp_fulfillment = pd.read_sql("SELECT ROUND(ptp_fulfillment_rate*100,2) AS RATE FROM KPI.VW_PTP_FULFILLMENT_RATE", conn).iloc[0]["RATE"]
    top_collectors = pd.read_sql(
        "SELECT collector_name, team_name, kept_dollars_collected FROM KPI.VW_COLLECTOR_PRODUCTIVITY "
        "ORDER BY kept_dollars_collected DESC LIMIT 5", conn)

    return {
        "par_trend": par_trend, "latest_par": latest_par, "roll_rate": roll_cure["ROLL_RATE"],
        "cure_rate": roll_cure["CURE_RATE"], "recovery_rate": recovery,
        "call_connect": call_connect, "ptp_fulfillment": ptp_fulfillment, "top_collectors": top_collectors,
    }


def make_par_chart(par_trend: pd.DataFrame) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(par_trend["SNAPSHOT_DATE"], par_trend["PAR_30"], label="PAR 30", marker="o", markersize=3)
    ax.plot(par_trend["SNAPSHOT_DATE"], par_trend["PAR_60"], label="PAR 60", marker="o", markersize=3)
    ax.plot(par_trend["SNAPSHOT_DATE"], par_trend["PAR_90"], label="PAR 90", marker="o", markersize=3)
    ax.set_title("PAR Trend -- Last 30 Days")
    ax.set_ylabel("Portfolio at Risk (%)")
    ax.legend()
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()


def build_email(kpis: dict, run_date: str, chart_bytes: bytes) -> MIMEMultipart:
    lp = kpis["latest_par"]
    top_rows = "".join(
        f"<tr><td>{r.COLLECTOR_NAME}</td><td>{r.TEAM_NAME}</td><td>${r.KEPT_DOLLARS_COLLECTED:,.2f}</td></tr>"
        for r in kpis["top_collectors"].itertuples()
    )
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;">
      <h2>Loan Delinquency Portfolio -- Daily Report ({run_date})</h2>
      <h3>Portfolio Health (as of {lp['SNAPSHOT_DATE']})</h3>
      <table cellpadding="6">
        <tr><td><b>PAR 30</b></td><td>{lp['PAR_30']:.2f}%</td></tr>
        <tr><td><b>PAR 60</b></td><td>{lp['PAR_60']:.2f}%</td></tr>
        <tr><td><b>PAR 90</b></td><td>{lp['PAR_90']:.2f}%</td></tr>
        <tr><td><b>Roll Rate</b></td><td>{kpis['roll_rate']:.2f}%</td></tr>
        <tr><td><b>Cure Rate</b></td><td>{kpis['cure_rate']:.2f}%</td></tr>
        <tr><td><b>Recovery Rate</b></td><td>{kpis['recovery_rate']:.2f}%</td></tr>
        <tr><td><b>Call Connect Rate</b></td><td>{kpis['call_connect']:.2f}%</td></tr>
        <tr><td><b>PTP Fulfillment Rate</b></td><td>{kpis['ptp_fulfillment']:.2f}%</td></tr>
      </table>
      <h3>PAR Trend</h3>
      <img src="cid:par_chart" width="600">
      <h3>Top 5 Collectors (by $ Kept)</h3>
      <table cellpadding="6" border="1" style="border-collapse:collapse;">
        <tr><th>Collector</th><th>Team</th><th>$ Kept</th></tr>
        {top_rows}
      </table>
      <p style="color:#888;font-size:12px;">Generated automatically from live Snowflake data.</p>
    </body></html>
    """
    msg = MIMEMultipart("related")
    msg["Subject"] = f"Loan Portfolio Daily Report -- {run_date}"
    msg["From"] = os.environ["GMAIL_ADDRESS"]
    msg["To"] = os.environ["GMAIL_ADDRESS"]
    msg.attach(MIMEText(html, "html"))
    img = MIMEImage(chart_bytes)
    img.add_header("Content-ID", "<par_chart>")
    msg.attach(img)
    return msg


def send_email(msg: MIMEMultipart):
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)


if __name__ == "__main__":
    import sys
    run_date = sys.argv[1] if len(sys.argv) > 1 else "unknown date"

    conn = get_snowflake_connection()
    try:
        kpis = fetch_kpis(conn)
    finally:
        conn.close()

    chart_bytes = make_par_chart(kpis["par_trend"])
    msg = build_email(kpis, run_date, chart_bytes)
    send_email(msg)
    print("Daily report email sent.")