#!/usr/bin/env python
"""Quirk #16 — negative distance in bill_data. Their dictionary only warns about emp_data."""
import duckdb, pathlib

RAW = pathlib.Path(__file__).resolve().parents[2] / "data" / "raw"
con = duckdb.connect()
con.sql(f"""
CREATE OR REPLACE VIEW b AS
SELECT business_unit, office, vendor, contract,
       TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE) AS cost,
       TRY_CAST(total_trip_km AS DOUBLE)               AS km
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
              ignore_errors=true, sample_size=-1)
""")

print("--- impossible values in bill_data ---")
print(con.sql("""
SELECT count(*) FILTER (WHERE km   < 0) AS neg_km_lines,
       count(*) FILTER (WHERE cost < 0) AS neg_cost_lines,
       round(min(km),2)   AS min_km,
       round(min(cost),2) AS min_cost,
       count(*)           AS total_lines
FROM b
"""))

print("\n--- negative km concentrated where? ---")
print(con.sql("""
SELECT business_unit,
       count(*) FILTER (WHERE km < 0)             AS neg_km_lines,
       round(sum(km) FILTER (WHERE km < 0), 1)    AS sum_negative_km,
       round(sum(cost) FILTER (WHERE km < 0), 0)  AS spend_on_those_lines,
       count(*)                                   AS total_lines
FROM b GROUP BY 1 ORDER BY 2 DESC
"""))

print("\n--- cost_per_km with negatives EXCLUDED (the correct figure) ---")
print(con.sql("""
SELECT business_unit, count(*) n,
       round(sum(cost)/nullif(sum(km),0),2) AS cost_per_km_clean
FROM b WHERE km > 0 GROUP BY 1 ORDER BY 3 DESC
"""))
