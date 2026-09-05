"""
COST & BILLING -- round 4: harden the two money findings.
 1) vendor price spread within the same contract -> control for slab AND office
 2) the 3x/4x cost outliers -> what actually distinguishes them
Run:  .venv/bin/python tools/analysis/cost_round4.py
"""
import duckdb, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")
con = duckdb.connect(); con.sql("SET threads TO 8")


def hdr(t):
    print("\n" + "=" * 100); print(t); print("=" * 100)


def q(sql, n=60, title=None):
    if title: print("\n--- " + title)
    con.sql(sql).show(max_rows=n, max_width=250)


con.sql(f"""
CREATE OR REPLACE VIEW billt AS
SELECT TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, vendor, contract,
  CASE WHEN slab_name IN ('null','NA') THEN NULL ELSE slab_name END AS slab_name,
  date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE AS cycle_month,
  TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS km,
  TRY_CAST(replace(trip_cost,',','') AS DOUBLE)     AS cost
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
WHERE trip_id <> 'OverHead'
""")
con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  trip_direction, shift_type, product_type,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
  TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")


# ============================================= 1. BUS-ORRNEW-TT VENDOR SPREAD
hdr("1. BUS-ORRNEW-TT: 35% vendor price spread -- real, or office/route mix?")

q("""SELECT count(*) AS n, count(slab_name) AS n_with_slab,
       count(DISTINCT office) AS offices, count(DISTINCT vendor) AS vendors,
       round(avg(km),3) AS avg_km
     FROM billt WHERE contract='BUS-ORRNEW-TT'""",
  title="contract shape (no slab => nothing else to control for but office)")

q("""SELECT office, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(median(cost),2) AS med_cost, round(sum(cost),2) AS spend
     FROM billt WHERE contract='BUS-ORRNEW-TT'
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY office, avg_cost DESC""",
  title="DECISIVE: BUS-ORRNEW-TT cost by office x vendor (n>=500)")

q("""SELECT office, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost
     FROM billt WHERE contract='BUS-ORRNEW-SML'
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY office, avg_cost DESC""",
  title="same test on BUS-ORRNEW-SML")

# do the dearer bus vendors carry more people? (would justify the price)
q("""SELECT b.vendor, count(*) AS n, round(avg(b.cost),2) AS avg_cost,
       round(avg(t.emp_actual),2) AS avg_pax, round(avg(t.cab_capacity),2) AS avg_seats,
       round(avg(b.cost)/nullif(avg(t.emp_actual),0),2) AS cost_per_pax,
       round(avg(t.traveled_km),2) AS avg_traveled_km
     FROM billt b JOIN trips t USING (trip_id)
     WHERE b.contract='BUS-ORRNEW-TT'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY avg_cost DESC""",
  title="ARTIFACT CHECK: do the dearer bus vendors carry more passengers / drive further?")


# ================================== 2. 4Seater LEVELLING PRIZE, WITHIN SLAB
hdr("2. THE LEVELLING PRIZE, COMPUTED WITHIN slab (apples to apples)")

q("""WITH v AS (SELECT contract, slab_name, vendor, avg(cost) AS v_avg, count(*) AS n
               FROM billt WHERE cost>0 AND slab_name IS NOT NULL
               GROUP BY 1,2,3 HAVING count(*)>=500),
     b AS (SELECT contract, slab_name, min(v_avg) AS best FROM v GROUP BY 1,2)
SELECT v.contract, sum(v.n) AS n_trips, round(sum(v.n*v.v_avg),2) AS actual_spend,
       round(sum(v.n*(v.v_avg-b.best)),2) AS saving_if_levelled_within_slab,
       round(100.0*sum(v.n*(v.v_avg-b.best))/sum(v.n*v.v_avg),2) AS pct_saving
FROM v JOIN b USING (contract, slab_name)
GROUP BY 1 ORDER BY saving_if_levelled_within_slab DESC LIMIT 12""",
  title="slab-controlled levelling prize (3 months, n>=500 per vendor-slab)")

