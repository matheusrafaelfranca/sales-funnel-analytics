-- SQL queries for the sales funnel analysis.
--
-- A SECOND, independent implementation of the same metrics as funnel.py /
-- channels.py / leadtime.py -- written in SQL against `leads` and
-- `ad_spend` tables instead of in Python against Lead/Spend objects. The
-- two are cross-checked against each other in test_sql_report.py: if a
-- query here disagrees with the Python module on the same data, one of the
-- two has a bug.
--
-- Every query is self-contained (its own CTEs) so it can be copy-pasted
-- into a SQLite shell and run on its own.
--
-- Table shapes (see db.py):
--   leads(lead_id, channel, campaign, sdr, created_at, contacted_at,
--         qualified_at, meeting_at, proposal_at, won_at, lost_at, deal_value)
--   ad_spend(channel, campaign, amount)
-- Timestamp columns are ISO text ('YYYY-MM-DD HH:MM:SS') or NULL when the
-- lead never reached that stage.


-- name: funnel_counts
-- How many leads reached each stage, via conditional aggregation
-- (SUM(CASE WHEN ...)) instead of six separate COUNT queries.
SELECT
    COUNT(*) AS lead_n,
    SUM(CASE WHEN contacted_at IS NOT NULL THEN 1 ELSE 0 END) AS contacted_n,
    SUM(CASE WHEN qualified_at IS NOT NULL THEN 1 ELSE 0 END) AS qualified_n,
    SUM(CASE WHEN meeting_at   IS NOT NULL THEN 1 ELSE 0 END) AS meeting_n,
    SUM(CASE WHEN proposal_at  IS NOT NULL THEN 1 ELSE 0 END) AS proposal_n,
    SUM(CASE WHEN won_at       IS NOT NULL THEN 1 ELSE 0 END) AS won_n
FROM leads;


