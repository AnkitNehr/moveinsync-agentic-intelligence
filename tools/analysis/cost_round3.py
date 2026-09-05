"""
COST & BILLING -- round 3.
Round 2 killed two round-1 findings (the "Rs60k outlier trips" were OverHead
line items; the "km-inflating vendors" are confounded with contract family).
This file recomputes everything cleanly and pins down what is left.
Run:  .venv/bin/python tools/analysis/cost_round3.py
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
  trip_id='OverHead' AS is_overhead,
  business_unit, office, vendor, contract,
  CASE WHEN slab_name IN ('null','NA') THEN NULL ELSE slab_name END AS slab_name,
  date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE AS cycle_month,
  TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS km,
  TRY_CAST(replace(trip_cost,',','') AS DOUBLE)     AS cost
FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
""")
con.sql("""CREATE OR REPLACE VIEW contract_class AS
SELECT contract, CASE
  WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) >= 95 THEN 'FIXED_RATE'
  WHEN 100.0*sum(CASE WHEN km=0 THEN 1 ELSE 0 END)/count(*) <= 20 THEN 'DISTANCE_BASED'
  ELSE 'MIXED' END AS contract_type FROM bill GROUP BY 1""")
con.sql("""CREATE OR REPLACE VIEW billx AS
           SELECT b.*, c.contract_type FROM bill b LEFT JOIN contract_class c USING (contract)""")
# "trip rows only": no OverHead line items
con.sql("CREATE OR REPLACE VIEW billt AS SELECT * FROM billx WHERE NOT is_overhead")

con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit AS ride_bu, office AS ride_office,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")


# =============================================================== A. OVERHEAD
hdr("A. THE 'OverHead' LINE ITEMS -- a separate cost object, not a trip")

q("""SELECT count(*) AS n, round(sum(cost),2) AS spend, round(avg(cost),2) AS avg_cost,
       round(min(cost),2) AS min_cost, round(max(cost),2) AS max_cost,
       round(100.0*sum(cost)/(SELECT sum(cost) FROM bill),3) AS pct_of_total_spend,
       round(avg(km),3) AS avg_km
     FROM bill WHERE is_overhead""", title="OverHead scale")

q("""SELECT business_unit, office, vendor, contract, cycle_month, count(*) AS n,
       round(sum(cost),2) AS spend
     FROM bill WHERE is_overhead GROUP BY ALL ORDER BY spend DESC""",
  title="where OverHead is charged")

q("""SELECT round(100.0*sum(CASE WHEN is_overhead THEN cost ELSE 0 END)
                 /sum(cost),2) AS overhead_pct_of_office_spend,
       office, count(*) FILTER (WHERE is_overhead) AS n_overhead_rows,
       round(sum(cost),2) AS office_spend
     FROM bill GROUP BY office HAVING count(*) FILTER (WHERE is_overhead)>0
     ORDER BY overhead_pct_of_office_spend DESC""",
  title="OverHead as a share of the office it is charged to")

q("""SELECT
       round(avg(cost) FILTER (WHERE NOT is_overhead),2) AS avg_real_trip_cost,
       round(avg(cost) FILTER (WHERE is_overhead),2)     AS avg_overhead_line,
       round(avg(cost),2) AS avg_if_you_do_not_separate_them
     FROM bill WHERE vendor='Amit Mikhailov Travel' AND contract='DV_Package'""",
  title="why it matters: Amit Mikhailov on DV_Package")


# =================================== B. OUTLIERS RECOMPUTED WITHOUT OVERHEAD
hdr("B. COST OUTLIERS, OverHead EXCLUDED")

con.sql("""
CREATE OR REPLACE VIEW peer AS
SELECT b.*, median(cost) OVER w AS peer_med, count(*) OVER w AS peer_n
FROM billt b WINDOW w AS (PARTITION BY contract, coalesce(slab_name,'<null>'))
""")

