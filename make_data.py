"""Generates the synthetic sample dataset. Not part of the tool itself."""

import csv
import random
from datetime import datetime, timedelta

random.seed(7)

START = datetime(2026, 3, 2, 9, 0)

# channel -> (campaign, lead count, deals to close, ticket range)
PLAN = [
    ("meta", "lookalike-lojistas", 38, 2, (3600, 5400)),
    ("meta", "remarketing-site", 17, 1, (3600, 5400)),
    ("google", "search-loja-virtual", 19, 4, (4200, 6600)),
    ("google", "search-concorrentes", 11, 2, (4200, 6600)),
    ("organic", "blog-seo", 20, 3, (3600, 5400)),
    ("referral", "programa-indicacao", 10, 3, (6000, 9600)),
]

SDRS = {
    # sdr: (response hours range, works the lead?, relative strength)
    "SDR-01": ((1, 4), 0.98, 1.20),
    "SDR-02": ((4, 14), 0.92, 1.00),
    "SDR-03": ((18, 52), 0.72, 0.70),
}

# Target step rates. qualified -> meeting is deliberately the weakest link:
# the team qualifies plenty and cannot get the meeting on the calendar.
STEP = {
    "qualified": 0.76,
    "meeting": 0.52,
    "proposal": 0.78,
}


def fmt(moment):
    return "" if moment is None else moment.strftime("%Y-%m-%d %H:%M")


def build():
    """Walk each lead down the funnel, then close a fixed number per campaign.

    How many deals each campaign wins is set in PLAN rather than rolled, so
    the resulting CAC per channel is the story the sample is meant to tell
    instead of whatever the random seed happened to produce.
    """
    leads = []
    counter = 0

    for channel, campaign, count, _deals, ticket in PLAN:
        for _ in range(count):
            counter += 1
            sdr = random.choice(list(SDRS))
            (lo, hi), work_rate, strength = SDRS[sdr]

            created = START + timedelta(
                days=random.randint(0, 55),
                hours=random.randint(0, 10),
                minutes=random.choice([0, 15, 30, 45]),
            )

            contacted = qualified = meeting = proposal = None

            if random.random() < work_rate:
                contacted = created + timedelta(hours=random.uniform(lo, hi))

                if random.random() < STEP["qualified"] * strength:
                    qualified = contacted + timedelta(hours=random.uniform(6, 70))

                    if random.random() < STEP["meeting"] * strength:
                        meeting = qualified + timedelta(days=random.uniform(1.5, 9))

                        if random.random() < STEP["proposal"]:
                            proposal = meeting + timedelta(days=random.uniform(0.5, 5))

            leads.append(
                {
                    "lead_id": f"L-{counter:04d}",
                    "campaign_key": campaign,
                    "ticket": ticket,
                    "created": created,
                    "contacted": contacted,
                    "qualified": qualified,
                    "meeting": meeting,
                    "proposal": proposal,
                    "won": None,
                    "lost": None,
                    "value": 0.0,
                    "channel": channel,
                    "campaign": campaign,
                    "sdr": sdr,
                    "strength": strength,
                }
            )

    # Close the planned number of deals per campaign, preferring leads owned
    # by the stronger SDRs so the per-SDR table stays coherent with the funnel.
    for _channel, campaign, _count, deals, ticket in PLAN:
        eligible = [
            lead for lead in leads
            if lead["campaign_key"] == campaign and lead["proposal"] is not None
        ]
        eligible.sort(
            key=lambda lead: -lead["strength"] + random.uniform(-0.38, 0.38)
        )

        for lead in eligible[:deals]:
            lead["won"] = lead["proposal"] + timedelta(days=random.uniform(1, 14))
            lead["value"] = round(random.uniform(*ticket), -1)

    # Anything that stopped moving long enough counts as lost.
    for lead in leads:
        if lead["won"] is None and random.random() < 0.72:
            last = (
                lead["proposal"] or lead["meeting"] or lead["qualified"]
                or lead["contacted"] or lead["created"]
            )
            lead["lost"] = last + timedelta(days=random.uniform(2, 20))

    rows = [
        {
            "lead_id": lead["lead_id"],
            "created_at": fmt(lead["created"]),
            "channel": lead["channel"],
            "campaign": lead["campaign"],
            "sdr": lead["sdr"],
            "contacted_at": fmt(lead["contacted"]),
            "qualified_at": fmt(lead["qualified"]),
            "meeting_at": fmt(lead["meeting"]),
            "proposal_at": fmt(lead["proposal"]),
            "won_at": fmt(lead["won"]),
            "lost_at": fmt(lead["lost"]),
            "deal_value": f"{lead['value']:.0f}",
        }
        for lead in leads
    ]

    rows.sort(key=lambda row: row["created_at"])
    return rows


def main():
    rows = build()

    with open("data/leads.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    spend = [
        ("meta", "lookalike-lojistas", 8400),
        ("meta", "remarketing-site", 3300),
        ("google", "search-loja-virtual", 9800),
        ("google", "search-concorrentes", 4100),
        ("organic", "blog-seo", 2800),
        ("referral", "programa-indicacao", 1200),
    ]

    with open("data/ad_spend.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["channel", "campaign", "amount"])
        writer.writerows(spend)

    won = sum(1 for row in rows if row["won_at"])
    print(f"{len(rows)} leads, {won} won")


if __name__ == "__main__":
    main()
