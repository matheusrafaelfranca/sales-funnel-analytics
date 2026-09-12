# Sales Funnel Analytics

A Python tool that reads a lead export and an ad spend export and answers the
four questions a small sales operation actually needs answered:

- **Where does the funnel leak?** Which stage transition loses the most leads.
- **Which channel is worth the money?** Cost per customer, not cost per lead.
- **How long does it take?** Lead time per stage, and how fast leads get worked.
- **How is the team doing?** Per-SDR conversion and first-response time.

The sample dataset models a fictional company selling an online-store platform
to small retailers, acquiring leads through Meta Ads, Google Ads, organic search
and a referral programme. **All data in this repository is synthetic** — leads
are anonymous IDs and SDRs are labels, not people.

## Usage

```bash
python analyze.py data/leads.csv data/ad_spend.csv
```

## What it reports

### The funnel

```
Stage               Leads  Of total     Step  Lost here
-------------------------------------------------------
Lead created          115    100.0%        —          —
First contact         103     89.6%    89.6%         12
Qualified              81     70.4%    78.6%         22
Meeting held           49     42.6%    60.5%         32
Proposal sent          39     33.9%    79.6%         10
Closed won             15     13.0%    38.5%         24

Biggest leak: Proposal sent -> Closed won (38.5% advance, 24 leads lost).
```

Two rates, because they answer different questions. **Of total** forecasts
volume: 13% of everything that enters becomes a customer. **Step** finds the
leak: of the leads that reached a stage, how many advanced. A stage can look
terrible on the cumulative rate simply because the stage above it starved it —
only the step rate tells you where the problem actually is.

### Channels

```
Channel         Spend  Leads  Cust.      CPL      CAC   ROAS   Close
--------------------------------------------------------------------
google         13,900     30      6      463    2,317   2.4x   20.0%
referral        1,200     10      3      120      400  20.1x   30.0%
meta           11,700     55      3      213    3,900   1.2x    5.5%
organic         2,800     20      3      140      933   4.9x   15.0%

Volume is not value: meta brings the most leads (55) at a CAC of 3,900,
while referral buys a customer for 400.
```

This is the finding the whole tool exists for. Meta produces **more leads than
every other channel combined** and the cheapest leads in the account after
referral — and it is by far the most expensive way to buy a customer, returning
barely more than it costs. An account optimised on cost per lead would keep
pushing budget into exactly the wrong channel.

### Lead time and the team

```
Transition                              Completed   Median
----------------------------------------------------------
Lead created -> First contact                 103     7.2h
First contact -> Qualified                     81    35.7h
Qualified -> Meeting held                      49   122.8h
Meeting held -> Proposal sent                  39    48.2h
Proposal sent -> Closed won                    15   226.5h

Median sales cycle: 18.6 days (lead created to closed won).
Never contacted: 12 leads were created and never worked.
Stalled: 20 open leads with no movement for over 14 days.

SDR        Leads  Meet.  Cust.   Close  Response  Untouched
-----------------------------------------------------------
SDR-01        42     24      8   19.0%      2.4h          0
SDR-02        33     19      5   15.2%      8.7h          1
SDR-03        40      6      2    5.0%     31.4h         11
```

Response time and close rate move together: 2.4h → 19%, 8.7h → 15%, 31.4h → 5%.
SDR-03 also left 11 of 40 leads untouched — leads that were paid for and never
worked. Those two numbers together are a coaching conversation, not a
performance review.

## Input format

`leads.csv` — one row per lead. A blank timestamp means the stage was never
reached.

| Column | Meaning |
|---|---|
| `lead_id` | Anonymous identifier |
| `created_at` | When the lead entered (`YYYY-MM-DD HH:MM`) |
| `channel` | First-touch channel: meta, google, organic, referral |
| `campaign` | Campaign within the channel |
| `sdr` | Who owns the lead |
| `contacted_at` | First human contact |
| `qualified_at` | Passed qualification |
| `meeting_at` | Meeting held |
| `proposal_at` | Proposal sent |
| `won_at` | Closed won |
| `lost_at` | Closed lost (independent of the stages reached) |
| `deal_value` | Contract value, 0 unless won |

`ad_spend.csv` — `channel`, `campaign`, `amount` for the analysed period.

## Design decisions

**Attribution is first-touch, and that is a limitation, not a feature.** Each
lead carries one channel. A lead that saw a Meta ad, searched the brand on
Google and then arrived through a referral is credited entirely to whichever
touch the CRM recorded. Multi-touch attribution would need the full event
stream, which most small operations do not have. The single-channel model is
stated here so nobody reads the CAC table as more precise than it is.

**CAC and CPL are reported side by side on purpose.** Cost per lead is the
number ad platforms optimise for and the number that misleads. The gap between
the two columns is the point.

**A channel with spend and no customers has CAC `None`, not `0`.** Returning
zero would sort the worst channel in the account as the best. ROAS in that
situation is genuinely `0x` — money spent, nothing returned — so that one is
reported as a number, because it is one.

