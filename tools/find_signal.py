#!/usr/bin/env python
"""
Signal hunt. The vendor-grain story is weak (mix effect ~= 0), so find where
the real movement actually is: which dimension, which metric, which month.

This is our anomaly detector, run by hand — whatever it surfaces is what the
demo should be built around.
"""
import duckdb, pathlib

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
con = duckdb.connect()

def rule(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

def show(sql, title=None):
    if title:
        print(f"\n--- {title} ---")
    print(con.sql(sql))

con.sql(f"""
CREATE OR REPLACE VIEW t AS
SELECT
    CAST(replace(trip_id, ',', '') AS BIGINT) AS trip_id,
    business_unit, office, product_type, vendor_id, trip_direction,
    shift_type, trip_nodal, delay_reason, actual_cab_fuel_type, route_source,
    date_trunc('month', strptime(trip_date, '%B %d, %Y')) AS month,
    strptime(trip_date, '%B %d, %Y')::DATE AS trip_date,
    TRY_CAST(replace(delay_minutes, ',', '') AS DOUBLE) AS delay_minutes,
    TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
    TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
    TRY_CAST(is_driver_nc AS BOOLEAN) AS is_driver_nc,
    TRY_CAST(is_cab_nc AS BOOLEAN)    AS is_cab_nc,
    TRY_CAST(actual_cab_capacity AS INT)   AS cab_capacity,
    TRY_CAST(actualemployee_cnt AS INT)    AS emp_actual,
    TRY_CAST(plannedemployee_cnt AS INT)   AS emp_planned,
    TRY_CAST(noshow_cnt AS INT)            AS noshow,
    CASE WHEN TRY_CAST(replace(delay_minutes, ',', '') AS DOUBLE) <= 5
         THEN 1 ELSE 0 END AS on_time
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
              null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")

rule("A · WHERE IS THE MOVEMENT?  OTA by dimension, May → June → July")
for dim in ["business_unit", "product_type", "trip_direction", "trip_nodal",
            "delay_reason", "route_source", "actual_cab_fuel_type"]:
    show(f"""
    WITH r AS (SELECT {dim} AS k, month, count(*) n, 100.0*avg(on_time) ota
               FROM t GROUP BY 1,2)
    SELECT k,
      round(max(CASE WHEN month='2026-05-01' THEN ota END),2) AS may,
      round(max(CASE WHEN month='2026-06-01' THEN ota END),2) AS jun,
      round(max(CASE WHEN month='2026-07-01' THEN ota END),2) AS jul,
      round(max(CASE WHEN month='2026-06-01' THEN ota END)
          - max(CASE WHEN month='2026-05-01' THEN ota END),2) AS jun_vs_may,
      max(CASE WHEN month='2026-06-01' THEN n END) AS jun_trips
    FROM r GROUP BY k ORDER BY jun_vs_may LIMIT 8
    """, f"by {dim}")

rule("B · OFFICE — the widest grain (18 offices)")
show("""
WITH r AS (SELECT office k, month, count(*) n, 100.0*avg(on_time) ota
           FROM t GROUP BY 1,2)
SELECT k,
  round(max(CASE WHEN month='2026-05-01' THEN ota END),2) AS may,
  round(max(CASE WHEN month='2026-06-01' THEN ota END),2) AS jun,
  round(max(CASE WHEN month='2026-07-01' THEN ota END),2) AS jul,
  round(max(CASE WHEN month='2026-06-01' THEN ota END)
      - max(CASE WHEN month='2026-05-01' THEN ota END),2) AS jun_vs_may,
  max(CASE WHEN month='2026-06-01' THEN n END) AS jun_trips
FROM r GROUP BY k HAVING max(CASE WHEN month='2026-06-01' THEN n END) > 1000
ORDER BY jun_vs_may LIMIT 12
""")

rule("C · WHAT DROVE JUNE?  delay-reason mix shift")
show("""
WITH d AS (
  SELECT month, delay_reason, count(*) n,
         100.0*count(*)/sum(count(*)) OVER (PARTITION BY month) AS share
  FROM t GROUP BY 1,2)
SELECT delay_reason,
  round(max(CASE WHEN month='2026-05-01' THEN share END),2) AS may_pct,
  round(max(CASE WHEN month='2026-06-01' THEN share END),2) AS jun_pct,
  round(max(CASE WHEN month='2026-07-01' THEN share END),2) AS jul_pct,
  round(max(CASE WHEN month='2026-06-01' THEN share END)
      - max(CASE WHEN month='2026-05-01' THEN share END),2) AS jun_shift
FROM d GROUP BY 1 ORDER BY jun_shift DESC
""", "Share of ALL trips by delay reason")

show("""
SELECT month, round(100.0*avg(CASE WHEN delay_reason='DRIVER' THEN 1 ELSE 0 END),2) AS driver_pct,
       round(100.0*avg(CASE WHEN delay_reason='TRAFFIC' THEN 1 ELSE 0 END),2) AS traffic_pct,
       round(100.0*avg(CASE WHEN delay_reason='EMPLOYEE' THEN 1 ELSE 0 END),2) AS employee_pct
FROM t GROUP BY month ORDER BY month
""", "Delay causes month over month")

rule("D · DAILY — is June a spike or a sustained shift?")
show("""
SELECT trip_date, count(*) n, round(100.0*avg(on_time),2) ota
FROM t WHERE trip_date BETWEEN '2026-05-25' AND '2026-06-30'
GROUP BY 1 ORDER BY ota LIMIT 15
""", "Worst 15 days (late May – June)")

rule("E · OTHER METRICS — is the story somewhere else entirely?")
show("""
SELECT month,
  round(100.0*avg(CASE WHEN is_driver_nc THEN 1 ELSE 0 END),2) AS driver_noncompliance_pct,
  round(100.0*avg(CASE WHEN is_cab_nc THEN 1 ELSE 0 END),2)    AS cab_noncompliance_pct,
  round(100.0*avg(CASE WHEN actual_escort THEN 1 ELSE 0 END),2) AS escort_pct,
  round(100.0*sum(noshow)/nullif(sum(emp_planned),0),2)         AS noshow_pct,
  round(avg(emp_actual*1.0/nullif(cab_capacity,0)),3)           AS occupancy,
  round(avg(traveled_km),2)                                     AS avg_km
FROM t GROUP BY month ORDER BY month
""", "Safety / compliance / utilisation by month")

rule("F · ALERTS — safety signal")
show(f"""
WITH a AS (
  SELECT business_unit, event_type, severity,
         date_trunc('month', strptime(start_time, '%B %d, %Y, %I:%M %p')) AS month
  FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true,
                ignore_errors=true, sample_size=-1))
SELECT event_type,
  sum(CASE WHEN month='2026-05-01' THEN 1 ELSE 0 END) AS may,
  sum(CASE WHEN month='2026-06-01' THEN 1 ELSE 0 END) AS jun,
  sum(CASE WHEN month='2026-07-01' THEN 1 ELSE 0 END) AS jul,
  round(100.0*(sum(CASE WHEN month='2026-07-01' THEN 1 ELSE 0 END)
             - sum(CASE WHEN month='2026-05-01' THEN 1 ELSE 0 END))
        / nullif(sum(CASE WHEN month='2026-05-01' THEN 1 ELSE 0 END),0),1) AS pct_change
FROM a GROUP BY 1 ORDER BY abs(coalesce(pct_change,0)) DESC
""", "Alert volume by type, May vs July")

rule("G · COST — the money view")
show(f"""
WITH b AS (
  SELECT business_unit, office, vendor,
         TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE) AS cost,
         TRY_CAST(total_trip_km AS DOUBLE) AS km,
         date_trunc('month', strptime(cycle_start, '%B %d, %Y, %I:%M %p')) AS month
  FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
                ignore_errors=true, sample_size=-1))
SELECT month, count(*) AS billed_trips,
  round(avg(cost),1) AS avg_cost,
  round(sum(cost)/1000000,2) AS total_cost_millions,
  round(sum(cost)/nullif(sum(km),0),2) AS cost_per_km,
  sum(CASE WHEN km = 0 THEN 1 ELSE 0 END) AS zero_km_trips
FROM b GROUP BY month ORDER BY month
""", "Cost by billing month")

print("\nsignal hunt complete.\n")
