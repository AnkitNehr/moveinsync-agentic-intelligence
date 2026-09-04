#!/usr/bin/env python
import duckdb, pathlib

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
con = duckdb.connect()

con.sql(f"""
CREATE OR REPLACE VIEW b AS
SELECT business_unit, office, vendor, contract, slab_name,
       TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE) AS cost,
       TRY_CAST(total_trip_km AS DOUBLE)               AS km,
       date_trunc('month', strptime(cycle_start, '%B %d, %Y, %I:%M %p')) AS month
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
              ignore_errors=true, sample_size=-1)
""")

print("--- Cost by billing month ---")
print(con.sql("""
SELECT month, count(*) AS billed_trips,
       round(avg(cost),1)                      AS avg_cost,
       round(sum(cost)/1e6,2)                  AS total_millions,
       round(sum(cost)/nullif(sum(km),0),2)    AS cost_per_km,
       sum(CASE WHEN km = 0 THEN 1 ELSE 0 END) AS zero_km_trips,
       sum(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unparsed_cost
FROM b GROUP BY month ORDER BY month
"""))

print("\n--- Cost per km by business unit, May vs July ---")
print(con.sql("""
WITH x AS (SELECT business_unit k, month, sum(cost)/nullif(sum(km),0) cpk, count(*) n
           FROM b GROUP BY 1,2)
SELECT k,
  round(max(CASE WHEN month='2026-05-01' THEN cpk END),2) AS may,
  round(max(CASE WHEN month='2026-07-01' THEN cpk END),2) AS jul,
  round(100.0*(max(CASE WHEN month='2026-07-01' THEN cpk END)
             / nullif(max(CASE WHEN month='2026-05-01' THEN cpk END),0) - 1),1) AS pct_change
FROM x GROUP BY k ORDER BY pct_change DESC NULLS LAST
"""))

print("\n--- Zero-km-but-billed: the cost anomaly ---")
print(con.sql("""
SELECT month, count(*) AS zero_km_billed, round(sum(cost),0) AS wasted_spend
FROM b WHERE km = 0 AND cost > 0 GROUP BY month ORDER BY month
"""))
