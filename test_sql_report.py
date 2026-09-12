"""Cross-checks between the SQL queries and the Python modules.

funnel.py, channels.py and leadtime.py were written first and are tested on
their own (test_funnel.py, test_channels.py, test_leadtime.py). The SQL
queries in queries.sql are a second, independent implementation of the same
metrics. These tests build the same lead lists both ways and assert the two
implementations agree -- if they didn't, at least one would have a bug.

Run with:  python -m pytest test_sql_report.py -v
"""

import pytest
from conftest import at, stopped_at

from channels import Spend, by_channel
from db import build_database
from funnel import biggest_leak as py_biggest_leak
from funnel import conversion, stage_counts
from leadtime import by_sdr, stage_durations
from sql_report import biggest_leak as sql_biggest_leak
from sql_report import run


def test_funnel_counts_match_python():
    leads = [stopped_at("won")] * 3
    leads += [stopped_at("meeting")] * 2
    leads += [stopped_at("lead")]

    conn = build_database(leads, [])
    row = run(conn, "funnel_counts")[0]
    py_counts = stage_counts(leads)

    assert row["lead_n"] == py_counts["lead"]
    assert row["contacted_n"] == py_counts["contacted"]
    assert row["qualified_n"] == py_counts["qualified"]
    assert row["meeting_n"] == py_counts["meeting"]
    assert row["proposal_n"] == py_counts["proposal"]
    assert row["won_n"] == py_counts["won"]


def test_conversion_steps_match_python():
    leads = [stopped_at("won")] * 3
    leads += [stopped_at("proposal")] * 2
    leads += [stopped_at("meeting")] * 4
    leads += [stopped_at("qualified")] * 6
    leads += [stopped_at("contacted")] * 8
    leads += [stopped_at("lead")] * 2

    conn = build_database(leads, [])
    sql_rows = {row["to_stage"]: row for row in run(conn, "conversion_steps")}

    for row in conversion(leads):
        sql_row = sql_rows[row["to"]]
        assert sql_row["to_n"] == row["reached"]
        assert sql_row["step_rate"] == pytest.approx(row["step_rate"])
        assert sql_row["dropped"] == row["dropped"]


def test_biggest_leak_matches_python_including_min_sample_floor():
    """The SQL leak-finder must apply the same minimum-sample rule as
    funnel.biggest_leak(): a stage only 1-2 leads reached is not a leak,
    it is an empty stage."""
    leads = [stopped_at("won")] * 10
    leads += [stopped_at("proposal")] * 15  # step to won: 10/25 = 40%
    leads += [stopped_at("meeting")] * 1    # step to proposal: 25/26 = 96%, sample too small to matter
    leads += [stopped_at("qualified")] * 30  # step to meeting: 26/56 -> real leak
    leads += [stopped_at("contacted")] * 4
    leads += [stopped_at("lead")] * 2

    py_leak = py_biggest_leak(leads, min_sample=5)
    sql_leak = sql_biggest_leak(build_database(leads, []), min_sample=5)

    assert py_leak is not None and sql_leak is not None
    assert (sql_leak["from_stage"], sql_leak["to_stage"]) == (py_leak["from"], py_leak["to"])
    assert sql_leak["step_rate"] == pytest.approx(py_leak["step_rate"])
    assert sql_leak["dropped"] == py_leak["dropped"]


def test_biggest_leak_is_none_when_funnel_too_small_in_sql_too():
    leads = [stopped_at("meeting")]
    conn = build_database(leads, [])
    assert sql_biggest_leak(conn, min_sample=5) is None


