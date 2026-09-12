"""Shared test helpers."""

from datetime import datetime, timedelta

import pytest

from funnel import Lead

BASE = datetime(2026, 3, 2, 9, 0)


def at(hours: float) -> datetime:
    """A timestamp N hours after the base moment."""
    return BASE + timedelta(hours=hours)


def make_lead(**overrides) -> Lead:
    """A lead that reached every stage; override to truncate its journey.

    Pass a stage as None to stop the journey there, e.g.
    `make_lead(meeting_at=None, proposal_at=None, won_at=None)`.
    """
    defaults = dict(
        lead_id="L-0001",
        channel="google",
        campaign="search-loja-virtual",
        sdr="SDR-01",
        created_at=BASE,
        contacted_at=at(2),
        qualified_at=at(26),
        meeting_at=at(96),
        proposal_at=at(140),
        won_at=at(300),
        lost_at=None,
        deal_value=5000.0,
    )
    defaults.update(overrides)
    return Lead(**defaults)


def stopped_at(stage: str, **overrides) -> Lead:
    """A lead whose journey ends at `stage`; every later stage is None."""
    order = ["lead", "contacted", "qualified", "meeting", "proposal", "won"]
    fields = {
        "contacted": "contacted_at",
        "qualified": "qualified_at",
        "meeting": "meeting_at",
        "proposal": "proposal_at",
        "won": "won_at",
    }

    cut = order.index(stage)
    blanks = {fields[name]: None for name in order[cut + 1:] if name in fields}

    if stage != "won":
        blanks["deal_value"] = 0.0

    blanks.update(overrides)
    return make_lead(**blanks)


@pytest.fixture
def lead_factory():
    return make_lead
