"""
COST & BILLING analysis (bill_data.csv) -- agent name: cost

Every number in docs/findings/cost.md comes from a query in this file.
Run:  .venv/bin/python tools/analysis/cost.py
"""
import duckdb, sys, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")

con = duckdb.connect()
con.sql("SET threads TO 8")


def hdr(t):
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def q(sql, n=60, title=None):
    if title:
        print("\n--- " + title)
    con.sql(sql).show(max_rows=n, max_width=250)


# ---------------------------------------------------------------- base views
con.sql(f"""
CREATE OR REPLACE VIEW bill_raw AS
SELECT * FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
                       sample_size=-1)
""")

# NOTE: trip_id contains the literal 'OverHead' -> TRY_CAST, never CAST.
#       slab_name uses the literal STRING 'null' (121,111 rows), not SQL NULL.
#       trip_cost + total_trip_km are comma-formatted.
con.sql("""
CREATE OR REPLACE VIEW bill AS
SELECT
  TRY_CAST(replace(trip_id, ',', '') AS BIGINT)              AS trip_id,
  trip_id                                                    AS trip_id_raw,
  business_unit, office, vendor, contract,
  CASE WHEN slab_name IN ('null','NA') THEN NULL ELSE slab_name END AS slab_name,
  slab_name                                                  AS slab_raw,
  strptime(cycle_start, '%B %d, %Y, %I:%M %p')::DATE         AS cycle_start,
  strptime(cycle_end,   '%B %d, %Y, %I:%M %p')::DATE         AS cycle_end,
  date_trunc('month', strptime(cycle_start, '%B %d, %Y, %I:%M %p'))::DATE AS cycle_month,
  strftime(strptime(cycle_start, '%B %d, %Y, %I:%M %p'), '%Y-%m')
    || CASE WHEN strptime(cycle_start,'%B %d, %Y, %I:%M %p')::DATE
                 - date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE = 0
            THEN '-A' ELSE '-B' END                          AS cycle,
  TRY_CAST(replace(total_trip_km, ',', '') AS DOUBLE)        AS km,
  TRY_CAST(replace(trip_cost, ',', '') AS DOUBLE)            AS cost
FROM bill_raw
""")

con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  coalesce(trip_nodal,'NA') AS trip_nodal,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(planned_km AS DOUBLE) AS planned_km,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
  TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(noshow_cnt AS INT) AS noshow
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")


# ================================================================== 0. SANITY
hdr("0. SANITY / EDGE CASES")

q("""SELECT count(*) AS rows, count(trip_id) AS parseable_ids,
       sum(CASE WHEN trip_id_raw='OverHead' THEN 1 ELSE 0 END) AS overhead_rows,
       round(sum(cost),2) AS total_spend,
       round(sum(CASE WHEN trip_id_raw='OverHead' THEN cost ELSE 0 END),2) AS overhead_spend
     FROM bill""", title="row + OverHead accounting")

q("""SELECT sign(cost) AS cost_sign, count(*) AS n, round(sum(cost),2) AS spend
     FROM bill GROUP BY 1 ORDER BY 1""", title="negative / zero / positive cost")

q("""SELECT business_unit, office, vendor, contract, slab_raw, km, cost
     FROM bill WHERE cost < 0 ORDER BY cost LIMIT 15""",
  title="the negative-cost rows (credit notes?)")

q("""SELECT count(*) AS n_neg, round(sum(cost),2) AS neg_spend,
       count(DISTINCT vendor) AS vendors, count(DISTINCT contract) AS contracts
     FROM bill WHERE cost<0""", title="negative cost scale")

q("""SELECT n_dup, count(*) AS n_trip_ids FROM
     (SELECT trip_id, count(*) n_dup FROM bill WHERE trip_id IS NOT NULL GROUP BY 1)
     GROUP BY 1 ORDER BY 1""", title="duplicate trip_id in bill_data")