def test_channel_performance_matches_python_including_none_semantics():
    leads = [stopped_at("won", channel="meta")]
    leads += [stopped_at("contacted", channel="meta") for _ in range(9)]
    leads += [stopped_at("meeting", channel="google") for _ in range(5)]  # spend, no customers
    leads += [stopped_at("won", channel="organic")]  # no spend at all

    spends = [
        Spend("meta", "c1", 1000.0),
        Spend("google", "c2", 4000.0),
        Spend("meta_only_spend", "c3", 500.0),  # spend with zero leads
    ]

    conn = build_database(leads, spends)
    sql_rows = {row["channel"]: row for row in run(conn, "channel_performance")}
    py_rows = {row["key"]: row for row in by_channel(leads, spends)}

    assert set(sql_rows) == set(py_rows)

    for key, py_row in py_rows.items():
        sql_row = sql_rows[key]
        assert sql_row["spend"] == pytest.approx(py_row["spend"])
        assert sql_row["leads"] == py_row["leads"]
        assert sql_row["customers"] == py_row["customers"]
        assert sql_row["cpl"] == (None if py_row["cpl"] is None else pytest.approx(py_row["cpl"]))
        assert sql_row["cac"] == (None if py_row["cac"] is None else pytest.approx(py_row["cac"]))
        assert sql_row["roas"] == (None if py_row["roas"] is None else pytest.approx(py_row["roas"]))

    # The channel with spend and zero customers must have SQL NULL (Python None) CAC.
    assert sql_rows["google"]["cac"] is None
    # A pure-spend, zero-lead channel must still appear, with cpl NULL.
    assert sql_rows["meta_only_spend"]["cpl"] is None
    assert sql_rows["meta_only_spend"]["leads"] == 0
    # Organic has leads and zero spend: cac is a real 0.0, roas is undefined (NULL).
    assert sql_rows["organic"]["cac"] == pytest.approx(0.0)
    assert sql_rows["organic"]["roas"] is None


def test_stage_durations_median_matches_python():
    """Includes an even-sized sample so the two-middle-values average path
    in the SQL window-function median is exercised, not just the odd case."""
    leads = [
        stopped_at("meeting", meeting_at=at(50)),
        stopped_at("meeting", meeting_at=at(70)),
        stopped_at("meeting", meeting_at=at(90)),
        stopped_at("meeting", meeting_at=at(130)),  # 4 leads -> even sample
    ]
    leads += [stopped_at("qualified")] * 2  # never reach "meeting": must not count

    conn = build_database(leads, [])
    sql_rows = {(row["from_stage"], row["to_stage"]): row for row in run(conn, "stage_durations")}

    for row in stage_durations(leads):
        key = (row["from"], row["to"])
        if row["completed"] == 0:
            assert key not in sql_rows or sql_rows[key]["completed"] == 0
            continue
        sql_row = sql_rows[key]
        assert sql_row["completed"] == row["completed"]
        assert sql_row["median_hours"] == pytest.approx(row["median_hours"])


def test_sdr_ranking_matches_python_close_rate_and_untouched():
    leads = [stopped_at("won", sdr="SDR-01")] * 4
    leads += [stopped_at("contacted", sdr="SDR-01")] * 6  # 10 leads, 4 won -> 40%
    leads += [stopped_at("won", sdr="SDR-02")]
    leads += [stopped_at("lead", sdr="SDR-02")] * 3  # 4 leads, 1 won -> 25%, 3 untouched

    conn = build_database(leads, [])
    sql_rows = {row["sdr"]: row for row in run(conn, "sdr_ranking")}
    py_rows = {row["sdr"]: row for row in by_sdr(leads)}

    for sdr, py_row in py_rows.items():
        sql_row = sql_rows[sdr]
        assert sql_row["leads"] == py_row["leads"]
        assert sql_row["customers"] == py_row["customers"]
        assert sql_row["untouched"] == py_row["untouched"]
        assert sql_row["close_rate"] == pytest.approx(py_row["close_rate"])

    # SDR-01's close rate (40%) beats SDR-02's (25%): RANK() must put it first.
    assert sql_rows["SDR-01"]["rank"] < sql_rows["SDR-02"]["rank"]


def test_sdr_ranking_ties_share_a_rank():
    """Two SDRs with an identical close rate must get the same RANK(), and
    the next distinct SDR must skip a place -- that is what separates
    RANK() from ROW_NUMBER()."""
    leads = [stopped_at("won", sdr="A")]
    leads += [stopped_at("won", sdr="B")]
    leads += [stopped_at("contacted", sdr="C")] * 2

    conn = build_database(leads, [])
    ranks = {row["sdr"]: row["rank"] for row in run(conn, "sdr_ranking")}

    assert ranks["A"] == ranks["B"] == 1
    assert ranks["C"] == 3
