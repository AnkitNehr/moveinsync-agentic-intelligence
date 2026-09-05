"""
COST & BILLING -- round 2: verification of the round-1 signals.
Every claim in docs/findings/cost.md that came from round 1 gets an
artifact-check here.
Run:  .venv/bin/python tools/analysis/cost_round2.py
"""
import duckdb, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")
con = duckdb.connect()
con.sql("SET threads TO 8")


def hdr(t):
    print("\n" + "=" * 100); print(t); print("=" * 100)


def q(sql, n=60, title=None):
    if title: print("\n--- " + title)
    con.sql(sql).show(max_rows=n, max_width=250)


con.sql(f"""
CREATE OR REPLACE VIEW bill AS
SELECT TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id, trip_id AS trip_id_raw,
  business_unit, office, vendor, contract,
  CASE WHEN slab_name IN ('null','NA') THEN NULL ELSE slab_name END AS slab_name,
  strptime(cycle_start,'%B %d, %Y, %I:%M %p')::DATE AS cycle_start,
  date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE AS cycle_month,
  strftime(strptime(cycle_start,'%B %d, %Y, %I:%M %p'),'%Y-%m')
    || CASE WHEN strptime(cycle_start,'%B %d, %Y, %I:%M %p')::DATE
                 - date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE = 0
            THEN '-A' ELSE '-B' END AS cycle,
  TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS km,
  TRY_CAST(replace(trip_cost,',','') AS DOUBLE)     AS cost
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
""")

con.sql("""
CREATE OR REPLACE VIEW contract_class AS
SELECT contract,
       CASE WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) >= 95 THEN 'FIXED_RATE'
            WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) <= 20 THEN 'DISTANCE_BASED'
            ELSE 'MIXED' END AS contract_type
FROM bill GROUP BY 1
""")
con.sql("""CREATE OR REPLACE VIEW billx AS
           SELECT b.*, c.contract_type FROM bill b LEFT JOIN contract_class c USING (contract)""")

con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(planned_km AS DOUBLE)  AS planned_km,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")


# =========================================================== A. DUP TRIP_IDS
hdr("A. THE 6,999 DUPLICATE trip_ids -- double billing or ID reuse?")

q("""SELECT count(*) AS ride_rows, count(DISTINCT trip_id) AS distinct_ride_ids
     FROM trips""", title="is trip_id unique in ride_data?")

q("""SELECT n_per_id, count(*) AS n_ids FROM
     (SELECT trip_id, count(*) n_per_id FROM trips GROUP BY 1) GROUP BY 1 ORDER BY 1""",
  title="ride_data trip_id multiplicity")

q("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)=2)
     SELECT b.cycle_month, count(*) AS n_bill_rows
     FROM bill b JOIN d USING (trip_id) GROUP BY 1 ORDER BY 1""",
  title="which months do the dup-id bill rows fall in?")

q("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)=2)
     SELECT t.month AS ride_month, count(DISTINCT t.trip_id) AS n_ids,
            count(*) AS n_ride_rows
     FROM trips t JOIN d USING (trip_id) GROUP BY 1 ORDER BY 1""",
  title="do those same ids also appear twice in ride_data? (ID reuse test)")

q("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)=2)
     SELECT b.trip_id, b.cycle_month, b.office, b.vendor, b.contract, b.km, b.cost
     FROM bill b JOIN d USING (trip_id)
     ORDER BY b.trip_id LIMIT 12""",
  title="sample dup pairs, side by side")

# If ride_data also reuses the id across months, this is ID REUSE, not double billing.
q("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)=2)
     SELECT
       count(*) AS dup_ids,
       sum(CASE WHEN ride_rows=2 THEN 1 ELSE 0 END) AS also_2_rides,
       sum(CASE WHEN ride_rows=1 THEN 1 ELSE 0 END) AS only_1_ride,
       sum(CASE WHEN ride_rows=0 THEN 1 ELSE 0 END) AS no_ride
     FROM (SELECT d.trip_id, (SELECT count(*) FROM trips t WHERE t.trip_id=d.trip_id) AS ride_rows
           FROM d)""",
  title="VERDICT: dup bill ids that ALSO have 2 ride rows == id reuse, not double billing")


# ========================================================= B. AMIT / DV_PACKAGE
hdr("B. Amit Mikhailov Travel on DV_Package -- the 71 x Rs60k outliers")

