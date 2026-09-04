#!/usr/bin/env python
"""Is zero-km a broken pipeline, or just fixed-rate contracts? Decides how we frame it."""
import duckdb, pathlib

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
con = duckdb.connect()
con.sql(f"""
CREATE OR REPLACE VIEW b AS
SELECT business_unit, office, vendor, contract, slab_name,
       TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE) AS cost,
       TRY_CAST(total_trip_km AS DOUBLE) AS km,
       CAST(trip_id AS BIGINT) AS trip_id
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
              ignore_errors=true, sample_size=-1)
""")

print("--- Zero-km rate by contract (top 15 by volume) ---")
print(con.sql("""
SELECT contract, count(*) AS trips,
       round(100.0*avg(CASE WHEN km=0 THEN 1 ELSE 0 END),1) AS zero_km_pct,
       round(avg(cost),0) AS avg_cost
FROM b GROUP BY 1 ORDER BY trips DESC LIMIT 15
"""))

print("\n--- Zero-km rate by slab ---")
print(con.sql("""
SELECT coalesce(slab_name,'(null)') AS slab, count(*) AS trips,
       round(100.0*avg(CASE WHEN km=0 THEN 1 ELSE 0 END),1) AS zero_km_pct
FROM b GROUP BY 1 ORDER BY trips DESC LIMIT 12
"""))

print("\n--- Do those trips have real distance in ride_data? ---")
con.sql(f"""
CREATE OR REPLACE VIEW t AS
SELECT CAST(replace(trip_id, ',', '') AS BIGINT) AS trip_id,
       TRY_CAST(traveled_km AS DOUBLE) AS ride_km
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
              null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")
print(con.sql("""
SELECT CASE WHEN b.km = 0 THEN 'billed 0 km' ELSE 'billed > 0 km' END AS bucket,
       count(*) AS matched_trips,
       round(avg(t.ride_km),2) AS avg_actual_km_from_gps,
       round(sum(b.cost)/1e6,1) AS spend_millions
FROM b JOIN t USING (trip_id)
GROUP BY 1
"""))
