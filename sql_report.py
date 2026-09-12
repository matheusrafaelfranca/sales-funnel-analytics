"""Run the queries in queries.sql and print a report from the SQL layer.

Usage:
    python sql_report.py data/leads.csv data/ad_spend.csv

This is the SQL-driven twin of analyze.py: same input, same numbers, worked
out with JOIN / GROUP BY / HAVING / window functions instead of the Python
loops in funnel.py, channels.py and leadtime.py.
"""

import re
import sqlite3
import sys

from analyze import read_leads, read_spend
from db import build_database

QUERY_FILE = "queries.sql"

MIN_LEAK_SAMPLE = 5  # same floor as funnel.biggest_leak()'s default

STAGE_LABELS = {
    "lead": "Lead created",
    "contacted": "First contact",
    "qualified": "Qualified",
    "meeting": "Meeting held",
    "proposal": "Proposal sent",
    "won": "Closed won",
}


def load_queries(path: str = QUERY_FILE) -> dict[str, str]:
    """Parse queries.sql into {name: sql} using the '-- name: x' markers."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    blocks = re.split(r"^-- name: (\w+)\s*$", text, flags=re.MULTILINE)
    return {name: body.strip() for name, body in zip(blocks[1::2], blocks[2::2])}


QUERIES = load_queries()


def run(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return conn.execute(QUERIES[name]).fetchall()


def biggest_leak(conn: sqlite3.Connection, min_sample: int = MIN_LEAK_SAMPLE):
    """The worst step_rate among transitions with enough sample to trust.

    The SQL query returns every transition's raw counts; the minimum-sample
    floor is applied here in Python because it is a business rule (how much
    data is "enough to call it a leak"), not a fact about the data itself --
    the same separation funnel.py keeps between conversion() and
    biggest_leak().
    """
    candidates = [
        row for row in run(conn, "conversion_steps")
        if row["dropped"] > 0 and row["from_n"] >= min_sample
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: row["step_rate"])


def pct(value) -> str:
    return "   n/a" if value is None else f"{value * 100:5.1f}%"


def money(value) -> str:
    return "     n/a" if value is None else f"{value:8,.0f}"


def hours(value) -> str:
    return "    n/a" if value is None else f"{value:5.1f}h"


def title(text: str) -> None:
    print(f"\n{text}")
    print("=" * len(text))


def report_funnel(conn):
    title("FUNNEL (SQL)")
    counts = run(conn, "funnel_counts")[0]

    print(f"\n{'Stage':<18}{'Leads':>7}{'Step':>9}{'Lost here':>11}")
    print("-" * 45)
    print(f"{STAGE_LABELS['lead']:<18}{counts['lead_n']:>7}{'—':>9}{'—':>11}")

    for row in run(conn, "conversion_steps"):
        print(
            f"{STAGE_LABELS[row['to_stage']]:<18}{row['to_n']:>7}"
            f"{pct(row['step_rate']):>9}{row['dropped']:>11}"
        )

    leak = biggest_leak(conn)
    if leak:
        print(
            f"\nBiggest leak: {STAGE_LABELS[leak['from_stage']]} -> "
            f"{STAGE_LABELS[leak['to_stage']]} "
            f"({pct(leak['step_rate']).strip()} advance, {leak['dropped']} leads lost)."
        )


def report_channels(conn):
    title("CHANNELS (SQL)")
    print(f"\n{'Channel':<12}{'Spend':>9}{'Leads':>7}{'Cust.':>7}{'CPL':>9}{'CAC':>9}{'ROAS':>7}{'Close':>8}")
    print("-" * 68)
    for row in run(conn, "channel_performance"):
        roas = "  n/a" if row["roas"] is None else f"{row['roas']:5.1f}x"
        print(
            f"{row['channel']:<12}{money(row['spend'])[-8:]:>9}{row['leads']:>7}"
            f"{row['customers']:>7}{money(row['cpl']):>9}{money(row['cac']):>9}"
            f"{roas:>7}{pct(row['close_rate']):>8}"
        )


def report_speed(conn):
    title("LEAD TIME (SQL)")
    print(f"\n{'Transition':<38}{'Completed':>11}{'Median':>9}")
    print("-" * 58)
    for row in run(conn, "stage_durations"):
        label = f"{STAGE_LABELS[row['from_stage']]} -> {STAGE_LABELS[row['to_stage']]}"
        print(f"{label:<38}{row['completed']:>11}{hours(row['median_hours']):>9}")


def report_sdr(conn):
    title("SDR PERFORMANCE (SQL)")
    print(f"\n{'SDR':<9}{'Leads':>7}{'Meet.':>7}{'Cust.':>7}{'Close':>8}{'Rank':>6}{'Untouched':>11}")
    print("-" * 55)
    for row in run(conn, "sdr_ranking"):
        print(
            f"{row['sdr']:<9}{row['leads']:>7}{row['meetings']:>7}{row['customers']:>7}"
            f"{pct(row['close_rate']):>8}{'#' + str(row['rank']):>6}{row['untouched']:>11}"
        )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python sql_report.py <leads.csv> <ad_spend.csv>")

    leads = read_leads(sys.argv[1])
    spends = read_spend(sys.argv[2])
    conn = build_database(leads, spends)

    report_funnel(conn)
    report_channels(conn)
    report_speed(conn)
    report_sdr(conn)
    print()


if __name__ == "__main__":
    main()