q("""WITH v AS (SELECT contract, coalesce(slab_name,'<none>') AS slab, office, vendor,
                      avg(cost) AS v_avg, count(*) AS n
               FROM billt WHERE cost>0 GROUP BY 1,2,3,4 HAVING count(*)>=500),
     b AS (SELECT contract, slab, office, min(v_avg) AS best FROM v GROUP BY 1,2,3)
SELECT v.contract, count(DISTINCT v.office) AS offices, sum(v.n) AS n_trips,
       round(sum(v.n*v.v_avg),2) AS actual_spend,
       round(sum(v.n*(v.v_avg-b.best)),2) AS saving_if_levelled,
       round(100.0*sum(v.n*(v.v_avg-b.best))/sum(v.n*v.v_avg),2) AS pct_saving
FROM v JOIN b USING (contract, slab, office)
GROUP BY 1 ORDER BY saving_if_levelled DESC LIMIT 12""",
  title="STRICTEST: levelled within contract x slab x office")

q("""WITH v AS (SELECT contract, coalesce(slab_name,'<none>') AS slab, office, vendor,
                      avg(cost) AS v_avg, count(*) AS n
               FROM billt WHERE cost>0 GROUP BY 1,2,3,4 HAVING count(*)>=500),
     b AS (SELECT contract, slab, office, min(v_avg) AS best FROM v GROUP BY 1,2,3)
SELECT round(sum(v.n*(v.v_avg-b.best)),2) AS total_saving_3mo,
       round(sum(v.n*(v.v_avg-b.best))/3.0,2) AS per_month,
       sum(v.n) AS n_trips_covered,
       round(100.0*sum(v.n*(v.v_avg-b.best))/sum(v.n*v.v_avg),2) AS pct_of_covered_spend
FROM v JOIN b USING (contract, slab, office)""",
  title="TOTAL strict levelling prize")

# is the cheapest vendor cheap because of shorter trips? control km too
q("""SELECT contract, slab_name, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(avg(km),2) AS avg_km, round(avg(cost)/nullif(avg(km),0),2) AS cpk
     FROM billt WHERE contract='3S_Jan2024_CNG_AC' AND slab_name IS NOT NULL
     GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY slab_name, avg_cost DESC""",
  title="ARTIFACT CHECK: 3S_Jan2024_CNG_AC within slab -- same km, different price?")


# ============================================ 3. WHAT ARE THE 3x/4x OUTLIERS?
hdr("3. THE 3x AND 4x OUTLIERS -- what distinguishes them?")

con.sql("""
CREATE OR REPLACE VIEW peer AS
SELECT b.*, median(cost) OVER w AS peer_med, count(*) OVER w AS peer_n
FROM billt b WINDOW w AS (PARTITION BY contract, coalesce(slab_name,'<null>'))
""")

q("""SELECT contract, office, cycle_month, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(avg(peer_med),2) AS peer_med, round(sum(cost-peer_med),2) AS excess
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1,2,3 ORDER BY excess DESC LIMIT 20""",
  title="outliers by contract x office x month")

q("""SELECT p.contract, count(*) AS n,
       round(avg(t.emp_actual),2) AS avg_pax, round(avg(t.cab_capacity),2) AS avg_seats,
       round(avg(t.traveled_km),2) AS avg_traveled, round(avg(p.km),2) AS avg_billed_km,
       round(avg(t.delay_minutes),1) AS avg_delay,
       string_agg(DISTINCT t.trip_direction) AS directions
     FROM peer p LEFT JOIN trips t USING (trip_id)
     WHERE p.peer_n>=500 AND p.cost>3*p.peer_med AND p.peer_med>0
     GROUP BY 1 ORDER BY n DESC""",
  title="operational profile of the outlier trips")