# Are the duplicate trip_ids a real double-bill or two legitimate legs?
q("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL
                GROUP BY 1 HAVING count(*)=2)
     SELECT
       count(*) AS dup_trip_ids,
       sum(CASE WHEN same_cycle THEN 1 ELSE 0 END) AS same_cycle,
       sum(CASE WHEN same_vendor THEN 1 ELSE 0 END) AS same_vendor,
       sum(CASE WHEN same_contract THEN 1 ELSE 0 END) AS same_contract,
       sum(CASE WHEN same_cycle AND same_vendor AND same_contract AND same_cost THEN 1 ELSE 0 END) AS exact_dupe,
       round(sum(second_cost),2) AS spend_on_2nd_row
     FROM (
       SELECT b.trip_id,
              count(DISTINCT b.cycle)=1  AS same_cycle,
              count(DISTINCT b.vendor)=1 AS same_vendor,
              count(DISTINCT b.contract)=1 AS same_contract,
              count(DISTINCT b.cost)=1   AS same_cost,
              min(b.cost)                AS second_cost
       FROM bill b JOIN d USING (trip_id) GROUP BY 1)""",
  title="are duplicate trip_ids exact double-bills?")


# ============================================== 1. CONTRACT-TYPE SEGMENTATION
hdr("1. CONTRACT SEGMENTATION -- FIXED_RATE vs DISTANCE_BASED")

# Classify each contract by the share of its trips billed with km=0.
con.sql("""
CREATE OR REPLACE VIEW contract_class AS
SELECT contract,
       count(*) AS n,
       round(sum(cost),2) AS spend,
       round(100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*),2) AS pct_zero_km,
       -- correlation of cost with km among the non-zero-km rows
       round(corr(cost, km) FILTER (WHERE km>0), 3) AS corr_cost_km,
       CASE
         WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) >= 95 THEN 'FIXED_RATE'
         WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) <= 20 THEN 'DISTANCE_BASED'
         ELSE 'MIXED'
       END AS contract_type