q("""SELECT cycle_month, count(*) AS n, round(sum(cost),2) AS spend,
       round(min(cost),2) AS min_c, round(max(cost),2) AS max_c, round(avg(km),2) AS avg_km
     FROM bill WHERE vendor='Amit Mikhailov Travel' AND contract='DV_Package' AND cost>20000
     GROUP BY 1 ORDER BY 1""", title="when do the giant DV_Package charges happen?")

q("""SELECT b.trip_id_raw, b.cycle_month, b.office, b.km, b.cost,
       t.traveled_km, t.emp_actual, t.product_type, t.trip_date
     FROM bill b LEFT JOIN trips t USING (trip_id)
     WHERE b.vendor='Amit Mikhailov Travel' AND b.contract='DV_Package' AND b.cost>20000
     ORDER BY b.cost DESC LIMIT 15""",
  title="the actual rows -- do the rides exist and do they justify the cost?")

q("""SELECT
       CASE WHEN cost>20000 THEN 'giant (>20k)' WHEN cost>5000 THEN '5k-20k' ELSE 'normal' END AS band,
       count(*) AS n, round(sum(cost),2) AS spend, round(avg(km),2) AS avg_km,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),2) AS pct_of_vendor_contract_spend
     FROM bill WHERE vendor='Amit Mikhailov Travel' AND contract='DV_Package'
     GROUP BY 1 ORDER BY spend DESC""",
  title="ARTIFACT CHECK: how much of this vendor+contract spend is the giant tail?")

# does removing the tail put the vendor back in line with peers?
q("""SELECT vendor, count(*) AS n, round(avg(cost),2) AS avg_cost_all,
       round(avg(cost) FILTER (WHERE cost<=20000),2) AS avg_cost_ex_giant,
       count(*) FILTER (WHERE cost>20000) AS n_giant
     FROM bill WHERE contract='DV_Package'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY avg_cost_all DESC LIMIT 10""",
  title="DV_Package vendor ranking with and without the giant tail")

q("""SELECT contract, count(*) AS n, round(sum(cost),2) AS spend, round(max(cost),2) AS max_cost
     FROM bill WHERE cost>20000 GROUP BY 1 ORDER BY spend DESC""",
  title="ALL trips over Rs20,000 -- which contracts?")

q("""SELECT vendor, count(*) AS n, round(sum(cost),2) AS spend
     FROM bill WHERE cost>20000 GROUP BY 1 ORDER BY spend DESC""",
  title="ALL trips over Rs20,000 -- which vendors?")


# ================================================= C. FIXED_RATE 3x OUTLIERS
hdr("C. FIXED_RATE contracts billed 3x+ -- integer multiples of the base rate?")

q("""SELECT contract, round(median(cost),2) AS base_rate, count(*) AS n
     FROM bill WHERE contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML','4S-WOW150ORRNEW')
     GROUP BY 1""", title="base rate per bus contract")

q("""WITH base AS (SELECT contract, median(cost) AS m FROM bill
                   WHERE contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML','4S-WOW150ORRNEW')
                   GROUP BY 1)
     SELECT b.contract, round(b.cost/base.m, 2) AS multiple_of_base, count(*) AS n
     FROM bill b JOIN base USING (contract)
     WHERE b.cost > 3*base.m
     GROUP BY 1,2 ORDER BY 1, n DESC LIMIT 40""",
  title="ARTIFACT CHECK: are the 3x+ charges clean integer multiples? (=> aggregated trips)")

q("""WITH base AS (SELECT contract, median(cost) AS m FROM bill
                   WHERE contract IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML','4S-WOW150ORRNEW')
                   GROUP BY 1)
     SELECT b.contract,
       sum(CASE WHEN abs(b.cost/base.m - round(b.cost/base.m)) < 0.02 THEN 1 ELSE 0 END) AS near_integer_multiple,
       count(*) AS n_over_3x,
       round(100.0*sum(CASE WHEN abs(b.cost/base.m - round(b.cost/base.m)) < 0.02 THEN 1 ELSE 0 END)/count(*),2) AS pct_integer
     FROM bill b JOIN base USING (contract) WHERE b.cost > 3*base.m
     GROUP BY 1""", title="share of 3x+ charges that are near-integer multiples")

q("""SELECT b.contract, b.cost, b.km, t.traveled_km, t.emp_actual, t.cab_capacity,
       t.trip_direction, t.shift_type
     FROM bill b LEFT JOIN trips t USING (trip_id)
     WHERE b.contract='BUS-ORRNEW-TT' AND b.cost>5000
     ORDER BY b.cost DESC LIMIT 12""",
  title="do the big bus charges carry more passengers? (would justify aggregation)")


