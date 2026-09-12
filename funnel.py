"""Funnel stages, conversion rates and where the funnel leaks.

The funnel has six stages. A lead can only reach a stage by passing through
every stage before it, so the stages are strictly ordered:

    Lead -> Contacted -> Qualified -> Meeting -> Proposal -> Won

Two conversion rates answer different questions and are both reported:

    step-to-step : of the leads that REACHED this stage, how many advanced?
                   This is what finds the leak.
    cumulative   : of all leads that entered, how many got this far?
                   This is what forecasts volume.

Measuring every stage against the total (cumulative only) hides the leak:
a stage can look bad simply because the stage above it starved it.
"""

from dataclasses import dataclass
from datetime import datetime

STAGES = ["lead", "contacted", "qualified", "meeting", "proposal", "won"]

STAGE_LABELS = {
    "lead": "Lead created",
    "contacted": "First contact",
    "qualified": "Qualified",
    "meeting": "Meeting held",
    "proposal": "Proposal sent",
    "won": "Closed won",
}


class FunnelDataError(ValueError):
    """Raised when a lead record cannot describe a possible journey."""


@dataclass(frozen=True)
class Lead:
    """One lead and the timestamp at which it reached each stage.

    A stage that was never reached is None. `lost_at` is independent: a lead
    can be lost from any stage, and being lost does not erase the stages it
    did reach.
    """

    lead_id: str
    channel: str
    campaign: str
    sdr: str
    created_at: datetime
    contacted_at: datetime | None
    qualified_at: datetime | None
    meeting_at: datetime | None
    proposal_at: datetime | None
    won_at: datetime | None
    lost_at: datetime | None
    deal_value: float

    def stage_time(self, stage: str) -> datetime | None:
        return {
            "lead": self.created_at,
            "contacted": self.contacted_at,
            "qualified": self.qualified_at,
            "meeting": self.meeting_at,
            "proposal": self.proposal_at,
            "won": self.won_at,
        }[stage]

    def reached(self, stage: str) -> bool:
        return self.stage_time(stage) is not None

    @property
    def current_stage(self) -> str:
        """The furthest stage this lead reached."""
        furthest = "lead"
        for stage in STAGES:
            if self.reached(stage):
                furthest = stage
        return furthest

    @property
    def is_open(self) -> bool:
        """Still in play: not won and not lost."""
        return self.won_at is None and self.lost_at is None


def validate(lead: Lead) -> None:
    """Reject journeys that cannot have happened.

    Timestamps must not go backwards, a lead cannot skip a stage, and a lead
    cannot be both won and lost. These are data-collection failures, not
    unusual leads, so they are raised rather than silently normalised.
    """
    if lead.won_at is not None and lead.lost_at is not None:
        raise FunnelDataError(f"{lead.lead_id}: marked both won and lost")

    if lead.won_at is not None and lead.deal_value <= 0:
        raise FunnelDataError(f"{lead.lead_id}: won with no deal value")

    last_reached = None   # (stage, timestamp) of the last stage actually reached
    first_gap = None      # the first stage that was skipped, if any

    for stage in STAGES:
        moment = lead.stage_time(stage)

        if moment is None:
            if first_gap is None:
                first_gap = stage
            continue

        # Reaching a stage after a hole means the CRM lost an event: the lead
        # cannot have held a meeting without ever having been contacted.
        if first_gap is not None:
            raise FunnelDataError(
                f"{lead.lead_id}: reached {stage} without {first_gap}"
            )

        if last_reached is not None and moment < last_reached[1]:
            raise FunnelDataError(
                f"{lead.lead_id}: {stage} happened before {last_reached[0]}"
            )

        last_reached = (stage, moment)


def stage_counts(leads: list[Lead]) -> dict[str, int]:
    """How many leads reached each stage."""
    return {stage: sum(1 for lead in leads if lead.reached(stage)) for stage in STAGES}


def conversion(leads: list[Lead]) -> list[dict]:
    """Conversion table: one row per stage transition.

    Each row carries both rates plus the absolute number of leads lost at
    that step, because a 40% drop on 12 leads and a 40% drop on 400 leads
    are the same percentage and completely different problems.
    """
    counts = stage_counts(leads)
    entered = counts["lead"]
    rows = []

    for index in range(1, len(STAGES)):
        previous, stage = STAGES[index - 1], STAGES[index]
        reached_previous = counts[previous]
        reached_stage = counts[stage]

        rows.append(
            {
                "from": previous,
                "to": stage,
                "reached": reached_stage,
                "step_rate": reached_stage / reached_previous if reached_previous else 0.0,
                "cumulative_rate": reached_stage / entered if entered else 0.0,
                "dropped": reached_previous - reached_stage,
            }
        )

    return rows


def biggest_leak(leads: list[Lead], min_sample: int = 5) -> dict | None:
    """The transition with the worst step-to-step rate.

    A transition is only a candidate if at least `min_sample` leads reached
    the stage above it. Without that floor the answer is almost always the
    bottom of the funnel, where one or two leads make a 0% rate that means
    nothing: "0 of 1 advanced" is not a leak, it is an empty stage.

    Returns None when nothing is dropping, or when the funnel is still too
    small to say anything — which is the honest answer, not a default.
    """
    counts = stage_counts(leads)

    rows = [
        row
        for row in conversion(leads)
        if row["dropped"] > 0 and counts[row["from"]] >= min_sample
    ]

    if not rows:
        return None
    return min(rows, key=lambda row: row["step_rate"])
