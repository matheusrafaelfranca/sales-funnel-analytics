"""Cost and return per acquisition channel and per campaign.

The metric that matters is cost per CUSTOMER (CAC), not cost per lead (CPL).
A channel can deliver the cheapest leads in the account and still be the most
expensive way to buy a customer, because paying less per lead is worthless if
those leads do not close. Both are reported side by side precisely so the gap
between them is visible.
"""

from dataclasses import dataclass

from funnel import Lead


@dataclass(frozen=True)
class Spend:
    """What was invested in one campaign over the analysed period."""

    channel: str
    campaign: str
    amount: float


def _blank_row(key: str) -> dict:
    return {
        "key": key,
        "spend": 0.0,
        "leads": 0,
        "qualified": 0,
        "customers": 0,
        "revenue": 0.0,
    }


def _finalise(row: dict) -> dict:
    """Derive the ratios, leaving None where the denominator is zero.

    None is deliberate: a channel with spend but no customers has an
    *undefined* CAC, not a CAC of zero. Returning 0.0 would make the worst
    channel in the account sort as the best one.
    """
    row["cpl"] = row["spend"] / row["leads"] if row["leads"] else None
    row["cac"] = row["spend"] / row["customers"] if row["customers"] else None
    row["roas"] = row["revenue"] / row["spend"] if row["spend"] else None
    row["close_rate"] = row["customers"] / row["leads"] if row["leads"] else 0.0
    row["avg_ticket"] = row["revenue"] / row["customers"] if row["customers"] else None
    return row


def _aggregate(leads: list[Lead], spends: list[Spend], key_of_lead, key_of_spend) -> list[dict]:
    rows: dict[str, dict] = {}

    for spend in spends:
        key = key_of_spend(spend)
        rows.setdefault(key, _blank_row(key))["spend"] += spend.amount

    for lead in leads:
        key = key_of_lead(lead)
        row = rows.setdefault(key, _blank_row(key))
        row["leads"] += 1
        if lead.reached("qualified"):
            row["qualified"] += 1
        if lead.reached("won"):
            row["customers"] += 1
            row["revenue"] += lead.deal_value

    return [_finalise(row) for row in rows.values()]


def by_channel(leads: list[Lead], spends: list[Spend]) -> list[dict]:
    """One row per channel, sorted by revenue (highest first)."""
    rows = _aggregate(
        leads, spends, lambda lead: lead.channel, lambda spend: spend.channel
    )
    return sorted(rows, key=lambda row: row["revenue"], reverse=True)


def by_campaign(leads: list[Lead], spends: list[Spend]) -> list[dict]:
    """One row per campaign, sorted by spend (highest first)."""
    rows = _aggregate(
        leads,
        spends,
        lambda lead: f"{lead.channel} / {lead.campaign}",
        lambda spend: f"{spend.channel} / {spend.campaign}",
    )
    return sorted(rows, key=lambda row: row["spend"], reverse=True)


def volume_vs_cac_gap(rows: list[dict]) -> dict | None:
    """Compare the channel that delivers the most leads with the cheapest CAC.

    When these are different channels, the account is optimising for the wrong
    number — and that gap is usually the single most valuable finding in the
    whole report. Returns None when they are the same channel, or when no
    channel has produced a customer yet.
    """
    with_leads = [row for row in rows if row["leads"] > 0]
    with_cac = [row for row in rows if row["cac"] is not None]

    if not with_leads or not with_cac:
        return None

    most_leads = max(with_leads, key=lambda row: row["leads"])
    best_cac = min(with_cac, key=lambda row: row["cac"])

    if most_leads["key"] == best_cac["key"]:
        return None

    return {"most_leads": most_leads, "best_cac": best_cac}