# ============================================== D. KM INFLATION -- 3 VENDORS
hdr("D. KM OVER-BILLING ISOLATED TO 3 VENDORS -- real or contract artifact?")

con.sql("""
CREATE OR REPLACE VIEW j AS
SELECT b.trip_id, b.vendor, b.contract, b.contract_type, b.office, b.cycle_month,
       b.km AS billed_km, b.cost, t.traveled_km, t.planned_km, t.month AS ride_month
FROM billx b JOIN trips t USING (trip_id)
""")

q("""SELECT vendor,
       count(*) AS n,
       sum(CASE WHEN billed_km=traveled_km THEN 1 ELSE 0 END) AS exact,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_billed_more,
       round(100.0*sum(CASE WHEN billed_km<traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_billed_less,
       round(avg(billed_km-traveled_km) FILTER (WHERE billed_km>traveled_km),2) AS avg_uplift_km
     FROM j WHERE billed_km>0 AND traveled_km>0 AND contract_type='DISTANCE_BASED'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_billed_more DESC""",
  title="per-vendor share of trips where billed km EXCEEDS traveled km")

q("""SELECT vendor, contract, count(*) AS n,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_billed_more,
       round(sum(billed_km-traveled_km),1) AS extra_km
     FROM j WHERE billed_km>0 AND traveled_km>0 AND contract_type='DISTANCE_BASED'
       AND vendor IN ('Anjali Mikhailov Travel','Rahul Mikhailov Travel','Rohan Mikhailov Travel')
     GROUP BY 1,2 HAVING count(*)>=200 ORDER BY pct_billed_more DESC LIMIT 20""",
  title="which CONTRACTS do the 3 km-inflating vendors inflate on?")

# The decisive test: do OTHER vendors on the SAME contract also inflate?
q("""SELECT contract, vendor, count(*) AS n,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_billed_more,
       round(sum(billed_km-traveled_km),1) AS extra_km,
       round(avg(billed_km-traveled_km) FILTER (WHERE billed_km>traveled_km),2) AS avg_uplift
     FROM j WHERE billed_km>0 AND traveled_km>0 AND contract IN ('4Seater','3S_Jan2024_CNG_AC','6Seater')
     GROUP BY 1,2 HAVING count(*)>=500 ORDER BY contract, pct_billed_more DESC""",
  title="DECISIVE: same contract, all vendors -- is inflation vendor-specific or contract-wide?")

q("""SELECT office, count(*) AS n,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_billed_more
     FROM j WHERE billed_km>0 AND traveled_km>0 AND contract_type='DISTANCE_BASED'
     GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_billed_more DESC""",
  title="ARTIFACT CHECK: is km inflation actually an OFFICE/GPS effect, not a vendor one?")

q("""SELECT round(billed_km-traveled_km,1) AS delta, count(*) AS n
     FROM j WHERE billed_km>traveled_km AND traveled_km>0
       AND vendor IN ('Anjali Mikhailov Travel','Rahul Mikhailov Travel','Rohan Mikhailov Travel')
     GROUP BY 1 ORDER BY n DESC LIMIT 20""",
  title="shape of the uplift -- flat add-on, or proportional?")

q("""SELECT
       round(sum((billed_km-traveled_km) * (cost/nullif(billed_km,0))),2) AS rupees_on_extra_km,
       count(*) AS n_trips_with_uplift
     FROM j WHERE billed_km>traveled_km AND traveled_km>0 AND contract_type='DISTANCE_BASED'
       AND vendor IN ('Anjali Mikhailov Travel','Rahul Mikhailov Travel','Rohan Mikhailov Travel')""",
  title="rupee value of the extra km, 3 vendors")


# ================================================= E. ZERO-COST BILLING ROWS
hdr("E. THE 715 ZERO-COST BILL ROWS -- billing failures?")

q("""SELECT contract, contract_type, count(*) AS n,
       sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END) AS n_slab_null,
       round(avg(km),2) AS avg_km
     FROM billx WHERE cost=0 GROUP BY 1,2 ORDER BY n DESC LIMIT 25""",
  title="zero-cost rows by contract")

q("""SELECT count(*) AS zero_cost_rows,
       sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END) AS with_null_slab,
       round(100.0*sum(CASE WHEN slab_name IS NULL THEN 1 ELSE 0 END)/count(*),2) AS pct_null_slab
     FROM billx WHERE cost=0""",
  title="do zero-cost rows coincide with missing slab?")

