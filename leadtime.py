"""Lead time between stages, response time and SDR performance.

Two different questions, often confused:

    lead time     how long a lead takes to move from one stage to the next
    response time how long the lead waits for the first human contact

Response time is broken out because it is the one number in this file the
team can change today, and the one most strongly associated with whether a
lead converts at all.
"""

from statistics import median

from funnel import STAGES, Lead


def _hours_between(start, end) -> float:
    return (end - start).total_seconds() / 3600


def response_times(leads: list[Lead]) -> list[float]:
    """Hours from lead creation to first contact, for leads that were contacted.

    Leads never contacted are excluded rather than counted as zero. They are a
    real problem, but they are a COVERAGE problem, not a speed problem —
    folding them in here would make an unworked list look fast.
    `never_contacted()` reports them separately.
    """
    return [
        _hours_between(lead.created_at, lead.contacted_at)
        for lead in leads
        if lead.contacted_at is not None
    ]


def never_contacted(leads: list[Lead]) -> list[Lead]:
    """Leads that were paid for and never worked."""
    return [lead for lead in leads if lead.contacted_at is None]


def stage_durations(leads: list[Lead]) -> list[dict]:
    """Median hours for each stage transition.

    Only leads that COMPLETED the transition are counted. Including leads
    still sitting in a stage would understate the duration, because a lead
    that has been stuck for three weeks contributes nothing until it moves —
    the slowest cases are exactly the ones missing from the average.

    The median is used rather than the mean: one deal that took four months
    to sign should not move the number the team plans against.
    """
    rows = []

    for index in range(1, len(STAGES)):
        previous, stage = STAGES[index - 1], STAGES[index]
        durations = [
            _hours_between(lead.stage_time(previous), lead.stage_time(stage))
            for lead in leads
            if lead.reached(previous) and lead.reached(stage)
        ]

        rows.append(
            {
                "from": previous,
                "to": stage,
                "completed": len(durations),
                "median_hours": median(durations) if durations else None,
            }
        )

    return rows


def sales_cycle_days(leads: list[Lead]) -> float | None:
    """Median days from lead creation to closed won, for won deals only."""
    cycles = [
        _hours_between(lead.created_at, lead.won_at) / 24
        for lead in leads
        if lead.won_at is not None
    ]
    return median(cycles) if cycles else None


def stalled(leads: list[Lead], threshold_days: float, now) -> list[Lead]:
    """Open leads with no movement for longer than the threshold.

    Measured from the last stage the lead actually reached, so a lead that
    advanced yesterday is never flagged, however old it is.
    """
    flagged = []

    for lead in leads:
        if not lead.is_open:
            continue
        last_movement = lead.stage_time(lead.current_stage)
        if _hours_between(last_movement, now) / 24 > threshold_days:
            flagged.append(lead)

    return flagged


def by_sdr(leads: list[Lead]) -> list[dict]:
    """Per-SDR performance, sorted by close rate.

    Close rate is measured over leads RECEIVED, not leads worked, so an SDR
    cannot improve the number by ignoring the leads that look hard.
    """
    grouped: dict[str, list[Lead]] = {}
    for lead in leads:
        grouped.setdefault(lead.sdr, []).append(lead)

    rows = []
    for sdr, owned in sorted(grouped.items()):
        responses = response_times(owned)
        customers = sum(1 for lead in owned if lead.reached("won"))

        rows.append(
            {
                "sdr": sdr,
                "leads": len(owned),
                "contacted": sum(1 for lead in owned if lead.reached("contacted")),
                "qualified": sum(1 for lead in owned if lead.reached("qualified")),
                "meetings": sum(1 for lead in owned if lead.reached("meeting")),
                "customers": customers,
                "revenue": sum(lead.deal_value for lead in owned if lead.reached("won")),
                "close_rate": customers / len(owned) if owned else 0.0,
                "median_response_hours": median(responses) if responses else None,
                "untouched": len(never_contacted(owned)),
            }
        )

    return sorted(rows, key=lambda row: row["close_rate"], reverse=True)