q("""SELECT count(*) AS n_outliers, round(sum(cost),2) AS outlier_spend,
       round(sum(cost-peer_med),2) AS excess_over_median,
       round(100.0*count(*)/(SELECT count(*) FROM billt),4) AS pct_of_trips,
       round(100.0*sum(cost-peer_med)/(SELECT sum(cost) FROM billt),4) AS excess_pct_of_spend
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0""",
  title=">3x contract+slab median, real trips only")

q("""SELECT contract_type, contract, count(*) AS n, round(avg(peer_med),2) AS peer_med,
       round(avg(cost),2) AS avg_cost, round(max(cost),2) AS max_cost,
       round(sum(cost-peer_med),2) AS excess, round(avg(km),2) AS avg_km
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1,2 ORDER BY excess DESC LIMIT 20""",
  title="outlier excess by contract, OverHead excluded")

q("""SELECT vendor, count(*) AS n_outlier, round(sum(cost-peer_med),2) AS excess,
       round(100.0*count(*)/max(vn),3) AS pct_of_vendor_trips
     FROM peer p JOIN (SELECT vendor AS v2, count(*) AS vn FROM billt GROUP BY 1) ON v2=vendor
     WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY excess DESC LIMIT 12""",
  title="outlier excess by vendor, OverHead excluded")

# do the surviving outliers correspond to real rides?
q("""SELECT
       count(*) AS n_outliers,
       sum(CASE WHEN t.trip_id IS NULL THEN 1 ELSE 0 END) AS no_matching_ride,
       round(avg(t.emp_actual),2) AS avg_pax,
       round(avg(t.traveled_km),2) AS avg_traveled_km,
       round(avg(p.km),2) AS avg_billed_km
     FROM peer p LEFT JOIN trips t USING (trip_id)
     WHERE p.peer_n>=500 AND p.cost>3*p.peer_med AND p.peer_med>0""",
  title="ARTIFACT CHECK: do the surviving outliers have real rides behind them?")

q("""SELECT round(cost/peer_med,0) AS x_over_median, count(*) AS n,
       round(sum(cost-peer_med),2) AS excess
     FROM peer WHERE peer_n>=500 AND cost>3*peer_med AND peer_med>0
     GROUP BY 1 ORDER BY 1 LIMIT 20""",
  title="distribution of the multiple -- smooth tail or discrete jumps?")


# ==================== C. VENDOR COST PER TRIP, SAME CONTRACT, NO OVERHEAD
hdr("C. VENDOR COST-PER-TRIP WITHIN THE SAME CONTRACT (OverHead + credits excluded)")

q("""SELECT contract, vendor, count(*) AS n, round(avg(cost),2) AS avg_cost,
       round(first(ctr_avg),2) AS contract_avg,
       round(100.0*(avg(cost)-first(ctr_avg))/first(ctr_avg),2) AS pct_vs_contract,
       round((avg(cost)-first(ctr_avg))*count(*),2) AS excess_rupees
     FROM (SELECT b.*, avg(cost) OVER (PARTITION BY contract) AS ctr_avg
           FROM billt b WHERE cost>0)
     GROUP BY 1,2 HAVING count(*)>=500
     ORDER BY excess_rupees DESC LIMIT 20""",
  title="most expensive vendors vs their contract average (n>=500)")

q("""SELECT contract, count(DISTINCT vendor) AS n_vendors, count(*) AS n,
       round(sum(cost),2) AS spend,
       round(100.0*(max(v_avg)-min(v_avg))/min(v_avg),2) AS spread_pct,
       round(min(v_avg),2) AS cheapest_vendor_avg, round(max(v_avg),2) AS dearest_vendor_avg
     FROM (SELECT contract, vendor, avg(cost) AS v_avg, count(*) AS c, sum(cost) AS cost
           FROM billt WHERE cost>0 GROUP BY 1,2 HAVING count(*)>=500)
     GROUP BY 1 HAVING count(DISTINCT vendor)>=3 ORDER BY spend DESC LIMIT 15""",
  title="cheapest-to-dearest vendor spread WITHIN each contract (only vendors with n>=500)")