q("""SELECT
       (SELECT count(*) FROM billx WHERE slab_name IS NULL
          AND contract IN (SELECT contract FROM billx GROUP BY 1
                           HAVING bool_or(slab_name IS NULL) AND NOT bool_and(slab_name IS NULL)))
         AS genuinely_missing_slab_rows,
       (SELECT count(*) FROM billx WHERE slab_name IS NULL AND cost=0
          AND contract IN (SELECT contract FROM billx GROUP BY 1
                           HAVING bool_or(slab_name IS NULL) AND NOT bool_and(slab_name IS NULL)))
         AS of_which_billed_zero""",
  title="VERDICT: on slab-based contracts, does a missing slab mean a Rs0 bill?")

q("""SELECT b.contract, b.vendor, count(*) AS n, round(avg(b.km),2) AS avg_billed_km,
       round(avg(t.traveled_km),2) AS avg_traveled_km,
       round(avg(bc.normal_cost),2) AS peer_avg_cost,
       round(count(*)*avg(bc.normal_cost),2) AS revenue_leak_estimate
     FROM billx b
     LEFT JOIN trips t USING (trip_id)
     JOIN (SELECT contract AS c2, avg(cost) AS normal_cost FROM billx WHERE cost>0 GROUP BY 1)
       bc ON bc.c2=b.contract
     WHERE b.cost=0 AND b.slab_name IS NULL
       AND b.contract IN (SELECT contract FROM billx GROUP BY 1
                          HAVING bool_or(slab_name IS NULL) AND NOT bool_and(slab_name IS NULL))
     GROUP BY 1,2 ORDER BY n DESC LIMIT 20""",
  title="the un-billed trips: who ran them and what should they have cost?")

q("""SELECT cycle_month, count(*) AS n_zero_cost FROM billx WHERE cost=0 GROUP BY 1 ORDER BY 1""",
  title="zero-cost rows by month -- trend?")


# ============================================= F. CYCLE-B (16th) IS DIFFERENT
hdr("F. THE MID-MONTH CYCLE (16th->end) -- 100% distance-based, CPK 59 vs 82")

q("""SELECT cycle, business_unit, count(*) AS n, round(sum(cost),2) AS spend
     FROM bill WHERE cycle LIKE '%-B' GROUP BY 1,2 ORDER BY 1,4 DESC""",
  title="who bills on the mid-month cycle?")

q("""SELECT CASE WHEN cycle LIKE '%-B' THEN 'cycle B (16th)' ELSE 'cycle A (1st)' END AS cyc,
       business_unit, office, count(*) AS n, round(sum(cost),2) AS spend
     FROM bill GROUP BY 1,2,3 ORDER BY 2,3,1""", n=40,
  title="ARTIFACT CHECK: is cycle B a separate BU/office, or the same ones split?")

q("""SELECT CASE WHEN cycle LIKE '%-B' THEN 'B' ELSE 'A' END AS cyc, contract,
       count(*) AS n, round(sum(cost),2) AS spend, round(avg(cost),2) AS avg_cost,
       round(sum(cost)/nullif(sum(km),0),2) AS cpk
     FROM bill WHERE business_unit='pinnacle-Slc'
     GROUP BY 1,2 HAVING count(*)>=200 ORDER BY contract, cyc""", n=40,
  title="same BU, cycle A vs B, by contract -- is the CPK gap a contract-mix artifact?")


# ================================= G. MEERA LEBEDEV CREDIT NOTES + ORPHANS
hdr("G. THE MAY CREDIT-NOTE EVENT (Meera Lebedev / 6S-PREMIUMNEW)")

q("""SELECT count(*) AS n_credit_rows, round(sum(cost),2) AS credit_value,
       count(DISTINCT trip_id) AS distinct_trips,
       sum(CASE WHEN t.trip_id IS NULL THEN 1 ELSE 0 END) AS credits_with_NO_ride
     FROM bill b LEFT JOIN trips t USING (trip_id) WHERE b.cost<0""",
  title="do the credit notes point at real trips?")

q("""SELECT b.office, b.vendor, count(*) AS n, round(sum(b.cost),2) AS credit_value,
       round(min(b.cost),2) AS biggest_single_credit
     FROM bill b WHERE b.cost<0 GROUP BY 1,2 ORDER BY credit_value""",
  title="credit notes by office+vendor")