FROM bill GROUP BY 1
""")

q("""SELECT * FROM contract_class ORDER BY spend DESC""", n=60,
  title="every contract: zero-km share, cost~km correlation, class")

q("""SELECT contract_type, count(*) AS n_contracts, sum(n) AS n_trips,
       round(sum(spend),2) AS spend,
       round(100.0*sum(spend)/sum(sum(spend)) OVER (),2) AS pct_spend
     FROM contract_class GROUP BY 1 ORDER BY spend DESC""",
  title="spend split by contract type")

con.sql("""
CREATE OR REPLACE VIEW billx AS
SELECT b.*, c.contract_type, c.pct_zero_km
FROM bill b LEFT JOIN contract_class c USING (contract)
""")

# ARTIFACT CHECK: is the MIXED bucket real, or one contract used two ways?
q("""SELECT contract, contract_type, pct_zero_km, n, spend, corr_cost_km
     FROM contract_class WHERE contract_type='MIXED' ORDER BY spend DESC""",
  title="ARTIFACT CHECK: what is in MIXED?")

q("""SELECT contract, CASE WHEN km=0 THEN 'km=0' ELSE 'km>0' END AS bucket,
       count(*) AS n, round(avg(cost),2) AS avg_cost, round(min(cost),2) AS min_cost,
       round(max(cost),2) AS max_cost, round(avg(km),2) AS avg_km
     FROM billx WHERE contract_type='MIXED'
       AND contract IN (SELECT contract FROM contract_class WHERE contract_type='MIXED'
                        ORDER BY spend DESC LIMIT 6)
     GROUP BY 1,2 ORDER BY contract, bucket""",
  title="ARTIFACT CHECK: inside MIXED contracts, do km=0 rows cost the same as km>0?")


# ================================== 2. REAL COST PER KM (distance-based only)
hdr("2. REAL COST-PER-KM -- DISTANCE_BASED CONTRACTS ONLY")

q("""SELECT
       'ALL contracts (the meaningless blend)' AS scope,
       count(*) AS n, round(sum(cost),2) AS spend, round(sum(km),1) AS km,
       round(sum(cost)/nullif(sum(km),0),2) AS blended_cpk
     FROM billx WHERE cost>0
     UNION ALL
     SELECT 'DISTANCE_BASED only', count(*), round(sum(cost),2), round(sum(km),1),
            round(sum(cost)/nullif(sum(km),0),2)
     FROM billx WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0""",
  title="blended vs segmented cost-per-km")

q("""SELECT cycle, count(*) AS n, round(sum(cost),2) AS spend, round(sum(km),1) AS km,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk
     FROM billx WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0
     GROUP BY 1 ORDER BY 1""", title="distance-only CPK by billing cycle")

q("""SELECT contract, count(*) AS n, round(sum(cost),2) AS spend,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk,
       round(median(cost/km),3) AS median_cpk
     FROM billx WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0
     GROUP BY 1 HAVING count(*)>=500 ORDER BY spend DESC""",
  title="distance-only CPK by contract (n>=500)")

# vendor CPK WITHIN a single contract == apples to apples
q("""SELECT contract, vendor, count(*) AS n, round(sum(cost),2) AS spend,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk,
       round(avg(km),1) AS avg_km,
       round(sum(cost)/nullif(sum(km),0)
             - (max(ctr_cpk)),3) AS cpk_vs_contract
     FROM (
       SELECT b.*, sum(cost) OVER (PARTITION BY contract)/
                   nullif(sum(km) OVER (PARTITION BY contract),0) AS ctr_cpk
       FROM billx b WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0)
     GROUP BY 1,2 HAVING count(*)>=500
     ORDER BY abs(sum(cost)/nullif(sum(km),0) - max(ctr_cpk)) DESC LIMIT 30""",
  title="vendor CPK vs its own contract's CPK (n>=500) -- biggest gaps")

q("""SELECT office, count(*) AS n, round(sum(cost),2) AS spend,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk
     FROM billx WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0
     GROUP BY 1 HAVING count(*)>=500 ORDER BY cpk DESC""",
  title="distance-only CPK by office (n>=500)")

# ARTIFACT CHECK for office CPK spread: is it slab/trip-length mix?
q("""SELECT office, count(*) AS n, round(avg(km),1) AS avg_km,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk,
       round(median(km),1) AS med_km
     FROM billx WHERE contract_type='DISTANCE_BASED' AND km>0 AND cost>0
       AND contract='4Seater'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY cpk DESC""",
  title="ARTIFACT CHECK: office CPK inside ONE contract (4Seater) -- controls contract mix")


# ============================================ 3. CONTRACT MIX SHIFT BY CYCLE
hdr("3. CONTRACT-TYPE MIX SHIFT ACROSS THE 6 BILLING CYCLES")

q("""SELECT cycle, contract_type, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (PARTITION BY cycle),2) AS pct_of_cycle_spend
     FROM billx GROUP BY 1,2 ORDER BY 1,4 DESC""",
  title="contract-type share of spend, per cycle")

q("""SELECT cycle_month, contract_type, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (PARTITION BY cycle_month),2) AS pct_spend,
       round(100.0*count(*)/sum(count(*)) OVER (PARTITION BY cycle_month),2) AS pct_trips
     FROM billx GROUP BY 1,2 ORDER BY 1,4 DESC""",
  title="contract-type mix by MONTH (both cycles merged)")

q("""WITH m AS (
       SELECT contract, cycle_month, sum(cost) AS spend, count(*) AS n
       FROM billx GROUP BY 1,2),
     t AS (SELECT cycle_month, sum(spend) AS tot FROM m GROUP BY 1)
     SELECT m.contract,
       round(100.0*max(CASE WHEN m.cycle_month='2026-05-01' THEN m.spend END)/max(CASE WHEN t.cycle_month='2026-05-01' THEN t.tot END),3) AS may_pct,
       round(100.0*max(CASE WHEN m.cycle_month='2026-06-01' THEN m.spend END)/max(CASE WHEN t.cycle_month='2026-06-01' THEN t.tot END),3) AS jun_pct,
       round(100.0*max(CASE WHEN m.cycle_month='2026-07-01' THEN m.spend END)/max(CASE WHEN t.cycle_month='2026-07-01' THEN t.tot END),3) AS jul_pct,
       sum(m.n) AS n_total
     FROM m JOIN t USING (cycle_month) GROUP BY 1 HAVING sum(m.n)>=500
     ORDER BY abs(coalesce(round(100.0*max(CASE WHEN m.cycle_month='2026-07-01' THEN m.spend END)/max(CASE WHEN t.cycle_month='2026-07-01' THEN t.tot END),3),0)
                - coalesce(round(100.0*max(CASE WHEN m.cycle_month='2026-05-01' THEN m.spend END)/max(CASE WHEN t.cycle_month='2026-05-01' THEN t.tot END),3),0)) DESC
     LIMIT 20""",
  title="per-contract share of monthly spend, May vs Jun vs Jul (n>=500)")

# ARTIFACT CHECK: does the mid-month cycle (-B) behave differently?
q("""SELECT cycle, count(*) AS n, round(sum(cost),2) AS spend, round(avg(cost),2) AS avg_cost,
       round(100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*),2) AS pct_zero_km
     FROM billx GROUP BY 1 ORDER BY 1""",
  title="ARTIFACT CHECK: cycle A (1st) vs cycle B (16th) volumes")


# ==================================================== 4. SPEND CONCENTRATION
hdr("4. SPEND CONCENTRATION / VENDOR RISK")

q("""SELECT vendor, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),3) AS pct_spend,
       round(100.0*sum(sum(cost)) OVER (ORDER BY sum(cost) DESC)
             /sum(sum(cost)) OVER (),3) AS cum_pct
     FROM bill GROUP BY 1 ORDER BY spend DESC""", n=30,
  title="vendor spend concentration + cumulative")

q("""SELECT contract, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),3) AS pct_spend,
       round(100.0*sum(sum(cost)) OVER (ORDER BY sum(cost) DESC)
             /sum(sum(cost)) OVER (),3) AS cum_pct
     FROM bill GROUP BY 1 ORDER BY spend DESC LIMIT 15""",
  title="contract spend concentration")

q("""SELECT office, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),3) AS pct_spend
     FROM bill GROUP BY 1 ORDER BY spend DESC LIMIT 10""",
  title="office spend concentration")

# HHI on vendor spend
q("""SELECT round(sum(sh*sh),1) AS vendor_hhi, count(*) AS n_vendors
     FROM (SELECT 100.0*sum(cost)/sum(sum(cost)) OVER () AS sh
           FROM bill GROUP BY vendor)""",
  title="vendor Herfindahl-Hirschman Index (0-10000)")

# single-vendor offices = the real operational risk
q("""WITH ov AS (
       SELECT office, vendor, count(*) AS c, sum(cost) AS s,
              100.0*sum(cost)/sum(sum(cost)) OVER (PARTITION BY office) AS v_share
       FROM bill GROUP BY 1,2)
     SELECT office, count(*) AS n_vendors, sum(c) AS n_trips, round(sum(s),2) AS spend,
            round(max(v_share),2) AS top_vendor_pct,
            arg_max(vendor, v_share) AS top_vendor
     FROM ov GROUP BY office HAVING sum(c)>=500
     ORDER BY top_vendor_pct DESC LIMIT 20""",
  title="single-vendor dependency by office (n>=500)")

# --- the negative-spend vendor deserves its own look
q("""SELECT vendor, contract, cycle, count(*) AS n,
       round(sum(cost),2) AS net_spend,
       sum(CASE WHEN cost<0 THEN 1 ELSE 0 END) AS n_credit,
       round(sum(CASE WHEN cost<0 THEN cost ELSE 0 END),2) AS credits,
       round(sum(CASE WHEN cost>0 THEN cost ELSE 0 END),2) AS charges
     FROM bill WHERE vendor='Meera Lebedev Travel' OR contract='6S-PREMIUMNEW'
     GROUP BY 1,2,3 ORDER BY net_spend LIMIT 20""",
  title="Meera Lebedev / 6S-PREMIUMNEW breakdown")

q("""SELECT round(sum(cost),2) AS spend_as_loaded,
       round(sum(CASE WHEN cost>0 THEN cost ELSE 0 END),2) AS gross_charges,
       round(sum(CASE WHEN cost<0 THEN cost ELSE 0 END),2) AS total_credits,
       round(100.0*abs(sum(CASE WHEN cost<0 THEN cost ELSE 0 END))
             /sum(CASE WHEN cost>0 THEN cost ELSE 0 END),3) AS credit_pct_of_gross
     FROM bill""", title="credits as a share of gross charges")


# ====================================== 5. COST PER TRIP, SAME CONTRACT TYPE
hdr("5. COST PER TRIP -- APPLES TO APPLES WITHIN THE SAME CONTRACT")

q("""SELECT contract, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(median(cost),2) AS med_cost,
       round(avg(cost) - avg(avg(cost)) OVER (PARTITION BY contract),2) AS vs_contract_avg,
       round(100.0*(avg(cost) - first(ctr_avg))/first(ctr_avg),2) AS pct_vs_contract,
       round(sum(cost),2) AS spend,
       round((avg(cost) - first(ctr_avg))*count(*),2) AS excess_rupees
     FROM (SELECT b.*, avg(cost) OVER (PARTITION BY contract) AS ctr_avg FROM bill b)
     GROUP BY 1,2 HAVING count(*)>=500
     ORDER BY excess_rupees DESC LIMIT 25""",
  title="vendors costing MOST vs their contract average (n>=500), ranked by rupee excess")

q("""SELECT contract, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(100.0*(avg(cost) - first(ctr_avg))/first(ctr_avg),2) AS pct_vs_contract,
       round((avg(cost) - first(ctr_avg))*count(*),2) AS excess_rupees
     FROM (SELECT b.*, avg(cost) OVER (PARTITION BY contract) AS ctr_avg FROM bill b)
     GROUP BY 1,2 HAVING count(*)>=500
     ORDER BY excess_rupees ASC LIMIT 15""",
  title="vendors costing LEAST vs contract average (n>=500)")

# ARTIFACT CHECK: is the vendor gap just km / slab mix?
q("""SELECT contract, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(avg(km),2) AS avg_km,
       round(sum(cost)/nullif(sum(km),0),3) AS cpk,
       string_agg(DISTINCT coalesce(slab_name,'<null>')) AS slabs
     FROM bill WHERE contract='4Seater'
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY avg_cost DESC""",
  title="ARTIFACT CHECK: 4Seater vendor gap -- is it km or slab mix?")

q("""SELECT contract, slab_name, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(avg(km),2) AS avg_km
     FROM bill WHERE contract='4Seater' AND slab_name IS NOT NULL
     GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY slab_name, avg_cost DESC""",
  title="ARTIFACT CHECK: 4Seater cost per trip WITHIN the same slab")


# ================================================================ 6. OUTLIERS
hdr("6. COST OUTLIERS VS CONTRACT+SLAB NORM")

con.sql("""
CREATE OR REPLACE VIEW peer AS
SELECT b.*,
       median(cost) OVER w  AS peer_med,
       quantile_cont(cost, 0.99) OVER w AS peer_p99,
       count(*) OVER w      AS peer_n
