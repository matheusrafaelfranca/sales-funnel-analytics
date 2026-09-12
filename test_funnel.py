"""Tests for funnel stages, conversion and leak detection."""

import pytest
from conftest import at, make_lead, stopped_at

from funnel import (
    FunnelDataError,
    biggest_leak,
    conversion,
    stage_counts,
    validate,
)


def test_current_stage_is_the_furthest_reached():
    assert stopped_at("qualified").current_stage == "qualified"
    assert stopped_at("won").current_stage == "won"
    assert stopped_at("lead").current_stage == "lead"


def test_lost_lead_keeps_the_stages_it_reached():
    """Losing a deal does not erase the meeting that happened."""
    lead = stopped_at("meeting", lost_at=at(200))

    assert lead.reached("meeting") is True
    assert lead.current_stage == "meeting"
    assert lead.is_open is False


def test_open_means_neither_won_nor_lost():
    assert stopped_at("qualified").is_open is True
    assert stopped_at("won").is_open is False
    assert stopped_at("qualified", lost_at=at(200)).is_open is False


def test_stage_counts_are_cumulative():
    """A lead at 'meeting' is counted in every stage below it too."""
    leads = [stopped_at("meeting"), stopped_at("contacted"), stopped_at("won")]
    counts = stage_counts(leads)

    assert counts["lead"] == 3
    assert counts["contacted"] == 3
    assert counts["qualified"] == 2
    assert counts["meeting"] == 2
    assert counts["won"] == 1


def test_step_rate_and_cumulative_rate_differ():
    """The distinction that makes the leak visible.

    10 leads, 5 qualify, 4 of those 5 get a meeting. The meeting step is
    strong (80%) even though only 40% of all leads got there.
    """
    leads = [stopped_at("meeting") for _ in range(4)]
    leads += [stopped_at("qualified")]
    leads += [stopped_at("contacted") for _ in range(5)]

    rows = {row["to"]: row for row in conversion(leads)}

    assert rows["meeting"]["step_rate"] == pytest.approx(0.80)
    assert rows["meeting"]["cumulative_rate"] == pytest.approx(0.40)


def test_biggest_leak_finds_the_worst_step():
    # 10 contacted, 8 qualified (80%), 2 meetings (25%) -> meeting is the leak.
    leads = [stopped_at("meeting") for _ in range(2)]
    leads += [stopped_at("qualified") for _ in range(6)]
    leads += [stopped_at("contacted") for _ in range(2)]

    leak = biggest_leak(leads)

    assert leak["from"] == "qualified"
    assert leak["to"] == "meeting"
    assert leak["dropped"] == 6


def test_biggest_leak_ignores_stages_nobody_reached():
    """An empty stage is 0% by definition and must not be reported as the leak."""
    leads = [stopped_at("contacted") for _ in range(4)]
    leads += [stopped_at("qualified")]

    leak = biggest_leak(leads)

    assert leak["to"] == "qualified"  # not 'meeting', which nobody reached


def test_biggest_leak_is_none_for_a_perfect_funnel():
    assert biggest_leak([stopped_at("won") for _ in range(3)]) is None


def test_valid_journey_passes():
    validate(make_lead())
    validate(stopped_at("qualified"))
    validate(stopped_at("meeting", lost_at=at(200)))


def test_won_and_lost_is_rejected():
    with pytest.raises(FunnelDataError, match="both won and lost"):
        validate(make_lead(lost_at=at(400)))


def test_won_without_value_is_rejected():
    with pytest.raises(FunnelDataError, match="no deal value"):
        validate(make_lead(deal_value=0))


def test_backwards_timestamps_are_rejected():
    with pytest.raises(FunnelDataError, match="before"):
        validate(make_lead(qualified_at=at(1)))  # earlier than first contact


def test_skipped_stage_is_rejected():
    """A meeting without a first contact means the CRM lost an event."""
    with pytest.raises(FunnelDataError, match="without"):
        validate(make_lead(contacted_at=None, qualified_at=None))