**Lead time counts only completed transitions.** A lead that has been stuck in
a stage for three weeks contributes nothing to that stage's median until it
moves, which means the slowest cases are systematically missing. Averages would
therefore read faster than reality, so `stalled()` reports those leads
separately instead of letting them silently flatter the number.

**Medians, not averages, throughout.** One deal that took four months to sign
should not move the figure the team plans against.

**The leak detector requires a minimum sample.** Without a floor, the answer is
almost always the bottom of the funnel, where one or two leads produce a 0%
rate that means nothing. "0 of 1 advanced" is an empty stage, not a leak.

**SDR close rate is measured over leads received, not leads worked.** Otherwise
an SDR improves the number by ignoring the leads that look hard — and the
untouched column exists to make exactly that behaviour visible.

**Impossible journeys are rejected loudly.** A lead that is both won and lost,
timestamps that run backwards, or a meeting with no prior contact are
data-collection failures, not unusual leads. The tool names the lead and the
line rather than reporting a number someone would act on.

## SQL version

The same four questions, answered a second time in SQL against `leads` and
`ad_spend` tables in SQLite instead of in Python against `Lead`/`Spend`
objects:

```bash
python sql_report.py data/leads.csv data/ad_spend.csv
```

This is an independent implementation, not a wrapper around `funnel.py` /
`channels.py` / `leadtime.py` — `queries.sql` is written from scratch and
happens to agree with them. `test_sql_report.py` cross-checks every query
against the Python modules on the same data, and that check caught a real
bug while it was being written: the first version of `channel_performance`
returned `NULL` CPL for a channel with leads but no ad spend (organic),
because the spend side of a `LEFT JOIN` was `NULL` and never coalesced
before the division — instead of the `0.0` the Python version correctly
returns. The test failed, the query was fixed, and the fix is why the
`COALESCE` appears inside the `CASE WHEN` for `cpl`/`cac`/`roas`, not just
in the plain `spend` column.

The queries cover:

- **`funnel_counts`** / **`conversion_steps`** — stage counts and
  step-to-step rates via conditional aggregation (`SUM(CASE WHEN ...)`)
  instead of one query per stage.
- **`channel_performance`** — spend, CPL, CAC and ROAS per channel, built
  from a `UNION` of channel names from both tables (so a channel with only
  spend, or only leads, still gets a row) `LEFT JOIN`ed against both
  aggregates, with `NULL` preserved wherever a denominator is genuinely
  zero.
- **`stage_durations`** — median hours per completed transition. SQLite has
  no `MEDIAN()`, so it's built from `ROW_NUMBER()` and `COUNT() OVER
  (PARTITION BY ...)`: rank each duration within its transition, then
  average whichever row(s) land in the middle — one row for an odd sample,
  two for an even one.
- **`sdr_ranking`** — per-SDR close rate with `RANK() OVER`, so two SDRs
  tied on close rate share a rank and the next one skips a place.

`biggest_leak()` in `sql_report.py` applies the same minimum-sample floor as
`funnel.biggest_leak()` on top of `conversion_steps` — that floor is a
business rule about how much data is "enough to call it a leak," not a fact
about the data, so it stays in Python rather than being baked into the SQL.

`db.py` loads lists of `Lead` / `Spend` into an in-memory SQLite database;
`sql_report.py` parses `queries.sql` (using the `-- name: x` markers) and
prints a report shaped like `analyze.py`'s.

## Tests

```bash
python -m pytest -v
```

41 tests. `test_funnel.py`, `test_channels.py` and `test_leadtime.py` (33)
cover the Python modules; the ones worth reading are the ones that encode
the decisions above: `test_step_rate_and_cumulative_rate_differ`,
`test_cpl_and_cac_are_different_questions`,
`test_stage_durations_use_only_completed_transitions` and
`test_close_rate_is_measured_over_leads_received`. `test_sql_report.py` (8)
cross-checks the SQL queries against those same modules, including the
`NULL`-vs-`0.0` CAC/CPL/ROAS semantics, the even-sample median case, and
`RANK()` ties.

## Structure

```
funnel.py            Stages, conversion rates, leak detection, validation
channels.py          Spend, CPL, CAC, ROAS per channel and campaign
leadtime.py          Stage durations, response time, stalled leads, SDR table
analyze.py           CLI: reads both CSVs, prints the report
db.py                Loads Lead/Spend lists into an in-memory SQLite database
queries.sql           SQL: funnel, channel, lead-time and SDR-ranking queries
sql_report.py        CLI: runs queries.sql, prints the same report via SQL
conftest.py          Test helpers
test_sql_report.py   Cross-checks between queries.sql and the Python modules
make_data.py         Generates the synthetic sample (not part of the tool)
data/                Sample leads and ad spend
```

No dependencies beyond the standard library (SQLite is built in); `pytest`
is only needed for tests.