-- name: conversion_steps
-- One row per stage transition: step rate (of leads that reached the
-- stage above, how many advanced) and how many were lost. This is the raw
-- material biggest_leak() in sql_report.py filters by minimum sample size --
-- the floor itself is a business rule (funnel.py's `min_sample`), not
-- something that belongs baked into the query.
WITH counts AS (
    SELECT
        COUNT(*) AS lead_n,
        SUM(CASE WHEN contacted_at IS NOT NULL THEN 1 ELSE 0 END) AS contacted_n,
        SUM(CASE WHEN qualified_at IS NOT NULL THEN 1 ELSE 0 END) AS qualified_n,
        SUM(CASE WHEN meeting_at   IS NOT NULL THEN 1 ELSE 0 END) AS meeting_n,
        SUM(CASE WHEN proposal_at  IS NOT NULL THEN 1 ELSE 0 END) AS proposal_n,
        SUM(CASE WHEN won_at       IS NOT NULL THEN 1 ELSE 0 END) AS won_n
    FROM leads
),
steps AS (
    SELECT 'lead' AS from_stage, 'contacted' AS to_stage, lead_n AS from_n, contacted_n AS to_n FROM counts
    UNION ALL
    SELECT 'contacted', 'qualified', contacted_n, qualified_n FROM counts
    UNION ALL
    SELECT 'qualified', 'meeting', qualified_n, meeting_n FROM counts
    UNION ALL
    SELECT 'meeting', 'proposal', meeting_n, proposal_n FROM counts
    UNION ALL
    SELECT 'proposal', 'won', proposal_n, won_n FROM counts
)
SELECT
    from_stage,
    to_stage,
    from_n,
    to_n,
    CASE WHEN from_n > 0 THEN to_n * 1.0 / from_n ELSE 0.0 END AS step_rate,
    from_n - to_n AS dropped
FROM steps;


-- name: channel_performance
-- Spend, leads, customers, CPL, CAC and ROAS per channel.
--
-- A channel can have spend and no leads (money burned on nothing), or leads
-- and no spend (organic), so an INNER JOIN between the two aggregates would
-- silently drop rows. Instead: union the channel names that appear in
-- EITHER table, then LEFT JOIN both aggregates onto that full list.
--
-- CPL/CAC/ROAS are NULL (not 0) when their denominator is zero -- a channel
-- with spend and no customers has an undefined CAC, not a CAC of zero,
-- exactly as channels.py's _finalise() treats it. ROAS is the one exception:
-- spend with zero revenue is a real, meaningful 0.0, not undefined.
WITH channels_all AS (
    SELECT DISTINCT channel FROM leads
    UNION
    SELECT DISTINCT channel FROM ad_spend
),
lead_agg AS (
    SELECT
        channel,
        COUNT(*) AS leads,
        SUM(CASE WHEN won_at IS NOT NULL THEN 1 ELSE 0 END) AS customers,
        SUM(CASE WHEN won_at IS NOT NULL THEN deal_value ELSE 0 END) AS revenue
    FROM leads
    GROUP BY channel
),
spend_agg AS (
    SELECT channel, SUM(amount) AS spend
    FROM ad_spend
    GROUP BY channel
)
SELECT
    c.channel,
    COALESCE(spend_agg.spend, 0.0) AS spend,
    COALESCE(lead_agg.leads, 0) AS leads,
    COALESCE(lead_agg.customers, 0) AS customers,
    COALESCE(lead_agg.revenue, 0.0) AS revenue,
    CASE WHEN COALESCE(lead_agg.leads, 0) > 0
         THEN COALESCE(spend_agg.spend, 0.0) * 1.0 / lead_agg.leads END AS cpl,
    CASE WHEN COALESCE(lead_agg.customers, 0) > 0
         THEN COALESCE(spend_agg.spend, 0.0) * 1.0 / lead_agg.customers END AS cac,
    CASE WHEN COALESCE(spend_agg.spend, 0) > 0
         THEN COALESCE(lead_agg.revenue, 0.0) * 1.0 / spend_agg.spend END AS roas,
    CASE WHEN COALESCE(lead_agg.leads, 0) > 0
         THEN lead_agg.customers * 1.0 / lead_agg.leads ELSE 0.0 END AS close_rate
FROM channels_all c
LEFT JOIN lead_agg  ON lead_agg.channel  = c.channel
LEFT JOIN spend_agg ON spend_agg.channel = c.channel
ORDER BY revenue DESC;


-- name: stage_durations
-- Median hours per stage transition, counting only COMPLETED transitions
-- (a lead stuck in a stage contributes nothing until it moves -- see
-- leadtime.py's stage_durations() for why that matters).
--
-- SQLite has no MEDIAN() aggregate, so it is built from a window function:
-- ROW_NUMBER() ranks each duration within its transition, COUNT() OVER
-- gives that transition's sample size, and the row(s) whose rank sit in the
-- middle are averaged -- one row for an odd sample, two for an even one.
-- This is the standard median-via-window-function pattern.
WITH durations AS (
    SELECT 'lead' AS from_stage, 'contacted' AS to_stage,
           (julianday(contacted_at) - julianday(created_at)) * 24 AS hours
    FROM leads WHERE contacted_at IS NOT NULL
    UNION ALL
    SELECT 'contacted', 'qualified',
           (julianday(qualified_at) - julianday(contacted_at)) * 24
    FROM leads WHERE contacted_at IS NOT NULL AND qualified_at IS NOT NULL
    UNION ALL
    SELECT 'qualified', 'meeting',
           (julianday(meeting_at) - julianday(qualified_at)) * 24
    FROM leads WHERE qualified_at IS NOT NULL AND meeting_at IS NOT NULL
    UNION ALL
    SELECT 'meeting', 'proposal',
           (julianday(proposal_at) - julianday(meeting_at)) * 24
    FROM leads WHERE meeting_at IS NOT NULL AND proposal_at IS NOT NULL
    UNION ALL
    SELECT 'proposal', 'won',
           (julianday(won_at) - julianday(proposal_at)) * 24
    FROM leads WHERE proposal_at IS NOT NULL AND won_at IS NOT NULL
),
ranked AS (
    SELECT
        from_stage,
        to_stage,
        hours,
        ROW_NUMBER() OVER (PARTITION BY from_stage, to_stage ORDER BY hours) AS rn,
        COUNT(*) OVER (PARTITION BY from_stage, to_stage) AS n
    FROM durations
)
SELECT
    from_stage,
    to_stage,
    n AS completed,
    AVG(hours) AS median_hours
FROM ranked
WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
GROUP BY from_stage, to_stage, n;


-- name: sdr_ranking
-- Per-SDR performance, ranked by close rate with RANK() OVER so tied SDRs
-- share a rank. Close rate is leads received, not leads worked -- an SDR
-- cannot improve the number by ignoring the leads that look hard.
WITH sdr_agg AS (
    SELECT
        sdr,
        COUNT(*) AS leads,
        SUM(CASE WHEN meeting_at   IS NOT NULL THEN 1 ELSE 0 END) AS meetings,
        SUM(CASE WHEN won_at       IS NOT NULL THEN 1 ELSE 0 END) AS customers,
        SUM(CASE WHEN contacted_at IS NULL     THEN 1 ELSE 0 END) AS untouched
    FROM leads
    GROUP BY sdr
)
SELECT
    sdr,
    leads,
    meetings,
    customers,
    untouched,
    customers * 1.0 / leads AS close_rate,
    RANK() OVER (ORDER BY customers * 1.0 / leads DESC) AS rank
FROM sdr_agg
ORDER BY close_rate DESC, sdr;
