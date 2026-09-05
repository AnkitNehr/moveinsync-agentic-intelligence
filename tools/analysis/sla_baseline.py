#!/usr/bin/env python
"""Derive defensible SLA targets from the data instead of guessing constants."""
import duckdb, pathlib

RAW = pathlib.Path(__file__).resolve().parents[2] / "data" / "raw"
con = duckdb.connect()

con.sql(f"""
CREATE OR REPLACE VIEW b AS
SELECT business_unit, office, vendor, contract, slab_name,
  TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE) AS cost,
  TRY_CAST(total_trip_km AS DOUBLE) AS km,
  CASE WHEN contract ILIKE '%HYD%' OR contract ILIKE '%ORRNEW%'
         OR contract ILIKE '%EV-Z%' OR slab_name IN ('Short','Medium','Long')
       THEN 'FIXED_RATE' ELSE 'DISTANCE_BASED' END AS regime,
  date_trunc('month', strptime(cycle_start, '%B %d, %Y, %I:%M %p'))::DATE AS month
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
              ignore_errors=true, sample_size=-1)
""")

print("--- cost_per_km, DISTANCE_BASED only, by month ---")
print(con.sql("""
SELECT month, count(*) lines, round(sum(cost)/nullif(sum(km),0),2) cost_per_km
FROM b WHERE regime='DISTANCE_BASED' AND km > 0
GROUP BY month ORDER BY month
"""))

print("\n--- distribution of per-line cost/km (distance contracts, km>0) ---")
print(con.sql("""
SELECT round(quantile_cont(cost/km, 0.10),1) p10,
       round(quantile_cont(cost/km, 0.25),1) p25,
       round(median(cost/km),1)              p50,
       round(quantile_cont(cost/km, 0.75),1) p75,
       round(quantile_cont(cost/km, 0.90),1) p90,
       count(*) n
FROM b WHERE regime='DISTANCE_BASED' AND km > 0 AND cost > 0
"""))

print("\n--- by business unit (the grain that alerted) ---")
print(con.sql("""
SELECT business_unit, count(*) n, round(sum(cost)/nullif(sum(km),0),2) cost_per_km
FROM b WHERE regime='DISTANCE_BASED' AND km > 0
GROUP BY 1 ORDER BY 3 DESC
"""))

print("\n--- cost per TRIP, for the cost_per_trip SLA ---")
print(con.sql("""
SELECT month, count(*) n, round(avg(cost),1) avg_cost,
       round(median(cost),1) median_cost,
       round(quantile_cont(cost,0.90),1) p90_cost
FROM b GROUP BY month ORDER BY month
"""))