q("""SELECT cycle_month, count(*) AS n, round(sum(cost),2) AS credit_value
     FROM bill WHERE cost<0 GROUP BY 1 ORDER BY 1""", title="credits by month")

# Pinecrest Office is tiny -- what does a -14.7M credit mean against its own spend?
q("""SELECT office, count(*) AS n, round(sum(cost),2) AS net_spend,
       round(sum(CASE WHEN cost>0 THEN cost ELSE 0 END),2) AS gross_charges,
       round(sum(CASE WHEN cost<0 THEN cost ELSE 0 END),2) AS credits
     FROM bill WHERE office='Pinecrest Office' GROUP BY 1""",
  title="Pinecrest Office: credits vs its own gross spend")

q("""SELECT count(*) AS orphan_rows_that_are_credits, round(sum(b.cost),2) AS value
     FROM bill b WHERE b.cost<0 AND b.trip_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_id=b.trip_id)""",
  title="ARTIFACT CHECK: how much of the negative orphan spend in May is these credits?")


# ================================ H. SIMPSON'S PARADOX ON COST/EMPLOYEE-TRIP
hdr("H. COST PER EMPLOYEE-TRIP -- blended flat, segments diverging")

q("""WITH s AS (
  SELECT b.cycle_month, b.contract_type, sum(b.cost) AS spend, sum(t.emp_actual) AS emp
  FROM billx b JOIN trips t USING (trip_id)
  WHERE b.contract_type IN ('DISTANCE_BASED','FIXED_RATE') GROUP BY 1,2)
SELECT contract_type,
  round(max(CASE WHEN cycle_month='2026-05-01' THEN spend/emp END),2) AS may_cpet,
  round(max(CASE WHEN cycle_month='2026-07-01' THEN spend/emp END),2) AS jul_cpet,
  round(100.0*(max(CASE WHEN cycle_month='2026-07-01' THEN spend/emp END)
             / max(CASE WHEN cycle_month='2026-05-01' THEN spend/emp END) - 1),2) AS pct_change,
  round(max(CASE WHEN cycle_month='2026-05-01' THEN emp END)) AS may_emp_trips,
  round(max(CASE WHEN cycle_month='2026-07-01' THEN emp END)) AS jul_emp_trips
FROM s GROUP BY 1""",
  title="May->July cost per employee-trip, by segment")

q("""WITH s AS (
  SELECT b.cycle_month, b.contract_type, sum(b.cost) AS spend, sum(t.emp_actual) AS emp
  FROM billx b JOIN trips t USING (trip_id)
  WHERE b.contract_type IN ('DISTANCE_BASED','FIXED_RATE') GROUP BY 1,2)
SELECT cycle_month,
  round(100.0*max(CASE WHEN contract_type='FIXED_RATE' THEN emp END)
        /sum(emp),2) AS fixed_share_of_emp_trips,
  round(sum(spend)/sum(emp),2) AS blended_cpet
FROM s GROUP BY 1 ORDER BY 1""",
  title="the mix that drives the blend: fixed-rate share of employee-trips")

# Decomposition: how much of the blended change is mix vs rate?
q("""WITH s AS (
  SELECT b.cycle_month, b.contract_type, sum(b.cost) AS spend, sum(t.emp_actual) AS emp
  FROM billx b JOIN trips t USING (trip_id)
  WHERE b.contract_type IN ('DISTANCE_BASED','FIXED_RATE') GROUP BY 1,2),
p AS (SELECT contract_type,
        max(CASE WHEN cycle_month='2026-05-01' THEN spend/emp END) AS r0,
        max(CASE WHEN cycle_month='2026-07-01' THEN spend/emp END) AS r1,
        max(CASE WHEN cycle_month='2026-05-01' THEN emp END)::DOUBLE AS e0,
        max(CASE WHEN cycle_month='2026-07-01' THEN emp END)::DOUBLE AS e1
      FROM s GROUP BY 1)
SELECT round(sum(r0*e0)/sum(e0),3) AS blended_may,
       round(sum(r1*e1)/sum(e1),3) AS blended_jul,
       round(sum(r0*e1)/sum(e1),3) AS blended_jul_at_may_rates,
       round(sum(r1*e1)/sum(e1) - sum(r0*e1)/sum(e1),3) AS rate_effect,
       round(sum(r0*e1)/sum(e1) - sum(r0*e0)/sum(e0),3) AS mix_effect
FROM p""", title="mix vs rate decomposition of the blended cost per employee-trip")

print("\n\nDONE")
