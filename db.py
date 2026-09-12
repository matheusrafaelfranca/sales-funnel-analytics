"""Load leads and ad spend into an in-memory SQLite database.

This exists so the calculations in queries.sql have tables to run against.
No derived columns are stored -- conversion rates, CAC, medians and rankings
are exactly what queries.sql computes from the raw rows.
"""

import sqlite3

from channels import Spend
from funnel import Lead

SCHEMA = """
-- lead_id is not declared PRIMARY KEY / UNIQUE on purpose: the Python model
-- (Lead in funnel.py) never assumes lead_id is unique either, so the SQL
-- schema stays exactly as strict as the domain it is cross-checked against.
-- The real leads.csv export does have unique IDs; that is a property of the
-- data, not a constraint this layer enforces.
CREATE TABLE leads (
    lead_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    campaign TEXT NOT NULL,
    sdr TEXT NOT NULL,
    created_at TEXT NOT NULL,
    contacted_at TEXT,
    qualified_at TEXT,
    meeting_at TEXT,
    proposal_at TEXT,
    won_at TEXT,
    lost_at TEXT,
    deal_value REAL NOT NULL
);

CREATE TABLE ad_spend (
    channel TEXT NOT NULL,
    campaign TEXT NOT NULL,
    amount REAL NOT NULL
);
"""


def _iso(moment):
    """datetime -> 'YYYY-MM-DD HH:MM:SS' text, or None. julianday() reads this directly."""
    return moment.isoformat(sep=" ") if moment is not None else None


def build_database(leads: list[Lead], spends: list[Spend]) -> sqlite3.Connection:
    """Return an in-memory SQLite connection with both tables loaded.

    No validation happens here: validate() in funnel.py already rejected any
    impossible journey before a Lead reaches this point, so the SQL layer
    answers the same questions on the same, already-trusted data.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                lead.lead_id,
                lead.channel,
                lead.campaign,
                lead.sdr,
                _iso(lead.created_at),
                _iso(lead.contacted_at),
                _iso(lead.qualified_at),
                _iso(lead.meeting_at),
                _iso(lead.proposal_at),
                _iso(lead.won_at),
                _iso(lead.lost_at),
                lead.deal_value,
            )
            for lead in leads
        ],
    )
    conn.executemany(
        "INSERT INTO ad_spend VALUES (?, ?, ?)",
        [(spend.channel, spend.campaign, spend.amount) for spend in spends],
    )
    conn.commit()
    return conn