FROM billx b
WINDOW w AS (PARTITION BY contract, coalesce(slab_name,'<null>'))
""")

q("""SELECT count(*) AS n_outliers, round(sum(cost),2) AS outlier_spend,
       round(sum(cost - peer_med),2) AS excess_over_median,
       round(100.0*count(*)/(SELECT count(*) FROM bill),3) AS pct_of_trips,
       round(100.0*sum(cost)/(SELECT sum(cost) FROM bill),3) AS pct_of_spend
     FROM peer WHERE peer_n>=500 AND cost > 3*peer_med AND peer_med>0""",
  title="trips costing >3x their contract+slab median (peer group n>=500)")

q("""SELECT contract, coalesce(slab_name,'<null>') AS slab, vendor,
       count(*) AS n, round(avg(peer_med),2) AS peer_median_cost,
       round(avg(cost),2) AS avg_outlier_cost, round(sum(cost),2) AS spend,
       round(sum(cost-peer_med),2) AS excess
     FROM peer WHERE peer_n>=500 AND cost > 3*peer_med AND peer_med>0
     GROUP BY 1,2,3 ORDER BY excess DESC LIMIT 25""",
  title="where the >3x outliers sit (vendor x contract x slab)")

q("""SELECT vendor, count(*) AS n_outlier, round(sum(cost-peer_med),2) AS excess,
       round(100.0*count(*)/max(vn),3) AS pct_of_vendor_trips_outlier
     FROM peer p JOIN (SELECT vendor AS v2, count(*) AS vn FROM bill GROUP BY 1) ON v2=vendor
     WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY excess DESC LIMIT 15""",
  title="outlier concentration by vendor")

# ARTIFACT CHECK: are outliers just long trips on a distance contract?
q("""SELECT contract_type,
       count(*) AS n_outliers,
       round(avg(km),1) AS avg_km_outlier,
       round(avg(peer_med),2) AS peer_med,
       round(avg(cost),2) AS avg_cost
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY n_outliers DESC""",
  title="ARTIFACT CHECK: outliers by contract type")

q("""SELECT
       CASE WHEN km=0 THEN 'km=0' WHEN km<=25 THEN '1-25' WHEN km<=50 THEN '26-50'
            WHEN km<=100 THEN '51-100' ELSE '>100' END AS km_band,
       count(*) AS n_outliers, round(sum(cost-peer_med),2) AS excess,
       round(avg(cost),2) AS avg_cost
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY n_outliers DESC""",
  title="ARTIFACT CHECK: do outliers have the km to justify the cost?")

# The killer check: outliers on FIXED_RATE contracts have no km justification
q("""SELECT contract, coalesce(slab_name,'<null>') AS slab, count(*) AS n,
       round(avg(peer_med),2) AS peer_med, round(avg(cost),2) AS avg_cost,
       round(max(cost),2) AS max_cost, round(sum(cost-peer_med),2) AS excess,
       round(avg(km),2) AS avg_km
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
       AND contract_type='FIXED_RATE'
     GROUP BY 1,2 ORDER BY excess DESC LIMIT 20""",
  title="FIXED_RATE outliers -- fixed price, but billed 3x+. km cannot explain these")


# ============================================================ 7. SLAB NULLS
hdr("7. slab_name NULLS")

q("""SELECT round(100.0*sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)/count(*),2) AS pct_null,
       sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END) AS n_null,
       round(sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END),2) AS null_spend,
       round(100.0*sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END)/sum(cost),2) AS pct_spend_null
     FROM bill""", title="overall slab null rate (string 'null' + 'NA' folded)")

q("""SELECT contract, count(*) AS n,
       sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END) AS n_null,
       round(100.0*sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)/count(*),2) AS pct_null,
       round(sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END),2) AS null_spend,
       max(contract_type) AS ctype
     FROM billx GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_null DESC, n DESC LIMIT 25""",
  title="slab nulls by contract (n>=500)")

q("""SELECT vendor, count(*) AS n,
       round(100.0*sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)/count(*),2) AS pct_null,
       round(sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END),2) AS null_spend
     FROM bill GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_null DESC LIMIT 15""",
  title="slab nulls by vendor (n>=500)")

# ARTIFACT CHECK: is slab null just "this contract has no slab concept"?
q("""SELECT
       CASE WHEN all_null THEN 'contract NEVER has a slab'
            WHEN any_null THEN 'contract SOMETIMES missing slab'
            ELSE 'contract ALWAYS has a slab' END AS pattern,
       count(*) AS n_contracts, sum(n) AS n_trips, round(sum(spend),2) AS spend,
       round(sum(null_spend),2) AS null_slab_spend
     FROM (SELECT contract, count(*) AS n, sum(cost) AS spend,
                  sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END) AS null_spend,
                  bool_and(slab_name IS NULL) AS all_null,
                  bool_or(slab_name IS NULL)  AS any_null
           FROM bill GROUP BY 1)
     GROUP BY 1 ORDER BY spend DESC""",
  title="ARTIFACT CHECK: structural (no slab concept) vs genuinely missing")

q("""SELECT contract, count(*) AS n, round(sum(cost),2) AS spend,
       sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END) AS n_null,
       round(100.0*sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)/count(*),2) AS pct_null,
       round(sum(CASE WHEN slab_name IS NULL THEN cost ELSE 0 END),2) AS null_spend,
       round(avg(cost) FILTER (WHERE slab_name IS NULL),2) AS avg_cost_null_slab,
       round(avg(cost) FILTER (WHERE slab_name IS NOT NULL),2) AS avg_cost_with_slab
     FROM bill GROUP BY 1
     HAVING count(*)>=500 AND sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)>0
        AND sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)<count(*)
     ORDER BY null_spend DESC LIMIT 20""",
  title="GENUINELY-MISSING slab: contracts that usually have a slab but sometimes do not")


# =============================================== 8. BILLED KM vs TRAVELED KM
hdr("8. BILLED KM vs RIDE_DATA TRAVELED KM")

con.sql("""
CREATE OR REPLACE VIEW joined AS
SELECT b.trip_id, b.vendor, b.contract, b.contract_type, b.office, b.cycle_month,
       b.slab_name, b.km AS billed_km, b.cost,
       t.traveled_km, t.planned_km, t.trip_date, t.emp_actual, t.emp_planned,
       t.noshow, t.cab_capacity, t.product_type