# apply the spread to the whole contract: what is the prize for levelling to best?
q("""WITH v AS (SELECT contract, vendor, avg(cost) AS v_avg, count(*) AS n
               FROM billt WHERE cost>0 GROUP BY 1,2 HAVING count(*)>=500),
     b AS (SELECT contract, min(v_avg) AS best FROM v GROUP BY 1)
     SELECT v.contract, sum(v.n) AS n_trips, round(sum(v.n*v.v_avg),2) AS actual_spend,
       round(sum(v.n*b.best),2) AS spend_at_best_vendor_rate,
       round(sum(v.n*(v.v_avg-b.best)),2) AS annualisable_saving_3mo
     FROM v JOIN b USING (contract) GROUP BY 1
     ORDER BY annualisable_saving_3mo DESC LIMIT 12""",
  title="prize for levelling every vendor to the cheapest on the same contract")


# ======================= D. KM UPLIFT: CONTRACT/BU RULE, NOT VENDOR BEHAVIOUR
hdr("D. THE KM UPLIFT IS A CONTRACT-FAMILY RULE, NOT VENDOR CHEATING")

con.sql("""
CREATE OR REPLACE VIEW j AS
SELECT b.trip_id, b.vendor, b.contract, b.contract_type, b.office, b.business_unit,
       b.cycle_month, b.km AS billed_km, b.cost, t.traveled_km
FROM billt b JOIN trips t USING (trip_id)
WHERE b.km>0 AND t.traveled_km>0
""")

q("""SELECT business_unit, count(*) AS n,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_uplifted,
       round(sum(billed_km-traveled_km),1) AS extra_km
     FROM j GROUP BY 1 ORDER BY pct_uplifted DESC""",
  title="DECISIVE: km uplift by BUSINESS UNIT")

q("""SELECT contract, count(DISTINCT vendor) AS n_vendors, count(*) AS n,
       round(100.0*sum(CASE WHEN billed_km>traveled_km THEN 1 ELSE 0 END)/count(*),2) AS pct_uplifted,
       round(sum(billed_km-traveled_km),1) AS extra_km,
       string_agg(DISTINCT business_unit) AS bus
     FROM j GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_uplifted DESC LIMIT 25""",
  title="km uplift by contract + how many vendors serve that contract")

q("""SELECT round(billed_km-traveled_km,2) AS uplift_km, count(*) AS n,
       round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
     FROM j WHERE billed_km>traveled_km GROUP BY 1 ORDER BY n DESC LIMIT 10""",
  title="the uplift is a FIXED add-on, not a percentage")

q("""SELECT contract, round(median(billed_km-traveled_km),2) AS median_uplift, count(*) AS n
     FROM j WHERE billed_km>traveled_km GROUP BY 1 HAVING count(*)>=200
     ORDER BY n DESC LIMIT 15""", title="median uplift per contract")

q("""SELECT round(sum(billed_km-traveled_km),1) AS extra_km_total,
       round(sum((billed_km-traveled_km)*(cost/billed_km)),2) AS rupees_on_extra_km,
       count(*) AS n_trips,
       round(100.0*sum((billed_km-traveled_km)*(cost/billed_km))
             /(SELECT sum(cost) FROM billt),3) AS pct_of_total_spend
     FROM j WHERE billed_km>traveled_km""",
  title="total rupee value of the km uplift, all vendors")


# ======================================== E. CONCENTRATION ON GROSS CHARGES
hdr("E. SPEND CONCENTRATION -- gross charges, credits and OverHead separated")

q("""SELECT vendor, count(*) AS n, round(sum(cost),2) AS gross_charges,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),3) AS pct,
       round(100.0*sum(sum(cost)) OVER (ORDER BY sum(cost) DESC)/sum(sum(cost)) OVER (),3) AS cum_pct
     FROM billt WHERE cost>0 GROUP BY 1 ORDER BY gross_charges DESC LIMIT 10""",
  title="top vendors by GROSS charges (real trips, positive rows only)")

