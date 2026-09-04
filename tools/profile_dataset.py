#!/usr/bin/env python
"""
Phase-0 dataset profile.

Answers the one question that decides the whole pitch:
does vendor MIX shift across months, or only vendor RATE?

If only rate shifts, "who caused it" collapses to "sort by biggest drop"
and the differentiator is gone. Run this before writing any metric.
"""
import duckdb, pathlib, sys

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
con = duckdb.connect()

def rule(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

def show(sql, title=None):
    if title:
        print(f"\n--- {title} ---")
    print(con.sql(sql))

# ── normalised trip spine ────────────────────────────────────────────────
# comma-formatted ids/epochs/delays, free-text dates, month-to-month dtype drift
con.sql(f"""
CREATE OR REPLACE VIEW trips AS
SELECT
    CAST(replace(trip_id, ',', '') AS BIGINT)              AS trip_id,
    business_unit, office, product_type, vendor_id,
    trip_direction, shift_type, trip_nodal, delay_reason,
    actual_cab_fuel_type, route_source,
    strptime(trip_date, '%B %d, %Y')::DATE                 AS trip_date,
    date_trunc('month', strptime(trip_date, '%B %d, %Y'))  AS month,
    TRY_CAST(replace(delay_minutes, ',', '') AS DOUBLE)    AS delay_minutes,
    TRY_CAST(replace(planned_end_epoch, ',', '') AS BIGINT)  AS planned_end_epoch,
    TRY_CAST(replace(actual_end_epoch,  ',', '') AS BIGINT)  AS actual_end_epoch,
    TRY_CAST(planned_km  AS DOUBLE)                        AS planned_km,
    TRY_CAST(traveled_km AS DOUBLE)                        AS traveled_km,
    TRY_CAST(actual_escort AS BOOLEAN)                     AS actual_escort,
    TRY_CAST(is_driver_nc AS BOOLEAN)                      AS is_driver_nc,
    TRY_CAST(is_cab_nc    AS BOOLEAN)                      AS is_cab_nc,
    actual_cab_capacity, plannedemployee_cnt, actualemployee_cnt, noshow_cnt
FROM read_csv('{RAW}/Ride_data*.csv',
              header=true, union_by_name=true, null_padding=true,
              ignore_errors=true, all_varchar=true, sample_size=-1)
""")

rule("1 · VOLUME BY MONTH")
show("""
SELECT month, count(*) AS trips,
       count(DISTINCT vendor_id) AS vendors,
       count(DISTINCT office)    AS offices,
       count(DISTINCT business_unit) AS business_units
FROM trips GROUP BY month ORDER BY month
""")

rule("2 · ON-TIME DEFINITION — how delay is distributed")
show("""
SELECT delay_reason, count(*) AS trips,
       round(100.0*count(*)/sum(count(*)) OVER (), 1) AS pct,
       round(median(delay_minutes), 1) AS median_delay,
       round(quantile_cont(delay_minutes, 0.9), 1) AS p90_delay,
       round(max(delay_minutes), 0) AS max_delay
FROM trips GROUP BY delay_reason ORDER BY trips DESC
""")

# on-time = delay of 5 minutes or less
con.sql("""
CREATE OR REPLACE VIEW t AS
SELECT *, CASE WHEN delay_minutes IS NULL THEN NULL
                WHEN delay_minutes <= 5 THEN 1 ELSE 0 END AS on_time
FROM trips
""")

show("""
SELECT month,
       count(*) AS trips,
       round(100.0*avg(on_time), 2) AS ota_pct
FROM t GROUP BY month ORDER BY month
""", "Campus-wide OTA by month")

rule("3 · ⭐ THE CRITICAL CHECK — does vendor MIX shift?")
show("""
WITH s AS (
  SELECT vendor_id, month, count(*) AS trips,
         100.0*count(*)/sum(count(*)) OVER (PARTITION BY month) AS share
  FROM t GROUP BY 1,2
), p AS (
  SELECT vendor_id,
    max(CASE WHEN month='2026-05-01' THEN share END) AS may_share,
    max(CASE WHEN month='2026-06-01' THEN share END) AS jun_share,
    max(CASE WHEN month='2026-07-01' THEN share END) AS jul_share
  FROM s GROUP BY 1
)
SELECT vendor_id,
       round(may_share,2) AS may_pct, round(jun_share,2) AS jun_pct,
       round(jul_share,2) AS jul_pct,
       round(jul_share-may_share,2) AS shift_pts
FROM p ORDER BY abs(jul_share-may_share) DESC NULLS LAST LIMIT 12
""", "Vendor share of trips — May vs July (top movers)")

rule("4 · VENDOR RATE — did anyone get worse?")
show("""
WITH r AS (
  SELECT vendor_id, month, count(*) AS trips, 100.0*avg(on_time) AS ota
  FROM t GROUP BY 1,2 HAVING count(*) >= 500
), p AS (
  SELECT vendor_id,
    max(CASE WHEN month='2026-05-01' THEN ota END) AS may_ota,
    max(CASE WHEN month='2026-07-01' THEN ota END) AS jul_ota,
    max(CASE WHEN month='2026-07-01' THEN trips END) AS jul_trips
  FROM r GROUP BY 1
)
SELECT vendor_id, round(may_ota,1) AS may_ota, round(jul_ota,1) AS jul_ota,
       round(jul_ota-may_ota,1) AS rate_shift, jul_trips
FROM p WHERE may_ota IS NOT NULL AND jul_ota IS NOT NULL
ORDER BY rate_shift LIMIT 12
""", "OTA by vendor — May vs July (worst movers)")

rule("5 · ⭐ MIX-RATE DECOMPOSITION — May → July")
show("""
WITH v AS (
  SELECT vendor_id, month,
         count(*)*1.0/sum(count(*)) OVER (PARTITION BY month) AS w,
         avg(on_time) AS r
  FROM t GROUP BY 1,2
), o AS (
  SELECT month, avg(on_time) AS R FROM t GROUP BY 1
), j AS (
  SELECT a.vendor_id,
         a.w AS w0, a.r AS r0, b.w AS w1, b.r AS r1,
         (SELECT R FROM o WHERE month='2026-05-01') AS R0
  FROM (SELECT * FROM v WHERE month='2026-05-01') a
  FULL JOIN (SELECT * FROM v WHERE month='2026-07-01') b USING (vendor_id)
)
SELECT vendor_id,
  round(100*coalesce(w1,0)*(coalesce(r1,0)-coalesce(r0,0)), 2) AS rate_effect_pts,
  round(100*(coalesce(w1,0)-coalesce(w0,0))*(coalesce(r0,0)-R0), 2) AS mix_effect_pts,
  round(100*(coalesce(w1,0)*(coalesce(r1,0)-coalesce(r0,0))
           + (coalesce(w1,0)-coalesce(w0,0))*(coalesce(r0,0)-R0)), 2) AS total_pts
FROM j
ORDER BY abs(100*(coalesce(w1,0)*(coalesce(r1,0)-coalesce(r0,0))
           + (coalesce(w1,0)-coalesce(w0,0))*(coalesce(r0,0)-R0))) DESC
LIMIT 12
""", "Per-vendor contribution to the campus OTA change")

show("""
WITH v AS (
  SELECT vendor_id, month,
         count(*)*1.0/sum(count(*)) OVER (PARTITION BY month) AS w,
         avg(on_time) AS r
  FROM t GROUP BY 1,2
), o AS (SELECT month, avg(on_time) AS R FROM t GROUP BY 1),
j AS (
  SELECT a.w AS w0, a.r AS r0, b.w AS w1, b.r AS r1,
         (SELECT R FROM o WHERE month='2026-05-01') AS R0
  FROM (SELECT * FROM v WHERE month='2026-05-01') a
  FULL JOIN (SELECT * FROM v WHERE month='2026-07-01') b USING (vendor_id)
)
SELECT
  round(100*sum(coalesce(w1,0)*(coalesce(r1,0)-coalesce(r0,0))), 3) AS sum_rate_pts,
  round(100*sum((coalesce(w1,0)-coalesce(w0,0))*(coalesce(r0,0)-R0)), 3) AS sum_mix_pts,
  round(100*sum(coalesce(w1,0)*(coalesce(r1,0)-coalesce(r0,0))
              + (coalesce(w1,0)-coalesce(w0,0))*(coalesce(r0,0)-R0)), 3) AS decomposed_total,
  round(100*((SELECT R FROM o WHERE month='2026-07-01')
           - (SELECT R FROM o WHERE month='2026-05-01')), 3) AS actual_delta
FROM j
""", "RECONCILIATION — decomposed total must equal actual delta")

rule("6 · DATA QUALITY — the documented messiness, measured")
show("""
SELECT
  count(*) AS rows,
  sum(CASE WHEN trip_id IS NULL THEN 1 ELSE 0 END) AS bad_trip_id,
  sum(CASE WHEN trip_date IS NULL THEN 1 ELSE 0 END) AS bad_date,
  sum(CASE WHEN delay_minutes IS NULL THEN 1 ELSE 0 END) AS null_delay,
  sum(CASE WHEN actual_end_epoch IS NULL THEN 1 ELSE 0 END) AS null_actual_end,
  sum(CASE WHEN planned_km IS NULL THEN 1 ELSE 0 END) AS null_planned_km,
  sum(CASE WHEN is_driver_nc IS NULL THEN 1 ELSE 0 END) AS null_driver_nc,
  sum(CASE WHEN traveled_km < 0 THEN 1 ELSE 0 END) AS negative_km,
  sum(CASE WHEN delay_minutes > 1440 THEN 1 ELSE 0 END) AS delay_over_24h
FROM trips
""")

print("\nprofile complete.\n")