# compare outlier trips to normal trips on the same contract
q("""SELECT p.contract,
       CASE WHEN p.cost>3*p.peer_med THEN 'outlier (>3x)' ELSE 'normal' END AS grp,
       count(*) AS n, round(avg(t.emp_actual),2) AS avg_pax,
       round(avg(t.traveled_km),2) AS avg_traveled, round(avg(t.delay_minutes),1) AS avg_delay,
       round(avg(p.cost),2) AS avg_cost
     FROM peer p LEFT JOIN trips t USING (trip_id)
     WHERE p.contract IN ('DV_Package','BUS-ORRNEW-TT','BUS-ORRNEW-SML') AND p.peer_med>0
     GROUP BY 1,2 ORDER BY 1,2""",
  title="DECISIVE: outlier vs normal trips on the same contract")

q("""SELECT round(cost,2) AS cost_value, count(*) AS n
     FROM peer WHERE contract='DV_Package' AND peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY n DESC LIMIT 15""",
  title="ARTIFACT CHECK: are the DV_Package outliers a handful of repeated fixed amounts?")

q("""SELECT round(sum(cost-peer_med),2) AS recoverable_excess, count(*) AS n_trips,
       count(DISTINCT vendor) AS vendors, count(DISTINCT office) AS offices
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0""",
  title="the audit-worthy number")

print("\n\nDONE")


# ===================== 4. NORMALISING THE BUS VENDOR SPREAD (appended round 4b)
hdr("4. BUS VENDOR SPREAD -- how much survives normalising for pax and distance?")

q("""SELECT b.contract, b.vendor, count(*) AS n,
       round(avg(b.cost),2) AS cost_per_trip,
       round(sum(b.cost)/nullif(sum(t.emp_actual),0),2) AS cost_per_pax,
       round(sum(b.cost)/nullif(sum(t.traveled_km),0),2) AS cost_per_traveled_km,
       round(avg(t.traveled_km),2) AS avg_km, round(avg(t.emp_actual),2) AS avg_pax
     FROM billt b JOIN trips t USING (trip_id)
     WHERE b.contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML') AND b.cost>0
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1, cost_per_trip DESC""",
  title="three normalisations of the same vendors")

q("""WITH v AS (SELECT b.contract, b.vendor, count(*) AS n, avg(b.cost) AS cpt,
                      sum(b.cost)/nullif(sum(t.emp_actual),0) AS cpp,
                      sum(b.cost)/nullif(sum(t.traveled_km),0) AS cpk
               FROM billt b JOIN trips t USING (trip_id)
               WHERE b.contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML') AND b.cost>0
               GROUP BY 1,2 HAVING count(*)>=500)
     SELECT contract,
       round(100.0*(max(cpt)-min(cpt))/min(cpt),1) AS spread_pct_per_trip,
       round(100.0*(max(cpp)-min(cpp))/min(cpp),1) AS spread_pct_per_pax,
       round(100.0*(max(cpk)-min(cpk))/min(cpk),1) AS spread_pct_per_km
     FROM v GROUP BY 1""",
  title="DECISIVE: does the spread survive normalisation?")

q("""WITH v AS (SELECT b.contract, b.vendor, count(*) AS n,
                      sum(b.cost) AS spend, sum(t.emp_actual) AS pax,
                      sum(b.cost)/nullif(sum(t.emp_actual),0) AS cpp
               FROM billt b JOIN trips t USING (trip_id)
               WHERE b.contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML') AND b.cost>0
               GROUP BY 1,2 HAVING count(*)>=500),
     best AS (SELECT contract, min(cpp) AS b FROM v GROUP BY 1)
     SELECT v.contract, sum(v.n) AS n_trips, round(sum(v.spend),2) AS spend,
       round(sum(v.pax*(v.cpp-best.b)),2) AS saving_at_best_cost_per_pax,
       round(100.0*sum(v.pax*(v.cpp-best.b))/sum(v.spend),2) AS pct
     FROM v JOIN best USING (contract) GROUP BY 1""",
  title="pax-normalised levelling prize on the two bus contracts")
