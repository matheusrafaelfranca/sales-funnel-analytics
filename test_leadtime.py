"""Tests for lead time, response time and SDR performance."""

import pytest
from conftest import BASE, at, stopped_at

from leadtime import (
    by_sdr,
    never_contacted,
    response_times,
    sales_cycle_days,
    stage_durations,
    stalled,
)


def test_response_time_is_creation_to_first_contact():
    assert response_times([stopped_at("contacted")]) == pytest.approx([2.0])


def test_uncontacted_leads_are_excluded_not_counted_as_zero():
    """Folding them in as zero would make an unworked list look instant."""
    leads = [stopped_at("contacted"), stopped_at("lead"), stopped_at("lead")]

    assert response_times(leads) == pytest.approx([2.0])
    assert len(never_contacted(leads)) == 2


def test_stage_durations_use_only_completed_transitions():
    """A lead still sitting in a stage must not shorten that stage's median.

    Three leads qualify; only one goes on to a meeting. The median for
    qualified -> meeting is that one lead's 70 hours, not an average diluted
    by the two that never moved.
    """
    leads = [stopped_at("meeting")]  # qualified at 26h, meeting at 96h
    leads += [stopped_at("qualified") for _ in range(2)]

    rows = {(row["from"], row["to"]): row for row in stage_durations(leads)}
    transition = rows[("qualified", "meeting")]

    assert transition["completed"] == 1
    assert transition["median_hours"] == pytest.approx(70.0)


def test_stage_duration_is_none_when_nobody_completed_it():
    rows = {(r["from"], r["to"]): r for r in stage_durations([stopped_at("contacted")])}

    assert rows[("contacted", "qualified")]["median_hours"] is None
    assert rows[("contacted", "qualified")]["completed"] == 0


def test_median_resists_one_extreme_deal():
    """One four-month deal must not move the number the team plans against."""
    leads = [stopped_at("won", won_at=at(24 * 10)) for _ in range(3)]
    leads += [stopped_at("won", won_at=at(24 * 120))]

    assert sales_cycle_days(leads) == pytest.approx(10.0)


def test_sales_cycle_is_none_without_a_single_win():
    assert sales_cycle_days([stopped_at("proposal")]) is None


def test_stalled_measures_from_the_last_movement():
    """A lead that advanced recently is never stale, however old it is."""
    now = at(24 * 40)

    old_but_moving = stopped_at("proposal", proposal_at=at(24 * 39))
    old_and_stuck = stopped_at("qualified")

    flagged = stalled([old_but_moving, old_and_stuck], threshold_days=14, now=now)

    assert [lead.lead_id for lead in flagged] == [old_and_stuck.lead_id]


def test_closed_leads_are_never_stalled():
    now = at(24 * 90)
    leads = [stopped_at("won"), stopped_at("qualified", lost_at=at(100))]

    assert stalled(leads, threshold_days=14, now=now) == []


def test_close_rate_is_measured_over_leads_received():
    """An SDR cannot improve the number by ignoring the hard leads.

    SDR-03 receives 4 leads, works 1 and closes it. Over leads worked that
    is 100%; over leads received it is 25%, which is the honest figure.
    """
    leads = [stopped_at("won", sdr="SDR-03")]
    leads += [stopped_at("lead", sdr="SDR-03") for _ in range(3)]

    row = by_sdr(leads)[0]

    assert row["leads"] == 4
    assert row["customers"] == 1
    assert row["close_rate"] == pytest.approx(0.25)
    assert row["untouched"] == 3


def test_sdr_rows_sort_by_close_rate():
    leads = [stopped_at("won", sdr="fast")]
    leads += [stopped_at("contacted", sdr="slow") for _ in range(4)]

    assert [row["sdr"] for row in by_sdr(leads)] == ["fast", "slow"]


def test_sdr_response_time_is_none_when_nothing_was_worked():
    row = by_sdr([stopped_at("lead", sdr="SDR-03")])[0]

    assert row["median_response_hours"] is None
    assert row["close_rate"] == 0.0