q("""SELECT round(sum(sh*sh),1) AS hhi FROM
     (SELECT 100.0*sum(cost)/sum(sum(cost)) OVER () AS sh
      FROM billt WHERE cost>0 GROUP BY vendor)""",
  title="HHI on gross charges")

q("""SELECT business_unit, count(DISTINCT vendor) AS n_vendors,
       round(sum(cost),2) AS spend,
       round(max(sh),2) AS top_vendor_pct, arg_max(vendor, sh) AS top_vendor
     FROM (SELECT business_unit, vendor, sum(cost) AS cost,
                  100.0*sum(cost)/sum(sum(cost)) OVER (PARTITION BY business_unit) AS sh
           FROM billt WHERE cost>0 GROUP BY 1,2)
     GROUP BY 1 ORDER BY spend DESC""",
  title="vendor concentration by BUSINESS UNIT (the level a contract is signed at)")

# how much spend sits on a contract served by exactly ONE vendor?
q("""SELECT CASE WHEN n_vendors=1 THEN 'single-sourced contract'
                WHEN n_vendors<=3 THEN '2-3 vendors' ELSE '4+ vendors' END AS bucket,
       count(*) AS n_contracts, sum(n) AS n_trips, round(sum(spend),2) AS spend,
       round(100.0*sum(spend)/sum(sum(spend)) OVER (),2) AS pct_spend
     FROM (SELECT contract, count(DISTINCT vendor) AS n_vendors, count(*) AS n, sum(cost) AS spend
           FROM billt WHERE cost>0 GROUP BY 1)
     GROUP BY 1 ORDER BY spend DESC""",
  title="how much spend sits on single-sourced contracts?")

q("""SELECT contract, count(DISTINCT vendor) AS n_vendors, count(*) AS n,
       round(sum(cost),2) AS spend, any_value(vendor) AS the_only_vendor
     FROM billt WHERE cost>0 GROUP BY 1 HAVING count(DISTINCT vendor)=1 AND count(*)>=500
     ORDER BY spend DESC LIMIT 15""",
  title="the single-sourced contracts (n>=500)")


# =================================================== F. FINAL HEADLINE TABLE
hdr("F. HEADLINE NUMBERS, ALL DEFINITIONS CLEAN")

q("""SELECT
       round(sum(cost),2) AS net_billed,
       round(sum(cost) FILTER (WHERE cost>0),2) AS gross_charges,
       round(sum(cost) FILTER (WHERE cost<0),2) AS credit_notes,
       round(sum(cost) FILTER (WHERE is_overhead),2) AS overhead_lines,
       count(*) FILTER (WHERE NOT is_overhead) AS trip_rows
     FROM billx""", title="what the Rs834M is actually made of")

q("""SELECT contract_type, count(*) AS n, round(sum(cost),2) AS spend,
       round(100.0*sum(cost)/sum(sum(cost)) OVER (),2) AS pct,
       round(sum(cost)/nullif(sum(km),0),2) AS cpk_or_na
     FROM billt WHERE cost>0 GROUP BY 1 ORDER BY spend DESC""",
  title="clean segmentation of trip spend")

q("""SELECT cycle_month, count(*) AS trips, round(sum(cost),2) AS spend,
       round(sum(cost) FILTER (WHERE contract_type='DISTANCE_BASED')
             /nullif(sum(km) FILTER (WHERE contract_type='DISTANCE_BASED'),0),3) AS distance_cpk,
       round(avg(cost) FILTER (WHERE contract_type='FIXED_RATE'),2) AS fixed_avg_per_trip
     FROM billt WHERE cost>0 GROUP BY 1 ORDER BY 1""",
  title="the two unit-cost metrics that are actually valid, by month")

print("\n\nDONE")
