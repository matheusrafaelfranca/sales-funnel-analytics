"""Tests for cost and return per channel."""

import pytest
from conftest import stopped_at

from channels import Spend, by_campaign, by_channel, volume_vs_cac_gap


def test_cpl_and_cac_are_different_questions():
    """The core point of the module.

    Two channels, same spend. Meta buys 10 leads and closes 1; Google buys
    2 leads and closes 1. Meta has the cheaper lead and the identical CAC —
    and the cheaper lead is the number that would have misled the decision.
    """
    leads = [stopped_at("won", channel="meta")]
    leads += [stopped_at("contacted", channel="meta") for _ in range(9)]
    leads += [stopped_at("won", channel="google")]
    leads += [stopped_at("contacted", channel="google")]

    spends = [
        Spend("meta", "c1", 1000.0),
        Spend("google", "c2", 1000.0),
    ]

    rows = {row["key"]: row for row in by_channel(leads, spends)}

    assert rows["meta"]["cpl"] == pytest.approx(100.0)
    assert rows["google"]["cpl"] == pytest.approx(500.0)
    assert rows["meta"]["cac"] == pytest.approx(1000.0)
    assert rows["google"]["cac"] == pytest.approx(1000.0)


def test_cac_is_none_when_nothing_closed():
    """Spend with no customers has an undefined CAC, not a CAC of zero.

    Returning 0.0 would sort the worst channel in the account as the best.
    ROAS is different: spending 4,000 and earning nothing really is 0x, and
    that number is meaningful, so it is reported rather than suppressed.
    """
    leads = [stopped_at("meeting", channel="meta") for _ in range(5)]
    rows = by_channel(leads, [Spend("meta", "c1", 4000.0)])

    assert rows[0]["cac"] is None
    assert rows[0]["roas"] == pytest.approx(0.0)
    assert rows[0]["close_rate"] == 0.0


def test_revenue_and_roas():
    leads = [
        stopped_at("won", channel="google", deal_value=6000.0),
        stopped_at("won", channel="google", deal_value=4000.0),
    ]
    rows = by_channel(leads, [Spend("google", "c1", 2500.0)])

    assert rows[0]["revenue"] == pytest.approx(10000.0)
    assert rows[0]["roas"] == pytest.approx(4.0)
    assert rows[0]["avg_ticket"] == pytest.approx(5000.0)


def test_channel_with_spend_but_no_leads_still_appears():
    """Money spent with nothing to show for it is the most important row."""
    rows = by_channel([], [Spend("meta", "burned", 5000.0)])

    assert len(rows) == 1
    assert rows[0]["spend"] == 5000.0
    assert rows[0]["leads"] == 0
    assert rows[0]["cpl"] is None


def test_organic_leads_with_no_spend():
    rows = by_channel([stopped_at("won", channel="organic")], [])

    assert rows[0]["spend"] == 0.0
    assert rows[0]["cac"] == 0.0
    assert rows[0]["roas"] is None  # dividing revenue by zero spend is undefined


def test_campaign_rows_are_namespaced_by_channel():
    """Two channels can run a campaign with the same name."""
    leads = [
        stopped_at("won", channel="meta", campaign="remarketing"),
        stopped_at("won", channel="google", campaign="remarketing"),
    ]
    spends = [
        Spend("meta", "remarketing", 1000.0),
        Spend("google", "remarketing", 2000.0),
    ]

    keys = {row["key"] for row in by_campaign(leads, spends)}

    assert keys == {"meta / remarketing", "google / remarketing"}


def test_gap_reports_when_volume_and_efficiency_disagree():
    leads = [stopped_at("won", channel="referral")]
    leads += [stopped_at("contacted", channel="meta") for _ in range(20)]
    leads += [stopped_at("won", channel="meta")]

    spends = [Spend("meta", "c1", 10000.0), Spend("referral", "c2", 500.0)]
    gap = volume_vs_cac_gap(by_channel(leads, spends))

    assert gap["most_leads"]["key"] == "meta"
    assert gap["best_cac"]["key"] == "referral"


def test_no_gap_when_the_same_channel_wins_both():
    leads = [stopped_at("won", channel="google") for _ in range(3)]
    rows = by_channel(leads, [Spend("google", "c1", 900.0)])

    assert volume_vs_cac_gap(rows) is None


def test_no_gap_before_the_first_sale():
    leads = [stopped_at("contacted", channel="meta") for _ in range(5)]
    rows = by_channel(leads, [Spend("meta", "c1", 800.0)])

    assert volume_vs_cac_gap(rows) is None