FROM billx b JOIN trips t USING (trip_id)
""")

q("""SELECT (SELECT count(*) FROM bill WHERE trip_id IS NOT NULL) AS bill_rows_with_id,
       (SELECT count(*) FROM trips WHERE trip_id IS NOT NULL) AS ride_rows,
       (SELECT count(*) FROM joined) AS matched_rows""",
  title="join coverage")

q("""SELECT count(*) AS n,
       round(sum(billed_km),1) AS billed_km, round(sum(traveled_km),1) AS traveled_km,
       round(sum(billed_km)-sum(traveled_km),1) AS delta_km,
       round(100.0*(sum(billed_km)-sum(traveled_km))/nullif(sum(traveled_km),0),2) AS pct_over
     FROM joined WHERE billed_km>0 AND traveled_km IS NOT NULL AND traveled_km>0""",
  title="systematic over/under-billing, distance rows only")

q("""SELECT contract_type, count(*) AS n,
       round(sum(billed_km),1) AS billed_km, round(sum(traveled_km),1) AS traveled_km,
       round(100.0*(sum(billed_km)-sum(traveled_km))/nullif(sum(traveled_km),0),2) AS pct_over,
       round(median(billed_km-traveled_km),2) AS med_delta
     FROM joined WHERE billed_km>0 AND traveled_km>0 GROUP BY 1 ORDER BY n DESC""",
  title="km delta by contract type")

q("""SELECT vendor, count(*) AS n,
       round(sum(billed_km),1) AS billed_km, round(sum(traveled_km),1) AS traveled_km,
       round(100.0*(sum(billed_km)-sum(traveled_km))/nullif(sum(traveled_km),0),2) AS pct_over,
       round(median(billed_km-traveled_km),2) AS med_delta_km,
       round(sum(billed_km-traveled_km) * (sum(cost)/nullif(sum(billed_km),0)),2) AS est_rupee_impact
     FROM joined WHERE billed_km>0 AND traveled_km>0 AND contract_type='DISTANCE_BASED'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_over DESC LIMIT 25""",
  title="over-billing by vendor, DISTANCE contracts, n>=500")

# ARTIFACT CHECK: does billed km track planned or traveled?
q("""SELECT count(*) AS n,
       round(corr(billed_km, traveled_km),4) AS corr_billed_traveled,
       round(corr(billed_km, planned_km),4)  AS corr_billed_planned,
       round(avg(abs(billed_km-traveled_km)),3) AS mae_vs_traveled,
       round(avg(abs(billed_km-planned_km)),3) AS mae_vs_planned,
       sum(CASE WHEN billed_km=traveled_km THEN 1 ELSE 0 END) AS exact_match_traveled,
       sum(CASE WHEN billed_km=planned_km  THEN 1 ELSE 0 END) AS exact_match_planned
     FROM joined WHERE billed_km>0 AND traveled_km>0 AND planned_km>0""",
  title="ARTIFACT CHECK: is billed_km copied from traveled_km or planned_km?")

q("""SELECT CASE WHEN billed_km-traveled_km=0 THEN 'exact'
                WHEN billed_km-traveled_km>0 THEN 'billed MORE'
                ELSE 'billed LESS' END AS dir,
       count(*) AS n, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct,
       round(avg(billed_km-traveled_km),3) AS avg_delta
     FROM joined WHERE billed_km>0 AND traveled_km>0 GROUP BY 1 ORDER BY n DESC""",
  title="direction of km discrepancy")


# ========================================================= 9. ORPHAN BILLING
hdr("9. ORPHAN BILLING (bill without ride, ride without bill)")

q("""SELECT count(*) AS bill_rows_no_ride, round(sum(cost),2) AS orphan_spend,
       round(100.0*sum(cost)/(SELECT sum(cost) FROM bill),3) AS pct_of_total_spend
     FROM billx b WHERE b.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_id=b.trip_id)""",
  title="BILLED but no ride record")

q("""SELECT vendor, contract, contract_type, count(*) AS n, round(sum(cost),2) AS orphan_spend
     FROM billx b WHERE b.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_id=b.trip_id)
     GROUP BY 1,2,3 ORDER BY orphan_spend DESC LIMIT 20""",
  title="orphan billing by vendor+contract")

q("""SELECT cycle_month, count(*) AS n, round(sum(cost),2) AS orphan_spend
     FROM billx b WHERE b.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_id=b.trip_id)
     GROUP BY 1 ORDER BY 1""", title="orphan billing by month")

q("""SELECT count(*) AS ride_rows_no_bill,
       round(100.0*count(*)/(SELECT count(*) FROM trips),2) AS pct_of_rides
     FROM trips t WHERE t.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)""",
  title="RIDE performed but never billed")

q("""SELECT month, count(*) AS unbilled_rides,
       round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
     FROM trips t WHERE t.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)
     GROUP BY 1 ORDER BY 1""", title="unbilled rides by month")

q("""SELECT business_unit, office, count(*) AS unbilled_rides
     FROM trips t WHERE t.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)
     GROUP BY 1,2 ORDER BY unbilled_rides DESC LIMIT 15""",
  title="unbilled rides by BU/office")

# ARTIFACT CHECK: are unbilled rides just July trips whose cycle hasn't closed?
q("""SELECT t.month, count(*) AS n_rides,
       sum(CASE WHEN EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id) THEN 1 ELSE 0 END) AS billed,
       round(100.0*sum(CASE WHEN EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id) THEN 1 ELSE 0 END)/count(*),2) AS pct_billed
     FROM trips t GROUP BY 1 ORDER BY 1""",
  title="ARTIFACT CHECK: billing coverage of rides by month")

# ARTIFACT CHECK: does the orphan bill row's trip exist in a DIFFERENT month's ride file?
q("""SELECT b.cycle_month, count(*) AS n
     FROM billx b WHERE b.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_id=b.trip_id)
     GROUP BY 1 ORDER BY 1""", title="ARTIFACT CHECK: orphan bills cluster in which cycle?")


# ================================================ 10. SPEND TREND / PER-EMP
hdr("10. SPEND TREND AND COST PER EMPLOYEE-TRIP")

q("""SELECT cycle_month, count(*) AS n_billed_trips, round(sum(cost),2) AS spend,
       round(avg(cost),2) AS avg_cost_per_trip,
       round(100.0*(sum(cost)/lag(sum(cost)) OVER (ORDER BY cycle_month)-1),2) AS mom_spend_pct,
       round(100.0*(count(*)/lag(count(*)) OVER (ORDER BY cycle_month)::DOUBLE-1),2) AS mom_trips_pct
     FROM bill GROUP BY 1 ORDER BY 1""", title="total spend trend by month")

q("""SELECT j.cycle_month, count(*) AS n_matched_trips,
       sum(j.emp_actual) AS employee_trips, round(sum(j.cost),2) AS spend,
       round(sum(j.cost)/nullif(sum(j.emp_actual),0),2) AS cost_per_employee_trip,
       round(sum(j.cost)/count(*),2) AS cost_per_trip,
       round(avg(j.emp_actual),3) AS avg_occupancy
     FROM joined j GROUP BY 1 ORDER BY 1""",
  title="cost per EMPLOYEE-trip (the metric that survives contract mix)")

q("""SELECT j.cycle_month, j.contract_type, count(*) AS n,
       sum(j.emp_actual) AS emp_trips, round(sum(j.cost),2) AS spend,
       round(sum(j.cost)/nullif(sum(j.emp_actual),0),2) AS cost_per_emp_trip,
       round(avg(j.emp_actual),3) AS avg_occupancy,
       round(avg(j.cab_capacity),2) AS avg_capacity,
       round(100.0*avg(j.emp_actual)/nullif(avg(j.cab_capacity),0),2) AS seat_fill_pct
     FROM joined j WHERE j.contract_type IS NOT NULL
     GROUP BY 1,2 ORDER BY 1,2""",
  title="cost per employee-trip by contract type + seat utilisation")

# empty / near-empty trips = money for nothing
q("""SELECT j.cycle_month, count(*) AS n_trips,
       sum(CASE WHEN j.emp_actual=0 THEN 1 ELSE 0 END) AS zero_pax_trips,
       round(100.0*sum(CASE WHEN j.emp_actual=0 THEN 1 ELSE 0 END)/count(*),2) AS pct_zero_pax,
       round(sum(CASE WHEN j.emp_actual=0 THEN j.cost ELSE 0 END),2) AS zero_pax_spend,
       round(100.0*sum(CASE WHEN j.emp_actual=0 THEN j.cost ELSE 0 END)/sum(j.cost),2) AS pct_spend_zero_pax
     FROM joined j WHERE j.emp_actual IS NOT NULL GROUP BY 1 ORDER BY 1""",
  title="trips billed with ZERO passengers")

q("""SELECT j.contract_type, j.contract, count(*) AS n,
       round(sum(j.cost),2) AS zero_pax_spend, round(avg(j.cost),2) AS avg_cost,
       round(avg(j.billed_km),2) AS avg_km, round(avg(j.noshow),2) AS avg_noshow,
       round(avg(j.emp_planned),2) AS avg_planned
     FROM joined j WHERE j.emp_actual=0
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY zero_pax_spend DESC LIMIT 20""",
  title="zero-passenger spend by contract (n>=500)")

# ARTIFACT CHECK: is emp_actual=0 real, or a null-ish default?
q("""SELECT emp_actual, count(*) AS n, round(avg(emp_planned),2) AS avg_planned,
       round(avg(noshow),2) AS avg_noshow, round(avg(cost),2) AS avg_cost
     FROM joined WHERE emp_actual IS NOT NULL AND emp_actual<=4
     GROUP BY 1 ORDER BY 1""",
  title="ARTIFACT CHECK: emp_actual=0 -- do planned+noshow corroborate it?")

q("""SELECT
       CASE WHEN emp_planned=noshow THEN 'planned == noshow (fully cancelled)'
            WHEN noshow=0 AND emp_planned=0 THEN 'nothing planned at all'
            ELSE 'other' END AS explanation,
       count(*) AS n, round(sum(cost),2) AS spend
     FROM joined WHERE emp_actual=0 GROUP BY 1 ORDER BY n DESC""",
  title="ARTIFACT CHECK: does noshow explain the zero-pax trips?")

print("\n\nDONE")
