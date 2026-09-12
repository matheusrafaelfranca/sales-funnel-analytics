"""Command-line report over a lead export and an ad spend export.

Usage:
    python analyze.py data/leads.csv data/ad_spend.csv
"""

import csv
import sys
from datetime import datetime

import channels
import leadtime
from funnel import (
    STAGE_LABELS,
    FunnelDataError,
    Lead,
    biggest_leak,
    conversion,
    stage_counts,
    validate,
)

STALL_THRESHOLD_DAYS = 14

LEAD_COLUMNS = [
    "lead_id", "created_at", "channel", "campaign", "sdr",
    "contacted_at", "qualified_at", "meeting_at", "proposal_at",
    "won_at", "lost_at", "deal_value",
]
SPEND_COLUMNS = ["channel", "campaign", "amount"]


def parse_moment(raw: str):
    """Parse an ISO timestamp, treating blank as 'never reached'."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise SystemExit(f"Invalid timestamp: {raw!r} (expected YYYY-MM-DD HH:MM)")


def require_columns(reader, expected, path):
    missing = [c for c in expected if c not in (reader.fieldnames or [])]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {', '.join(missing)}")


def read_leads(path: str) -> list[Lead]:
    leads = []

    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require_columns(reader, LEAD_COLUMNS, path)

        for line_number, row in enumerate(reader, start=2):
            lead = Lead(
                lead_id=row["lead_id"].strip(),
                channel=row["channel"].strip(),
                campaign=row["campaign"].strip(),
                sdr=row["sdr"].strip(),
                created_at=parse_moment(row["created_at"]),
                contacted_at=parse_moment(row["contacted_at"]),
                qualified_at=parse_moment(row["qualified_at"]),
                meeting_at=parse_moment(row["meeting_at"]),
                proposal_at=parse_moment(row["proposal_at"]),
                won_at=parse_moment(row["won_at"]),
                lost_at=parse_moment(row["lost_at"]),
                deal_value=float(row["deal_value"] or 0),
            )
            try:
                validate(lead)
            except FunnelDataError as exc:
                raise SystemExit(f"Line {line_number}: {exc}")

            leads.append(lead)

    if not leads:
        raise SystemExit(f"{path}: no leads found")

    return leads


def read_spend(path: str) -> list[channels.Spend]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require_columns(reader, SPEND_COLUMNS, path)
        return [
            channels.Spend(
                channel=row["channel"].strip(),
                campaign=row["campaign"].strip(),
                amount=float(row["amount"]),
            )
            for row in reader
        ]


def pct(value) -> str:
    return "   n/a" if value is None else f"{value * 100:5.1f}%"


def money(value) -> str:
    return "     n/a" if value is None else f"{value:8,.0f}"


def hours(value) -> str:
    return "    n/a" if value is None else f"{value:5.1f}h"


def title(text: str) -> None:
    print(f"\n{text}")
    print("=" * len(text))


def report_funnel(leads):
    title("FUNNEL")
    counts = stage_counts(leads)
    entered = counts["lead"]

    print(f"\n{'Stage':<18}{'Leads':>7}{'Of total':>10}{'Step':>9}{'Lost here':>11}")
    print("-" * 55)
    print(f"{STAGE_LABELS['lead']:<18}{entered:>7}{'100.0%':>10}{'—':>9}{'—':>11}")

    for row in conversion(leads):
        print(
            f"{STAGE_LABELS[row['to']]:<18}{row['reached']:>7}"
            f"{pct(row['cumulative_rate']):>10}{pct(row['step_rate']):>9}"
            f"{row['dropped']:>11}"
        )

    leak = biggest_leak(leads)
    if leak:
        print(
            f"\nBiggest leak: {STAGE_LABELS[leak['from']]} -> {STAGE_LABELS[leak['to']]} "
            f"({pct(leak['step_rate']).strip()} advance, {leak['dropped']} leads lost)."
        )


def report_channels(leads, spends):
    title("CHANNELS")
    rows = channels.by_channel(leads, spends)

    print(f"\n{'Channel':<12}{'Spend':>9}{'Leads':>7}{'Cust.':>7}{'CPL':>9}{'CAC':>9}{'ROAS':>7}{'Close':>8}")
    print("-" * 68)
    for row in rows:
        roas = "  n/a" if row["roas"] is None else f"{row['roas']:5.1f}x"
        print(
            f"{row['key']:<12}{money(row['spend'])[-8:]:>9}{row['leads']:>7}"
            f"{row['customers']:>7}{money(row['cpl']):>9}{money(row['cac']):>9}"
            f"{roas:>7}{pct(row['close_rate']):>8}"
        )

    gap = channels.volume_vs_cac_gap(rows)
    if gap:
        most, best = gap["most_leads"], gap["best_cac"]
        print(
            f"\nVolume is not value: {most['key']} brings the most leads "
            f"({most['leads']}) at a CAC of {money(most['cac']).strip()}, "
            f"while {best['key']} buys a customer for {money(best['cac']).strip()}."
        )


def report_campaigns(leads, spends):
    title("CAMPAIGNS")
    print(f"\n{'Campaign':<34}{'Spend':>9}{'Leads':>7}{'Cust.':>7}{'CAC':>9}{'ROAS':>7}")
    print("-" * 73)
    for row in channels.by_campaign(leads, spends):
        roas = "  n/a" if row["roas"] is None else f"{row['roas']:5.1f}x"
        print(
            f"{row['key']:<34}{money(row['spend'])[-8:]:>9}{row['leads']:>7}"
            f"{row['customers']:>7}{money(row['cac']):>9}{roas:>7}"
        )


def report_speed(leads):
    title("LEAD TIME")

    print(f"\n{'Transition':<38}{'Completed':>11}{'Median':>9}")
    print("-" * 58)
    for row in leadtime.stage_durations(leads):
        label = f"{STAGE_LABELS[row['from']]} -> {STAGE_LABELS[row['to']]}"
        print(f"{label:<38}{row['completed']:>11}{hours(row['median_hours']):>9}")

    cycle = leadtime.sales_cycle_days(leads)
    if cycle is not None:
        print(f"\nMedian sales cycle: {cycle:.1f} days (lead created to closed won).")

    untouched = leadtime.never_contacted(leads)
    if untouched:
        print(f"Never contacted: {len(untouched)} leads were created and never worked.")

    now = max(lead.created_at for lead in leads)
    stuck = leadtime.stalled(leads, STALL_THRESHOLD_DAYS, now)
    if stuck:
        print(
            f"Stalled: {len(stuck)} open leads with no movement for over "
            f"{STALL_THRESHOLD_DAYS} days."
        )


def report_sdr(leads):
    title("SDR PERFORMANCE")
    print(f"\n{'SDR':<9}{'Leads':>7}{'Meet.':>7}{'Cust.':>7}{'Close':>8}{'Response':>10}{'Untouched':>11}")
    print("-" * 59)
    for row in leadtime.by_sdr(leads):
        print(
            f"{row['sdr']:<9}{row['leads']:>7}{row['meetings']:>7}{row['customers']:>7}"
            f"{pct(row['close_rate']):>8}{hours(row['median_response_hours']):>10}"
            f"{row['untouched']:>11}"
        )
    print("\nClose rate is measured over leads received, not leads worked.")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python analyze.py <leads.csv> <ad_spend.csv>")

    leads = read_leads(sys.argv[1])
    spends = read_spend(sys.argv[2])

    report_funnel(leads)
    report_channels(leads, spends)
    report_campaigns(leads, spends)
    report_speed(leads)
    report_sdr(leads)
    print()


if __name__ == "__main__":
    main()
