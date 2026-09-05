#!/usr/bin/env python
"""
EMPLOYEE EXPERIENCE analysis (emp_Data.csv, rider-leg grain).

Every number in docs/findings/employees.md comes from a query in this file.
Run:  .venv/bin/python tools/analysis/employees.py [section]
"""
import sys
import duckdb

RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw"

con = duckdb.connect()
con.sql("SET threads TO 8")


def show(title, sql, maxw=200, rows=60):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    r = con.sql(sql)
    r.show(max_width=maxw, max_rows=rows)


# ---------------------------------------------------------------- views
con.sql(f"""
CREATE OR REPLACE VIEW emp_raw AS
SELECT * FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true,
                       sample_size=-1, union_by_name=true, null_padding=true,
                       ignore_errors=true)
""")

con.sql("""
CREATE OR REPLACE VIEW emp AS
SELECT
  business_unit, office, product_type,
  shift_type,
  TRY_CAST(replace(trip_id, ',', '') AS BIGINT)              AS trip_id,
  TRY_CAST(trip_date AS DATE)                                AS trip_date,
  date_trunc('month', TRY_CAST(trip_date AS DATE))::DATE     AS month,
  TRY_CAST(planned_pickup_epoch AS DOUBLE)                   AS pp,
  TRY_CAST(planned_drop_epoch   AS DOUBLE)                   AS pd,
  TRY_CAST(actual_pickup_epoch  AS DOUBLE)                   AS ap,
  TRY_CAST(actual_drop_epoch    AS DOUBLE)                   AS ad,
  TRY_CAST(planned_km  AS DOUBLE)                            AS planned_km,
  TRY_CAST(traveled_km AS DOUBLE)                            AS traveled_km,
  stwid,
  TRY_CAST(stwid AS BIGINT)                                  AS stwid_i,
  signintype, gender, emp_role, boarding_status,
  coalesce(not_boarding_reason, 'NULL_REASON')               AS nbr,
  is_no_show,
  CASE WHEN lower(is_no_show) = 'true' THEN 1
       WHEN lower(is_no_show) = 'false' THEN 0 END           AS no_show,
  -- pickup lateness in minutes (positive = late)
  CASE WHEN TRY_CAST(actual_pickup_epoch AS DOUBLE) IS NOT NULL
        AND TRY_CAST(planned_pickup_epoch AS DOUBLE) IS NOT NULL
       THEN (TRY_CAST(actual_pickup_epoch AS DOUBLE)
             - TRY_CAST(planned_pickup_epoch AS DOUBLE)) / 60.0 END AS pickup_late_min,
  CASE WHEN TRY_CAST(actual_drop_epoch AS DOUBLE) IS NOT NULL
        AND TRY_CAST(planned_drop_epoch AS DOUBLE) IS NOT NULL
       THEN (TRY_CAST(actual_drop_epoch AS DOUBLE)
             - TRY_CAST(planned_drop_epoch AS DOUBLE)) / 60.0 END AS drop_late_min,
  TRY_CAST(split_part(shift_type, ':', 1) AS INT)            AS shift_hour
FROM emp_raw
""")

# trip-level view (for direction / escort / vendor context)
con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, route_source,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes,
  TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
  TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(noshow_cnt AS INT) AS noshow,
  CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")

SEC = sys.argv[1] if len(sys.argv) > 1 else "all"


def want(n):
    return SEC in ("all", n)


# ============================================================ 0. PROFILE
if want("0"):
    show("0.1 row count + parse integrity", """
    SELECT count(*) AS rows,
           count(trip_id) AS trip_id_parsed,
           count(*) - count(trip_id) AS trip_id_null,
           count(trip_date) AS date_parsed,
           count(DISTINCT trip_id) AS distinct_trips,
           count(DISTINCT stwid) AS distinct_stwid,
           min(trip_date) AS min_d, max(trip_date) AS max_d
    FROM emp""")

    for c in ["signintype", "gender", "emp_role", "boarding_status",
              "not_boarding_reason", "is_no_show", "product_type",
              "business_unit", "office"]:
        show(f"0.2 distinct {c}", f"""
        SELECT coalesce({c},'<NULL>') AS v, count(*) n,
               round(100.0*count(*)/sum(count(*)) OVER (),3) pct
        FROM emp_raw GROUP BY 1 ORDER BY n DESC LIMIT 30""")

    show("0.3 shift_type cardinality", """
    SELECT count(DISTINCT shift_type) AS n_shifts,
           min(shift_type) mn, max(shift_type) mx FROM emp""")

    show("0.4 epoch null matrix", """
    SELECT pp IS NULL AS pp_null, pd IS NULL AS pd_null,
           ap IS NULL AS ap_null, ad IS NULL AS ad_null,
           count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
    FROM emp GROUP BY 1,2,3,4 ORDER BY n DESC""")

# ============================================================ 1. NO-SHOW
if want("1"):
    show("1.1 no-show rate by month (all legs)", """
    SELECT month, count(*) n,
           sum(no_show) no_shows,
           round(100.0*sum(no_show)/count(*),3) AS no_show_pct,
           count(*)-count(no_show) AS is_no_show_unparsed
    FROM emp GROUP BY 1 ORDER BY 1""")

    show("1.2 boarding_status x is_no_show x not_boarding_reason cross-tab", """
    SELECT boarding_status, is_no_show, nbr, count(*) n
    FROM emp GROUP BY 1,2,3 ORDER BY n DESC LIMIT 30""")

    show("1.3 no-show by signintype x month", """
    SELECT signintype, month, count(*) n, sum(no_show) ns,
           round(100.0*sum(no_show)/count(*),3) pct
    FROM emp GROUP BY 1,2 ORDER BY 1,2""")

    show("1.4 no-show by business_unit x month (n>=500)", """
    SELECT business_unit,
      count(*) FILTER (month='2026-05-01') n_may,
      round(100.0*sum(no_show) FILTER (month='2026-05-01')/nullif(count(*) FILTER (month='2026-05-01'),0),2) may,
      round(100.0*sum(no_show) FILTER (month='2026-06-01')/nullif(count(*) FILTER (month='2026-06-01'),0),2) jun,
      round(100.0*sum(no_show) FILTER (month='2026-07-01')/nullif(count(*) FILTER (month='2026-07-01'),0),2) jul,
      count(*) n_all,
      round(100.0*sum(no_show)/count(*),2) all_pct
    FROM emp GROUP BY 1 HAVING count(*)>=500 ORDER BY all_pct DESC""")

    show("1.5 no-show by office (n>=500)", """
    SELECT office, count(*) n, sum(no_show) ns, round(100.0*sum(no_show)/count(*),2) pct
    FROM emp GROUP BY 1 HAVING count(*)>=500 ORDER BY pct DESC""")

    show("1.6 no-show by shift_hour band (n>=500)", """
    SELECT shift_hour, count(*) n, sum(no_show) ns,
           round(100.0*sum(no_show)/count(*),2) pct
    FROM emp WHERE shift_hour IS NOT NULL
    GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")

    show("1.7 chronic shifts: shift_type x BU with worst no-show (n>=1000)", """
    SELECT business_unit, shift_type, count(*) n, sum(no_show) ns,
           round(100.0*sum(no_show)/count(*),2) pct
    FROM emp GROUP BY 1,2 HAVING count(*)>=1000 ORDER BY pct DESC LIMIT 20""")

    show("1.8 chronic shifts BEST (n>=1000)", """
    SELECT business_unit, shift_type, count(*) n, sum(no_show) ns,
           round(100.0*sum(no_show)/count(*),2) pct
    FROM emp GROUP BY 1,2 HAVING count(*)>=1000 ORDER BY pct ASC LIMIT 15""")

    show("1.9 no-show by product_type x month", """
    SELECT product_type, month, count(*) n, round(100.0*sum(no_show)/count(*),3) pct
    FROM emp GROUP BY 1,2 ORDER BY 1,2""")

# ============================================================ 2. NOT-BOARDING REASON
if want("2"):
    show("2.1 not_boarding_reason by month", """
    SELECT nbr,
      count(*) FILTER (month='2026-05-01') may,
      count(*) FILTER (month='2026-06-01') jun,
      count(*) FILTER (month='2026-07-01') jul,
      count(*) total
    FROM emp GROUP BY 1 ORDER BY total DESC""")

    show("2.2 nbr share among NON-boarded legs only, by month", """
    WITH nb AS (SELECT * FROM emp WHERE nbr<>'NULL_REASON')
    SELECT nbr,
      round(100.0*count(*) FILTER (month='2026-05-01')/sum(count(*) FILTER (month='2026-05-01')) OVER (),2) may_pct,
      round(100.0*count(*) FILTER (month='2026-06-01')/sum(count(*) FILTER (month='2026-06-01')) OVER (),2) jun_pct,
      round(100.0*count(*) FILTER (month='2026-07-01')/sum(count(*) FILTER (month='2026-07-01')) OVER (),2) jul_pct,
      count(*) n
    FROM nb GROUP BY 1 ORDER BY n DESC""")

    show("2.3 TRIP_CANCELLED_FROM_DASHBOARD rate (per all legs) by BU x month", """
    SELECT business_unit,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD' AND month='2026-05-01')
            /nullif(count(*) FILTER (month='2026-05-01'),0),3) may,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD' AND month='2026-06-01')
            /nullif(count(*) FILTER (month='2026-06-01'),0),3) jun,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD' AND month='2026-07-01')
            /nullif(count(*) FILTER (month='2026-07-01'),0),3) jul,
      count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD') n_cancel,
      count(*) n_all
    FROM emp GROUP BY 1 HAVING count(*)>=500 ORDER BY n_cancel DESC""")

    show("2.4 nbr by office (n_all>=500) - cancel & noncomm rates", """
    SELECT office, count(*) n_all,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD')/count(*),3) cancel_pct,
      round(100.0*count(*) FILTER (nbr='NON_COMMUNICATING')/count(*),3) noncomm_pct,
      round(100.0*count(*) FILTER (nbr='NO_SHOW')/count(*),3) noshow_pct
    FROM emp GROUP BY 1 HAVING count(*)>=500 ORDER BY cancel_pct DESC""")

    show("2.5 ARTIFACT CHECK: are dashboard cancels whole-trip or per-rider?", """
    WITH t AS (
      SELECT trip_id, count(*) legs,
             count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD') cancels
      FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT CASE WHEN cancels=0 THEN 'no cancel'
                WHEN cancels=legs THEN 'ALL legs cancelled'
                ELSE 'partial' END AS kind,
           count(*) trips, sum(legs) legs
    FROM t GROUP BY 1 ORDER BY trips DESC""")

    show("2.6 nbr x signintype", """
    SELECT signintype, nbr, count(*) n,
           round(100.0*count(*)/sum(count(*)) OVER (PARTITION BY signintype),3) pct_of_signintype
    FROM emp GROUP BY 1,2 ORDER BY signintype, n DESC""")

# ============================================================ 3. PICKUP PUNCTUALITY
if want("3"):
    show("3.1 pickup_late_min availability + summary", """
    SELECT count(*) AS n_rows, count(pickup_late_min) AS with_val,
           round(min(pickup_late_min),1) mn,
           round(quantile_cont(pickup_late_min,0.01),1) p1,
           round(quantile_cont(pickup_late_min,0.25),1) p25,
           round(quantile_cont(pickup_late_min,0.50),1) p50,
           round(quantile_cont(pickup_late_min,0.75),1) p75,
           round(quantile_cont(pickup_late_min,0.90),1) p90,
           round(quantile_cont(pickup_late_min,0.99),1) p99,
           round(max(pickup_late_min),1) mx,
           round(avg(pickup_late_min),2) mean
    FROM emp""")

    show("3.2 rider punctuality bands by month", """
    SELECT month, count(*) n,
      round(100.0*count(*) FILTER (pickup_late_min < -10)/count(*),2) early_gt10,
      round(100.0*count(*) FILTER (pickup_late_min BETWEEN -10 AND 5)/count(*),2) window_m10_p5,
      round(100.0*count(*) FILTER (pickup_late_min > 5 AND pickup_late_min<=15)/count(*),2) late_5_15,
      round(100.0*count(*) FILTER (pickup_late_min > 15 AND pickup_late_min<=30)/count(*),2) late_15_30,
      round(100.0*count(*) FILTER (pickup_late_min > 30)/count(*),2) late_gt30,
      round(100.0*count(*) FILTER (pickup_late_min<=5)/count(*),2) rider_ota_5
    FROM emp WHERE pickup_late_min IS NOT NULL GROUP BY 1 ORDER BY 1""")

    show("3.3 RIDER OTA (<=5min) vs TRIP OTA by month - the hiding test", """
    SELECT e.month,
      count(*) legs,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END),2) rider_ota,
      round(100.0*avg(CASE WHEN t.delay_minutes<=5 THEN 1.0 ELSE 0 END),2) trip_ota_at_leg_grain
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pickup_late_min IS NOT NULL AND t.delay_minutes IS NOT NULL
    GROUP BY 1 ORDER BY 1""")

    show("3.4 riders late>15 on trips that trip-OTA calls ON TIME", """
    SELECT e.month, count(*) legs_on_ontime_trips,
      count(*) FILTER (e.pickup_late_min>15) rider_late15,
      round(100.0*count(*) FILTER (e.pickup_late_min>15)/count(*),2) pct
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.delay_minutes<=5 AND e.pickup_late_min IS NOT NULL
    GROUP BY 1 ORDER BY 1""")

    show("3.5 rider late>15 rate by BU x month (n>=500/month)", """
    SELECT business_unit,
      count(*) FILTER (month='2026-05-01') n_may,
      round(100.0*count(*) FILTER (pickup_late_min>15 AND month='2026-05-01')/nullif(count(*) FILTER (month='2026-05-01'),0),2) may,
      round(100.0*count(*) FILTER (pickup_late_min>15 AND month='2026-06-01')/nullif(count(*) FILTER (month='2026-06-01'),0),2) jun,
      round(100.0*count(*) FILTER (pickup_late_min>15 AND month='2026-07-01')/nullif(count(*) FILTER (month='2026-07-01'),0),2) jul,
      count(*) n_all
    FROM emp WHERE pickup_late_min IS NOT NULL
    GROUP BY 1 HAVING count(*)>=1500 ORDER BY n_all DESC""")

    show("3.6 rider punctuality by leg position within trip (pickup order)", """
    WITH o AS (
      SELECT trip_id, pickup_late_min,
             row_number() OVER (PARTITION BY trip_id ORDER BY pp) AS seq,
             count(*) OVER (PARTITION BY trip_id) AS legs
      FROM emp WHERE trip_id IS NOT NULL AND pp IS NOT NULL AND pickup_late_min IS NOT NULL)
    SELECT seq, count(*) n,
           round(avg(pickup_late_min),2) avg_late,
           round(quantile_cont(pickup_late_min,0.5),2) med_late,
           round(100.0*count(*) FILTER (pickup_late_min>15)/count(*),2) pct_late15
    FROM o WHERE legs>=2 GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")

    show("3.7 pickup lateness by shift hour (n>=2000)", """
    SELECT shift_hour, count(*) n,
      round(avg(pickup_late_min),2) avg_late,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*),2) pct_late15
    FROM emp WHERE pickup_late_min IS NOT NULL AND shift_hour IS NOT NULL
    GROUP BY 1 HAVING count(*)>=2000 ORDER BY 1""")

# ============================================================ 4. NULL PICKUP/DROP
if want("4"):
    show("4.1 how many legs have null actual pickup AND/OR drop", """
    SELECT count(*) AS n_rows,
      count(*) FILTER (ap IS NULL) ap_null,
      count(*) FILTER (ad IS NULL) ad_null,
      count(*) FILTER (ap IS NULL AND ad IS NULL) both_null,
      count(*) FILTER (ap IS NULL AND ad IS NOT NULL) ap_only,
      count(*) FILTER (ap IS NOT NULL AND ad IS NULL) ad_only
    FROM emp""")

    show("4.2 null-actual legs explained by boarding_status / nbr", """
    SELECT boarding_status, nbr, is_no_show, count(*) n
    FROM emp WHERE ap IS NULL AND ad IS NULL
    GROUP BY 1,2,3 ORDER BY n DESC LIMIT 20""")

    show("4.3 UNEXPLAINED nulls: boarded but no actual epochs", """
    SELECT count(*) n FROM emp
    WHERE ap IS NULL AND ad IS NULL AND boarding_status='Boarded'""")

    show("4.4 null-actual concentration by BU / office", """
    SELECT business_unit, office, count(*) n_all,
      count(*) FILTER (ap IS NULL AND ad IS NULL) n_null,
      round(100.0*count(*) FILTER (ap IS NULL AND ad IS NULL)/count(*),2) pct
    FROM emp GROUP BY 1,2 HAVING count(*)>=500 ORDER BY pct DESC""")

    show("4.5 null-actual by month", """
    SELECT month, count(*) n,
      count(*) FILTER (ap IS NULL AND ad IS NULL) n_null,
      round(100.0*count(*) FILTER (ap IS NULL AND ad IS NULL)/count(*),2) pct
    FROM emp GROUP BY 1 ORDER BY 1""")

# ============================================================ 5. NEGATIVE KM
if want("5"):
    show("5.1 planned_km / traveled_km sign profile", """
    SELECT
      count(*) AS n_rows,
      count(*) FILTER (planned_km IS NULL) pk_null,
      count(*) FILTER (planned_km < 0) pk_neg,
      count(*) FILTER (planned_km = 0) pk_zero,
      count(*) FILTER (traveled_km IS NULL) tk_null,
      count(*) FILTER (traveled_km < 0) tk_neg,
      count(*) FILTER (traveled_km = 0) tk_zero,
      round(min(planned_km),3) pk_min, round(min(traveled_km),3) tk_min,
      round(max(planned_km),2) pk_max, round(max(traveled_km),2) tk_max
    FROM emp""")

    show("5.2 negative km distribution", """
    SELECT round(min(traveled_km),3) mn, round(quantile_cont(traveled_km,0.5),3) med,
           round(max(traveled_km),3) mx, count(*) n
    FROM emp WHERE traveled_km<0""")

    show("5.3 negative km by BU x office", """
    SELECT business_unit, office, count(*) n_all,
      count(*) FILTER (traveled_km<0 OR planned_km<0) n_neg,
      round(100.0*count(*) FILTER (traveled_km<0 OR planned_km<0)/count(*),3) pct
    FROM emp GROUP BY 1,2 HAVING count(*)>=500 ORDER BY pct DESC LIMIT 20""")

    show("5.4 do neg-km legs correlate with boarding_status / product / month?", """
    SELECT month, product_type, boarding_status, count(*) n_all,
      count(*) FILTER (traveled_km<0 OR planned_km<0) n_neg,
      round(100.0*count(*) FILTER (traveled_km<0 OR planned_km<0)/count(*),3) pct
    FROM emp GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY pct DESC LIMIT 20""")

    show("5.5 neg-km legs: are whole trips negative or single legs?", """
    WITH t AS (SELECT trip_id, count(*) legs,
                      count(*) FILTER (traveled_km<0) neg
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT CASE WHEN neg=0 THEN 'none' WHEN neg=legs THEN 'all legs neg' ELSE 'some legs neg' END k,
           count(*) trips FROM t GROUP BY 1 ORDER BY trips DESC""")

    show("5.6 exposure: distance-billed-equivalent km affected", """
    SELECT count(*) n_neg_legs,
           round(sum(traveled_km),2) sum_neg_km,
           round(sum(abs(traveled_km)),2) sum_abs_km
    FROM emp WHERE traveled_km<0""")

# ============================================================ 6. GENDER
if want("6"):
    show("6.1 gender split", """
    SELECT coalesce(gender,'<NULL>') g, count(*) n,
      round(100.0*count(*)/sum(count(*)) OVER (),2) pct,
      count(DISTINCT stwid) riders
    FROM emp GROUP BY 1 ORDER BY n DESC""")

    show("6.2 gender x punctuality + no-show", """
    SELECT coalesce(gender,'<NULL>') g, count(*) n,
      round(avg(pickup_late_min),2) avg_late,
      round(quantile_cont(pickup_late_min,0.5),2) med_late,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*) FILTER (pickup_late_min IS NOT NULL),2) pct_late15,
      round(100.0*avg(no_show),3) no_show_pct
    FROM emp GROUP BY 1 ORDER BY n DESC""")

    show("6.3 gender x night trips (shift 21:00-05:59) punctuality", """
    SELECT coalesce(gender,'<NULL>') g,
      CASE WHEN shift_hour>=21 OR shift_hour<6 THEN 'night' ELSE 'day' END band,
      count(*) n,
      round(avg(pickup_late_min),2) avg_late,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*) FILTER (pickup_late_min IS NOT NULL),2) pct_late15,
      round(100.0*avg(no_show),3) no_show_pct
    FROM emp WHERE shift_hour IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

    show("6.4 escort coverage on night trips by gender (join trips)", """
    SELECT coalesce(e.gender,'<NULL>') g,
      CASE WHEN e.shift_hour>=21 OR e.shift_hour<6 THEN 'night' ELSE 'day' END band,
      count(*) legs,
      count(*) FILTER (t.actual_escort) escorted,
      round(100.0*count(*) FILTER (t.actual_escort)/count(t.actual_escort),2) escort_pct,
      count(*)-count(t.actual_escort) escort_null
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.shift_hour IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

    show("6.5 ARTIFACT CHECK: is escort a per-trip attribute? mixed-gender trips", """
    WITH g AS (SELECT trip_id, count(DISTINCT gender) ng, count(*) legs
               FROM emp WHERE trip_id IS NOT NULL AND gender IS NOT NULL GROUP BY 1)
    SELECT ng, count(*) trips, sum(legs) legs FROM g GROUP BY 1 ORDER BY 1""")

    show("6.6 escort on FEMALE-ONLY vs MALE-ONLY night trips (trip grain)", """
    WITH tg AS (
      SELECT e.trip_id,
             max(CASE WHEN e.shift_hour>=21 OR e.shift_hour<6 THEN 1 ELSE 0 END) is_night,
             count(*) FILTER (e.gender='FEMALE') f,
             count(*) FILTER (e.gender='MALE') m
      FROM emp e WHERE e.trip_id IS NOT NULL GROUP BY 1)
    SELECT CASE WHEN f>0 AND m=0 THEN 'female-only'
                WHEN m>0 AND f=0 THEN 'male-only'
                WHEN f>0 AND m>0 THEN 'mixed' ELSE 'other' END comp,
           is_night, count(*) trips,
           round(100.0*count(*) FILTER (t.actual_escort)/count(t.actual_escort),2) escort_pct,
           count(t.actual_escort) n_escort_known
    FROM tg JOIN trips t USING (trip_id) GROUP BY 1,2 ORDER BY 1,2""")

    show("6.7 gender x nbr", """
    SELECT coalesce(gender,'<NULL>') g, nbr, count(*) n,
      round(100.0*count(*)/sum(count(*)) OVER (PARTITION BY coalesce(gender,'<NULL>')),3) pct
    FROM emp GROUP BY 1,2 ORDER BY 1, n DESC""")

# ======================================================= 6b. GENDER, CLEANED
if want("6b"):
    show("6b.1 ARTIFACT: who are the emp_role='escort' legs?", """
    SELECT emp_role, coalesce(gender,'<NULL>') g, count(*) n,
           count(DISTINCT stwid) riders,
           round(100.0*count(*) FILTER (shift_hour>=21 OR shift_hour<6)/count(*),2) pct_night
    FROM emp WHERE emp_role IN ('escort','employee','projectmgr')
    GROUP BY 1,2 ORDER BY 1,n DESC""")

    show("6b.2 escort legs vs trips.actual_escort agreement", """
    WITH t AS (SELECT trip_id, count(*) FILTER (emp_role='escort') esc_legs
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT tr.actual_escort, t.esc_legs>0 AS has_escort_leg, count(*) trips
    FROM t JOIN trips tr USING (trip_id) GROUP BY 1,2 ORDER BY trips DESC""")

    show("6b.3 gender composition EXCLUDING escort legs, night trips, escort cover", """
    WITH tg AS (
      SELECT trip_id,
             max(CASE WHEN shift_hour>=21 OR shift_hour<6 THEN 1 ELSE 0 END) is_night,
             count(*) FILTER (gender='FEMALE' AND emp_role<>'escort') f,
             count(*) FILTER (gender='MALE'   AND emp_role<>'escort') m
      FROM emp WHERE trip_id IS NOT NULL AND emp_role IS NOT NULL GROUP BY 1)
    SELECT CASE WHEN f>0 AND m=0 THEN 'female-only riders'
                WHEN m>0 AND f=0 THEN 'male-only riders'
                WHEN f>0 AND m>0 THEN 'mixed riders' ELSE 'no gendered rider' END comp,
           is_night, count(*) trips,
           count(*) FILTER (tr.actual_escort) escorted,
           round(100.0*count(*) FILTER (tr.actual_escort)/count(*),2) escort_pct
    FROM tg JOIN trips tr USING (trip_id) GROUP BY 1,2 ORDER BY 1,2""")

    show("6b.4 THE GAP: night trips carrying >=1 female employee WITHOUT escort", """
    WITH tg AS (
      SELECT trip_id,
             max(CASE WHEN shift_hour>=21 OR shift_hour<6 THEN 1 ELSE 0 END) is_night,
             count(*) FILTER (gender='FEMALE' AND emp_role<>'escort') f
      FROM emp WHERE trip_id IS NOT NULL AND emp_role IS NOT NULL GROUP BY 1)
    SELECT tr.month, count(*) night_trips_with_female,
      count(*) FILTER (NOT tr.actual_escort) unescorted,
      round(100.0*count(*) FILTER (NOT tr.actual_escort)/count(*),2) unescorted_pct
    FROM tg JOIN trips tr USING (trip_id)
    WHERE tg.is_night=1 AND tg.f>0 GROUP BY 1 ORDER BY 1""")

    show("6b.5 unescorted-night-female by BU / office (n>=500)", """
    WITH tg AS (
      SELECT trip_id,
             max(CASE WHEN shift_hour>=21 OR shift_hour<6 THEN 1 ELSE 0 END) is_night,
             count(*) FILTER (gender='FEMALE' AND emp_role<>'escort') f
      FROM emp WHERE trip_id IS NOT NULL AND emp_role IS NOT NULL GROUP BY 1)
    SELECT tr.business_unit, tr.office, tr.trip_direction, count(*) night_trips_with_female,
      count(*) FILTER (NOT tr.actual_escort) unescorted,
      round(100.0*count(*) FILTER (NOT tr.actual_escort)/count(*),2) unescorted_pct
    FROM tg JOIN trips tr USING (trip_id)
    WHERE tg.is_night=1 AND tg.f>0 GROUP BY 1,2,3
    HAVING count(*)>=500 ORDER BY unescorted_pct DESC""")

    show("6b.6 female no-show gap: is it BU composition? within-BU test", """
    SELECT business_unit,
      count(*) FILTER (gender='FEMALE') n_f,
      round(100.0*avg(no_show) FILTER (gender='FEMALE'),2) f_noshow,
      count(*) FILTER (gender='MALE') n_m,
      round(100.0*avg(no_show) FILTER (gender='MALE'),2) m_noshow,
      round(100.0*avg(no_show) FILTER (gender='FEMALE')
            - 100.0*avg(no_show) FILTER (gender='MALE'),2) gap_pt
    FROM emp GROUP BY 1 ORDER BY n_f DESC""")

    show("6b.7 female late>15 gap within BU", """
    SELECT business_unit,
      count(*) FILTER (gender='FEMALE' AND pickup_late_min IS NOT NULL) n_f,
      round(100.0*count(*) FILTER (gender='FEMALE' AND pickup_late_min>15)
            /nullif(count(*) FILTER (gender='FEMALE' AND pickup_late_min IS NOT NULL),0),2) f_late15,
      count(*) FILTER (gender='MALE' AND pickup_late_min IS NOT NULL) n_m,
      round(100.0*count(*) FILTER (gender='MALE' AND pickup_late_min>15)
            /nullif(count(*) FILTER (gender='MALE' AND pickup_late_min IS NOT NULL),0),2) m_late15
    FROM emp GROUP BY 1 ORDER BY n_f DESC""")

# ================================================ 2b. TAXONOMY / COMBINED
if want("2b"):
    show("2b.1 COMBINED not-boarded rate by BU x month (taxonomy-neutral)", """
    SELECT business_unit,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (month='2026-05-01'),2) may_nb,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (month='2026-06-01'),2) jun_nb,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (month='2026-07-01'),2) jul_nb,
      round(100.0*avg(no_show),2) noshow_label_pct,
      round(100.0*avg(CASE WHEN nbr='TRIP_CANCELLED_FROM_DASHBOARD' THEN 1.0 ELSE 0 END),2) cancel_label_pct,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END),2) combined_pct,
      count(*) n
    FROM emp GROUP BY 1 ORDER BY combined_pct DESC""")

    show("2b.2 taxonomy exclusivity: share of not-boarded labelled NO_SHOW, per BU", """
    SELECT business_unit, count(*) not_boarded,
      round(100.0*count(*) FILTER (nbr='NO_SHOW')/count(*),2) pct_noshow_label,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD')/count(*),2) pct_cancel_label
    FROM emp WHERE boarding_status='Not Boarded' GROUP BY 1 ORDER BY not_boarded DESC""")

    show("2b.3 do 'cancelled' riders ride another trip same day? (vs no-show riders)", """
    WITH nb AS (
      SELECT stwid, trip_date, nbr FROM emp
      WHERE boarding_status='Not Boarded' AND stwid NOT IN ('0','0.0') AND stwid IS NOT NULL),
    b AS (SELECT DISTINCT stwid, trip_date FROM emp
          WHERE boarding_status='Boarded' AND stwid NOT IN ('0','0.0') AND stwid IS NOT NULL)
    SELECT nb.nbr, count(*) n,
      count(*) FILTER (b.stwid IS NOT NULL) also_rode_same_day,
      round(100.0*count(*) FILTER (b.stwid IS NOT NULL)/count(*),2) pct
    FROM nb LEFT JOIN b ON nb.stwid=b.stwid AND nb.trip_date=b.trip_date
    GROUP BY 1 ORDER BY n DESC""")

    show("2b.4 pinnacle cancel: does the trip still run with other riders?", """
    WITH t AS (SELECT trip_id,
                 count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD') c,
                 count(*) FILTER (boarding_status='Boarded') b, count(*) legs
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT c>0 AS has_cancel, count(*) trips,
      round(avg(legs),2) avg_legs, round(avg(b),2) avg_boarded,
      count(*) FILTER (b=0) trips_zero_boarded
    FROM t GROUP BY 1 ORDER BY 1""")

    show("2b.5 zero-boarded trips (fully wasted cabs) by BU x month", """
    WITH t AS (SELECT trip_id, any_value(business_unit) AS bu, any_value(month) m,
                      count(*) legs, count(*) FILTER (boarding_status='Boarded') b
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT bu, count(*) trips, count(*) FILTER (b=0) zero_boarded,
      round(100.0*count(*) FILTER (b=0)/count(*),3) pct,
      round(100.0*count(*) FILTER (b=0 AND m='2026-05-01')/nullif(count(*) FILTER (m='2026-05-01'),0),3) may,
      round(100.0*count(*) FILTER (b=0 AND m='2026-06-01')/nullif(count(*) FILTER (m='2026-06-01'),0),3) jun,
      round(100.0*count(*) FILTER (b=0 AND m='2026-07-01')/nullif(count(*) FILTER (m='2026-07-01'),0),3) jul
    FROM t GROUP BY 1 ORDER BY zero_boarded DESC""")

# ================================================ 3b. RIDER OTA DEEP
if want("3b"):
    show("3b.1 rider OTA vs trip OTA by direction", """
    SELECT t.trip_direction, e.month, count(*) legs,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END),2) rider_ota,
      round(100.0*avg(CASE WHEN t.delay_minutes<=5 THEN 1.0 ELSE 0 END),2) trip_ota,
      round(100.0*avg(CASE WHEN t.delay_minutes<=5 THEN 1.0 ELSE 0 END)
            - 100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END),2) gap_pt
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pickup_late_min IS NOT NULL AND t.delay_minutes IS NOT NULL
    GROUP BY 1,2 ORDER BY 1,2""")

    show("3b.2 ARTIFACT: does trips.delay_minutes measure the FIRST leg only?", """
    WITH o AS (
      SELECT trip_id, pickup_late_min,
             row_number() OVER (PARTITION BY trip_id ORDER BY pp) seq
      FROM emp WHERE trip_id IS NOT NULL AND pp IS NOT NULL AND pickup_late_min IS NOT NULL)
    SELECT count(*) trips,
      round(corr(o.pickup_late_min, t.delay_minutes),4) corr_first_leg_vs_tripdelay,
      round(avg(abs(o.pickup_late_min - t.delay_minutes)),2) mean_abs_diff
    FROM o JOIN trips t USING (trip_id) WHERE o.seq=1 AND t.delay_minutes IS NOT NULL""")

    show("3b.3 what IS trips.delay_minutes vs rider drop lateness?", """
    SELECT count(*) legs,
      round(corr(e.drop_late_min, t.delay_minutes),4) corr_drop_vs_delay,
      round(corr(e.pickup_late_min, t.delay_minutes),4) corr_pickup_vs_delay
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.delay_minutes IS NOT NULL""")

    show("3b.4 rider-level LOGIN reach-office lateness (drop_late) by month", """
    SELECT t.trip_direction, e.month, count(*) legs,
      round(avg(e.drop_late_min),2) avg_drop_late,
      round(100.0*count(*) FILTER (e.drop_late_min>5)/count(*),2) pct_drop_late5,
      round(100.0*count(*) FILTER (e.drop_late_min>15)/count(*),2) pct_drop_late15
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.drop_late_min IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

    show("3b.5 rider-minutes of delay burned per month (the money line)", """
    SELECT month, count(*) legs,
      round(sum(greatest(pickup_late_min,0))) total_late_min,
      round(sum(greatest(pickup_late_min,0))/60.0) total_late_hours,
      round(sum(greatest(-pickup_late_min,0))) total_early_wait_min
    FROM emp WHERE pickup_late_min IS NOT NULL GROUP BY 1 ORDER BY 1""")

# ============================================================ 7. RIDER CONCENTRATION
if want("7"):
    show("7.1 stwid quality: placeholder 0 and nulls", """
    SELECT count(*) AS n_rows,
      count(*) FILTER (stwid IS NULL) stwid_null,
      count(*) FILTER (stwid IN ('0','0.0')) stwid_zero,
      count(DISTINCT stwid) distinct_all,
      count(DISTINCT stwid) FILTER (stwid NOT IN ('0','0.0')) distinct_real
    FROM emp""")

    show("7.2 who are the stwid=0 rows?", """
    SELECT emp_role, signintype, gender, boarding_status, count(*) n
    FROM emp WHERE stwid IN ('0','0.0') GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 15""")

    show("7.3 legs per rider distribution (real riders)", """
    WITH r AS (SELECT stwid, count(*) legs FROM emp
               WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0') GROUP BY 1)
    SELECT count(*) riders, round(avg(legs),1) avg_legs,
           quantile_cont(legs,0.5) p50, quantile_cont(legs,0.9) p90,
           quantile_cont(legs,0.99) p99, max(legs) mx
    FROM r""")

    show("7.4 CONCENTRATION: top decile of riders by count of late>15 pickups", """
    WITH r AS (
      SELECT stwid, count(*) legs,
             count(*) FILTER (pickup_late_min>15) late15,
             sum(greatest(pickup_late_min,0)) FILTER (pickup_late_min>0) delay_min
      FROM emp WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0')
        AND pickup_late_min IS NOT NULL
      GROUP BY 1),
    d AS (SELECT *, ntile(10) OVER (ORDER BY late15 DESC) AS decile FROM r)
    SELECT decile, count(*) riders, sum(legs) legs, sum(late15) late15_events,
      round(100.0*sum(late15)/sum(sum(late15)) OVER (),2) pct_of_all_late15,
      round(sum(delay_min)) total_delay_min,
      round(100.0*sum(delay_min)/sum(sum(delay_min)) OVER (),2) pct_of_all_delay_min
    FROM d GROUP BY 1 ORDER BY 1""")

    show("7.5 how much of the pain is just 'they ride more'? rate-normalised", """
    WITH r AS (
      SELECT stwid, count(*) legs, count(*) FILTER (pickup_late_min>15) late15
      FROM emp WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0')
        AND pickup_late_min IS NOT NULL GROUP BY 1 HAVING count(*)>=20),
    d AS (SELECT *, 1.0*late15/legs rate, ntile(10) OVER (ORDER BY 1.0*late15/legs DESC) AS decile FROM r)
    SELECT decile, count(*) riders, sum(legs) legs, sum(late15) late15,
           round(100.0*sum(late15)/sum(legs),2) late15_rate,
           round(100.0*sum(late15)/sum(sum(late15)) OVER (),2) pct_of_all_late15
    FROM d GROUP BY 1 ORDER BY 1""")

    show("7.6 worst-served riders (>=20 legs) - top 15", """
    WITH r AS (
      SELECT stwid, any_value(business_unit) AS bu, any_value(office) AS off_name,
             count(*) legs, count(*) FILTER (pickup_late_min>15) late15,
             round(avg(pickup_late_min),1) avg_late
      FROM emp WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0')
        AND pickup_late_min IS NOT NULL GROUP BY 1 HAVING count(*)>=20)
    SELECT * , round(100.0*late15/legs,1) rate FROM r ORDER BY rate DESC, legs DESC LIMIT 15""")

    show("7.7 riders who NEVER had a late>15 pickup (>=20 legs)", """
    WITH r AS (
      SELECT stwid, count(*) legs, count(*) FILTER (pickup_late_min>15) late15
      FROM emp WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0')
        AND pickup_late_min IS NOT NULL GROUP BY 1 HAVING count(*)>=20)
    SELECT count(*) riders_20plus,
      count(*) FILTER (late15=0) never_late,
      round(100.0*count(*) FILTER (late15=0)/count(*),2) pct
    FROM r""")

    show("7.8 repeat no-show riders concentration", """
    WITH r AS (
      SELECT stwid, count(*) legs, sum(no_show) ns
      FROM emp WHERE stwid IS NOT NULL AND stwid NOT IN ('0','0.0') GROUP BY 1)
    SELECT count(*) FILTER (ns>0) riders_with_any_noshow,
      count(*) riders,
      sum(ns) total_noshows,
      round(100.0*sum(ns) FILTER (ns>=5)/sum(ns),2) pct_noshows_from_riders_with_5plus,
      count(*) FILTER (ns>=5) riders_5plus
    FROM r""")

# ============================================================ 8. ROLE / SIGNIN
if want("8"):
    show("8.1 emp_role x signintype x month", """
    SELECT emp_role, signintype,
      count(*) FILTER (month='2026-05-01') may,
      count(*) FILTER (month='2026-06-01') jun,
      count(*) FILTER (month='2026-07-01') jul,
      count(*) total, round(100.0*count(*)/sum(count(*)) OVER (),3) pct
    FROM emp GROUP BY 1,2 ORDER BY total DESC""")

    show("8.2 guest/adhoc experience vs planned", """
    SELECT signintype, count(*) n,
      round(avg(pickup_late_min),2) avg_late,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*) FILTER (pickup_late_min IS NOT NULL),2) pct_late15,
      round(100.0*avg(no_show),3) no_show_pct,
      round(100.0*count(*) FILTER (ap IS NULL AND ad IS NULL)/count(*),2) null_actual_pct
    FROM emp GROUP BY 1 ORDER BY n DESC""")

    show("8.3 adhoc/guest share by BU (n>=500)", """
    SELECT business_unit, count(*) n,
      round(100.0*count(*) FILTER (signintype<>'Planned')/count(*),3) nonplanned_pct
    FROM emp GROUP BY 1 HAVING count(*)>=500 ORDER BY nonplanned_pct DESC""")

# ============================================================ 9. OCCUPANCY / LEGS PER TRIP
if want("9"):
    show("9.1 legs per trip distribution by month", """
    WITH t AS (SELECT trip_id, any_value(month) m, count(*) legs
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT m, count(*) trips, sum(legs) legs, round(avg(legs),3) avg_legs,
      quantile_cont(legs,0.5) p50, max(legs) mx
    FROM t GROUP BY 1 ORDER BY 1""")

    show("9.2 legs-per-trip histogram", """
    WITH t AS (SELECT trip_id, count(*) legs FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT legs, count(*) trips, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
    FROM t GROUP BY 1 ORDER BY 1 LIMIT 25""")

    show("9.3 single-rider cabs by month (a cost signal)", """
    WITH t AS (SELECT trip_id, any_value(month) m, count(*) legs,
                      count(*) FILTER (no_show=0) boarded
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT m, count(*) trips,
      round(100.0*count(*) FILTER (legs=1)/count(*),2) pct_1leg,
      round(100.0*count(*) FILTER (boarded<=1)/count(*),2) pct_le1_boarded,
      round(100.0*count(*) FILTER (boarded=0)/count(*),3) pct_zero_boarded
    FROM t GROUP BY 1 ORDER BY 1""")

    show("9.4 occupancy vs cab capacity (join trips)", """
    WITH t AS (SELECT trip_id, count(*) FILTER (no_show=0) boarded, count(*) legs
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT tr.month, tr.cab_capacity, count(*) trips,
      round(avg(t.boarded),2) avg_boarded,
      round(100.0*avg(t.boarded)/nullif(tr.cab_capacity,0),1) util_pct
    FROM t JOIN trips tr USING (trip_id)
    WHERE tr.cab_capacity IS NOT NULL
    GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 2,1""")

    show("9.5 does emp_data leg count match ride_data actualemployee_cnt?", """
    WITH t AS (SELECT trip_id, count(*) legs, count(*) FILTER (no_show=0) boarded
               FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT count(*) trips,
      count(*) FILTER (t.legs=tr.emp_planned) legs_eq_planned,
      count(*) FILTER (t.boarded=tr.emp_actual) boarded_eq_actual,
      round(100.0*count(*) FILTER (t.boarded=tr.emp_actual)/count(*),2) pct_match
    FROM t JOIN trips tr USING (trip_id)""")

# ============================================================ 10. JUNE DEEP DIVE
if want("10"):
    show("10.1 rider-level late>15 by month x product_type", """
    SELECT product_type, month, count(*) n,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*),2) pct_late15,
      round(avg(pickup_late_min),2) avg_late
    FROM emp WHERE pickup_late_min IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

    show("10.2 daily rider-late>15 rate (find the exact days)", """
    SELECT trip_date, count(*) n,
      round(100.0*count(*) FILTER (pickup_late_min>15)/count(*),2) pct_late15
    FROM emp WHERE pickup_late_min IS NOT NULL AND trip_date IS NOT NULL
    GROUP BY 1 ORDER BY pct_late15 DESC LIMIT 20""")

    show("10.3 monthly daily avg for context", """
    SELECT month, round(avg(pct),2) avg_daily_pct, round(min(pct),2) mn, round(max(pct),2) mx
    FROM (SELECT month, trip_date, 100.0*count(*) FILTER (pickup_late_min>15)/count(*) pct
          FROM emp WHERE pickup_late_min IS NOT NULL AND trip_date IS NOT NULL
          GROUP BY 1,2) GROUP BY 1 ORDER BY 1""")

    show("10.4 no-show / cancel weekday effect", """
    SELECT dayname(trip_date) dow, count(*) n,
      round(100.0*avg(no_show),3) no_show_pct,
      round(100.0*count(*) FILTER (nbr='TRIP_CANCELLED_FROM_DASHBOARD')/count(*),3) cancel_pct
    FROM emp WHERE trip_date IS NOT NULL GROUP BY 1
    ORDER BY min(dayofweek(trip_date))""")

print("\nDONE section=", SEC)

# ================================================ 11. VERIFICATION / ARTIFACT CHECKS
if want("11"):
    show("11.1 ARTIFACT: is the midday no-show peak just vanta-Sea? within-BU shift curve", """
    SELECT shift_hour,
      round(100.0*avg(no_show) FILTER (business_unit='vanta-Sea'),2) vanta_sea,
      count(*) FILTER (business_unit='vanta-Sea') n_vs,
      round(100.0*avg(no_show) FILTER (business_unit='orbit-Slc'),2) orbit,
      count(*) FILTER (business_unit='orbit-Slc') n_or,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (business_unit='pinnacle-Slc'),2) pinnacle_notboarded,
      count(*) FILTER (business_unit='pinnacle-Slc') n_pin
    FROM emp WHERE shift_hour IS NOT NULL GROUP BY 1
    HAVING count(*) FILTER (business_unit='vanta-Sea')>=500
       AND count(*) FILTER (business_unit='orbit-Slc')>=500 ORDER BY 1""")

    show("11.2 THE LONE-FEMALE-LAST-DROP TEST (night LOGOUT, unescorted)", """
    WITH lastleg AS (
      SELECT trip_id, gender, emp_role, shift_hour,
             row_number() OVER (PARTITION BY trip_id ORDER BY ad DESC) AS r,
             count(*) OVER (PARTITION BY trip_id) AS legs
      FROM emp WHERE trip_id IS NOT NULL AND ad IS NOT NULL AND emp_role<>'escort')
    SELECT t.month, count(*) AS night_logout_unescorted_trips,
      count(*) FILTER (l.gender='FEMALE') AS last_drop_female,
      round(100.0*count(*) FILTER (l.gender='FEMALE')/count(*),2) AS pct
    FROM lastleg l JOIN trips t USING (trip_id)
    WHERE l.r=1 AND t.trip_direction='LOGOUT' AND NOT t.actual_escort
      AND (l.shift_hour>=21 OR l.shift_hour<6)
    GROUP BY 1 ORDER BY 1""")

    show("11.3 same, but compare to escorted night LOGOUT (control)", """
    WITH lastleg AS (
      SELECT trip_id, gender, shift_hour,
             row_number() OVER (PARTITION BY trip_id ORDER BY ad DESC) AS r
      FROM emp WHERE trip_id IS NOT NULL AND ad IS NOT NULL AND emp_role<>'escort')
    SELECT t.actual_escort, count(*) AS trips,
      count(*) FILTER (l.gender='FEMALE') AS last_drop_female,
      round(100.0*count(*) FILTER (l.gender='FEMALE')/count(*),2) AS pct
    FROM lastleg l JOIN trips t USING (trip_id)
    WHERE l.r=1 AND t.trip_direction='LOGOUT' AND (l.shift_hour>=21 OR l.shift_hour<6)
    GROUP BY 1 ORDER BY 1""")

    show("11.4 lone-female-last-drop by BU/office (unescorted night LOGOUT)", """
    WITH lastleg AS (
      SELECT trip_id, gender, shift_hour,
             row_number() OVER (PARTITION BY trip_id ORDER BY ad DESC) AS r
      FROM emp WHERE trip_id IS NOT NULL AND ad IS NOT NULL AND emp_role<>'escort')
    SELECT t.business_unit, t.office, count(*) AS trips,
      count(*) FILTER (l.gender='FEMALE') AS last_drop_female,
      round(100.0*count(*) FILTER (l.gender='FEMALE')/count(*),2) AS pct
    FROM lastleg l JOIN trips t USING (trip_id)
    WHERE l.r=1 AND t.trip_direction='LOGOUT' AND NOT t.actual_escort
      AND (l.shift_hour>=21 OR l.shift_hour<6)
    GROUP BY 1,2 HAVING count(*)>=500 ORDER BY last_drop_female DESC""")

    show("11.5 ride_data duplicate trip rows", """
    SELECT count(*) AS ride_rows, count(DISTINCT trip_id) AS distinct_trips,
           count(*)-count(DISTINCT trip_id) AS dup_rows FROM trips""")

    show("11.6 Friday effect WITHIN BU (n>=500 per cell)", """
    SELECT business_unit,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (dayname(trip_date)='Friday'),2) fri_nb,
      count(*) FILTER (dayname(trip_date)='Friday') n_fri,
      round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1.0 ELSE 0 END)
            FILTER (dayname(trip_date) IN ('Tuesday','Wednesday')),2) tuewed_nb,
      count(*) FILTER (dayname(trip_date) IN ('Tuesday','Wednesday')) n_tw
    FROM emp WHERE trip_date IS NOT NULL GROUP BY 1 ORDER BY n_fri DESC""")

    show("11.7 Adhoc is mostly ESCORTS not ad-hoc employees", """
    SELECT signintype, count(*) AS n,
      count(*) FILTER (emp_role='escort') AS escort_legs,
      round(100.0*count(*) FILTER (emp_role='escort')/count(*),2) AS pct_escort
    FROM emp GROUP BY 1 ORDER BY n DESC""")

    show("11.8 catalyst-Sac high 'non-planned' share explained?", """
    SELECT business_unit, count(*) AS n,
      round(100.0*count(*) FILTER (signintype IN ('Adhoc','Guest'))/count(*),2) AS nonplanned_pct,
      round(100.0*count(*) FILTER (signintype IN ('Adhoc','Guest') AND emp_role='escort')/count(*),2) AS escort_pct,
      round(100.0*count(*) FILTER (signintype IN ('Adhoc','Guest') AND emp_role<>'escort')/count(*),2) AS true_adhoc_pct
    FROM emp GROUP BY 1 ORDER BY nonplanned_pct DESC""")

    show("11.9 rider-OTA June dip: is it concentrated like trip-OTA was? BU x direction", """
    SELECT e.business_unit, t.trip_direction,
      count(*) AS n,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END) FILTER (e.month='2026-05-01'),2) may,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END) FILTER (e.month='2026-06-01'),2) jun,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END) FILTER (e.month='2026-07-01'),2) jul,
      round(100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END) FILTER (e.month='2026-06-01')
          - 100.0*avg(CASE WHEN e.pickup_late_min<=5 THEN 1.0 ELSE 0 END) FILTER (e.month='2026-05-01'),2) jun_swing
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pickup_late_min IS NOT NULL GROUP BY 1,2 HAVING count(*)>=5000 ORDER BY jun_swing""")

    show("11.10 SPOT_2.0 sample size guard", """
    SELECT product_type, count(*) AS n, count(DISTINCT trip_id) AS trips,
           count(DISTINCT stwid) AS riders FROM emp GROUP BY 1 ORDER BY n DESC""")

# ================================================ 12. LOGOUT PICKUP ARTIFACT
if want("12"):
    show("12.1 pickup_late_min distribution by direction (is LOGOUT synthetic?)", """
    SELECT t.trip_direction, count(*) AS n,
      count(*) FILTER (e.pickup_late_min=0) AS exactly_zero,
      round(100.0*count(*) FILTER (e.pickup_late_min=0)/count(*),2) AS pct_zero,
      round(quantile_cont(e.pickup_late_min,0.10),2) AS p10,
      round(quantile_cont(e.pickup_late_min,0.50),2) AS p50,
      round(quantile_cont(e.pickup_late_min,0.90),2) AS p90,
      round(stddev(e.pickup_late_min),2) AS sd
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pickup_late_min IS NOT NULL GROUP BY 1""")

    show("12.2 LOGOUT: do all legs share the same actual_pickup (office boarding)?", """
    WITH t AS (SELECT trip_id, count(DISTINCT ap) AS dap, count(DISTINCT pp) AS dpp, count(*) AS legs
               FROM emp WHERE trip_id IS NOT NULL AND ap IS NOT NULL GROUP BY 1)
    SELECT tr.trip_direction, count(*) AS trips,
      round(100.0*count(*) FILTER (dap=1)/count(*),2) AS pct_same_actual_pickup,
      round(100.0*count(*) FILTER (dpp=1)/count(*),2) AS pct_same_planned_pickup
    FROM t JOIN trips tr USING (trip_id) WHERE legs>=2 GROUP BY 1""")

    show("12.3 LOGOUT rider pain is at the DROP end - band table", """
    SELECT t.trip_direction, e.month, count(*) AS n,
      round(100.0*count(*) FILTER (e.drop_late_min<=5)/count(*),2) AS drop_ota5,
      round(100.0*count(*) FILTER (e.drop_late_min>15)/count(*),2) AS drop_late15,
      round(100.0*count(*) FILTER (e.drop_late_min>30)/count(*),2) AS drop_late30,
      round(quantile_cont(e.drop_late_min,0.9),1) AS p90_drop_late
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.drop_late_min IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

    show("12.4 UNIFIED rider SLA: LOGIN=pickup punctuality, LOGOUT=drop punctuality", """
    SELECT e.month, count(*) AS legs,
      round(100.0*avg(CASE WHEN (t.trip_direction='LOGIN'  AND e.pickup_late_min<=5)
                             OR (t.trip_direction='LOGOUT' AND e.drop_late_min<=15)
                        THEN 1.0 ELSE 0 END),2) AS rider_sla_pct
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pickup_late_min IS NOT NULL AND e.drop_late_min IS NOT NULL
    GROUP BY 1 ORDER BY 1""")

    show("12.5 LOGOUT drop_late by BU x month (n>=5000)", """
    SELECT e.business_unit, count(*) AS n,
      round(100.0*count(*) FILTER (e.drop_late_min>15 AND e.month='2026-05-01')
            /nullif(count(*) FILTER (e.month='2026-05-01'),0),2) AS may,
      round(100.0*count(*) FILTER (e.drop_late_min>15 AND e.month='2026-06-01')
            /nullif(count(*) FILTER (e.month='2026-06-01'),0),2) AS jun,
      round(100.0*count(*) FILTER (e.drop_late_min>15 AND e.month='2026-07-01')
            /nullif(count(*) FILTER (e.month='2026-07-01'),0),2) AS jul
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGOUT' AND e.drop_late_min IS NOT NULL
    GROUP BY 1 HAVING count(*)>=5000 ORDER BY jun DESC""")

    show("12.6 how long does the LAST rider sit in the cab past plan? (LOGOUT)", """
    WITH o AS (SELECT trip_id, drop_late_min, gender,
                 row_number() OVER (PARTITION BY trip_id ORDER BY ad DESC) AS r
               FROM emp WHERE trip_id IS NOT NULL AND ad IS NOT NULL AND pd IS NOT NULL)
    SELECT t.month, count(*) AS trips,
      round(avg(o.drop_late_min),2) AS avg_last_drop_late,
      round(quantile_cont(o.drop_late_min,0.9),1) AS p90,
      round(100.0*count(*) FILTER (o.drop_late_min>30)/count(*),2) AS pct_over30
    FROM o JOIN trips t USING (trip_id)
    WHERE o.r=1 AND t.trip_direction='LOGOUT' GROUP BY 1 ORDER BY 1""")

# ================================================ 13. IS DROP-LATE A PLANNING ARTIFACT?
if want("13"):
    show("13.1 planned vs actual in-cab duration per rider", """
    SELECT t.trip_direction, e.month, count(*) AS n,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg((e.ad-e.ap)/60.0),2) AS actual_min,
      round(avg((e.ad-e.ap)/60.0) - avg((e.pd-e.pp)/60.0),2) AS overrun_min,
      round(quantile_cont((e.ad-e.ap)/60.0 - (e.pd-e.pp)/60.0,0.5),2) AS med_overrun
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pp IS NOT NULL AND e.pd IS NOT NULL AND e.ap IS NOT NULL AND e.ad IS NOT NULL
    GROUP BY 1,2 ORDER BY 1,2""")

    show("13.2 decompose LOGOUT drop lateness: late start vs slow ride", """
    SELECT e.month, count(*) AS n,
      round(avg(e.drop_late_min),2) AS drop_late,
      round(avg(e.pickup_late_min),2) AS pickup_late,
      round(avg(e.drop_late_min - e.pickup_late_min),2) AS in_cab_overrun,
      round(100.0*count(*) FILTER (e.drop_late_min>15 AND e.pickup_late_min<=5)/count(*),2) AS pct_late_despite_ontime_pickup
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGOUT' AND e.drop_late_min IS NOT NULL AND e.pickup_late_min IS NOT NULL
    GROUP BY 1 ORDER BY 1""")

    show("13.3 same for LOGIN", """
    SELECT e.month, count(*) AS n,
      round(avg(e.drop_late_min),2) AS drop_late,
      round(avg(e.pickup_late_min),2) AS pickup_late,
      round(avg(e.drop_late_min - e.pickup_late_min),2) AS in_cab_overrun,
      round(100.0*count(*) FILTER (e.drop_late_min>15 AND e.pickup_late_min<=5)/count(*),2) AS pct_late_despite_ontime_pickup
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGIN' AND e.drop_late_min IS NOT NULL AND e.pickup_late_min IS NOT NULL
    GROUP BY 1 ORDER BY 1""")

    show("13.4 pinnacle-Slc LOGOUT: planning gap vs execution gap", """
    SELECT e.business_unit, e.month, count(*) AS n,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg((e.ad-e.ap)/60.0),2) AS actual_min,
      round(avg(e.drop_late_min - e.pickup_late_min),2) AS in_cab_overrun,
      round(avg(e.pickup_late_min),2) AS pickup_late
    FROM emp e JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGOUT' AND e.pp IS NOT NULL AND e.ad IS NOT NULL
    GROUP BY 1,2 HAVING count(*)>=5000 ORDER BY 1,2""")

    show("13.5 planned duration vs planned_km implied speed (sanity)", """
    SELECT t.trip_direction, count(*) AS n,
      round(avg(e.planned_km),2) AS avg_planned_km,
      round(avg((e.pd-e.pp)/60.0),2) AS avg_planned_min,
      round(avg(e.planned_km)/(avg((e.pd-e.pp)/60.0)/60.0),1) AS implied_kmph_planned,
      round(avg(e.traveled_km),2) AS avg_actual_km,
      round(avg((e.ad-e.ap)/60.0),2) AS avg_actual_min,
      round(avg(e.traveled_km)/(avg((e.ad-e.ap)/60.0)/60.0),1) AS implied_kmph_actual
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pp IS NOT NULL AND e.ad IS NOT NULL AND e.planned_km>0 AND e.traveled_km>0
    GROUP BY 1""")

# ================================================ 14. LOGOUT OVERRUN: WAIT vs TRAFFIC
if want("14"):
    show("14.1 CONTROL: single-rider LOGOUT trips (no co-passenger wait possible)", """
    WITH t AS (SELECT trip_id, count(*) AS legs FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT tr.trip_direction, e.month, count(*) AS n,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg((e.ad-e.ap)/60.0),2) AS actual_min,
      round(avg((e.ad-e.ap)/60.0)-avg((e.pd-e.pp)/60.0),2) AS overrun_min,
      round(avg(e.traveled_km),2) AS km,
      round(avg(e.traveled_km)/(avg((e.ad-e.ap)/60.0)/60.0),1) AS kmph_actual,
      round(avg(e.planned_km)/(avg((e.pd-e.pp)/60.0)/60.0),1) AS kmph_planned
    FROM emp e JOIN t USING (trip_id) JOIN trips tr USING (trip_id)
    WHERE t.legs=1 AND e.pp IS NOT NULL AND e.ad IS NOT NULL
      AND e.planned_km>0 AND e.traveled_km>0
    GROUP BY 1,2 ORDER BY 1,2""")

    show("14.2 LOGOUT overrun by boarding sequence (wait effect)", """
    WITH o AS (SELECT trip_id, pp, pd, ap, ad, planned_km, traveled_km,
                 row_number() OVER (PARTITION BY trip_id ORDER BY ap) AS seq,
                 count(*) OVER (PARTITION BY trip_id) AS legs
               FROM emp WHERE trip_id IS NOT NULL AND ap IS NOT NULL AND ad IS NOT NULL
                 AND pp IS NOT NULL AND pd IS NOT NULL)
    SELECT o.seq, count(*) AS n,
      round(avg((o.pd-o.pp)/60.0),2) AS planned_min,
      round(avg((o.ad-o.ap)/60.0),2) AS actual_min,
      round(avg((o.ad-o.ap)/60.0)-avg((o.pd-o.pp)/60.0),2) AS overrun_min
    FROM o JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGOUT' AND o.legs BETWEEN 2 AND 6
    GROUP BY 1 HAVING count(*)>=2000 ORDER BY 1""")

    show("14.3 LOGIN same, for contrast", """
    WITH o AS (SELECT trip_id, pp, pd, ap, ad,
                 row_number() OVER (PARTITION BY trip_id ORDER BY ap) AS seq,
                 count(*) OVER (PARTITION BY trip_id) AS legs
               FROM emp WHERE trip_id IS NOT NULL AND ap IS NOT NULL AND ad IS NOT NULL
                 AND pp IS NOT NULL AND pd IS NOT NULL)
    SELECT o.seq, count(*) AS n,
      round(avg((o.pd-o.pp)/60.0),2) AS planned_min,
      round(avg((o.ad-o.ap)/60.0),2) AS actual_min,
      round(avg((o.ad-o.ap)/60.0)-avg((o.pd-o.pp)/60.0),2) AS overrun_min
    FROM o JOIN trips t USING (trip_id)
    WHERE t.trip_direction='LOGIN' AND o.legs BETWEEN 2 AND 6
    GROUP BY 1 HAVING count(*)>=2000 ORDER BY 1""")

    show("14.4 vanta-Sea single-rider LOGOUT (isolate the worst BU, no wait)", """
    WITH t AS (SELECT trip_id, count(*) AS legs FROM emp WHERE trip_id IS NOT NULL GROUP BY 1)
    SELECT e.business_unit, count(*) AS n,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg((e.ad-e.ap)/60.0),2) AS actual_min,
      round(avg((e.ad-e.ap)/60.0)-avg((e.pd-e.pp)/60.0),2) AS overrun_min,
      round(avg(e.planned_km)/(avg((e.pd-e.pp)/60.0)/60.0),1) AS kmph_planned,
      round(avg(e.traveled_km)/(avg((e.ad-e.ap)/60.0)/60.0),1) AS kmph_actual
    FROM emp e JOIN t USING (trip_id) JOIN trips tr USING (trip_id)
    WHERE t.legs=1 AND tr.trip_direction='LOGOUT' AND e.pp IS NOT NULL AND e.ad IS NOT NULL
      AND e.planned_km>0 AND e.traveled_km>0
    GROUP BY 1 HAVING count(*)>=2000 ORDER BY overrun_min DESC""")

    show("14.5 planned LOGOUT speed by BU (the parameter that is wrong)", """
    SELECT e.business_unit, t.trip_direction, count(*) AS n,
      round(avg(e.planned_km),2) AS planned_km,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg(e.planned_km)/(avg((e.pd-e.pp)/60.0)/60.0),1) AS kmph_planned,
      round(avg(e.traveled_km)/(avg((e.ad-e.ap)/60.0)/60.0),1) AS kmph_actual
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.pp IS NOT NULL AND e.ad IS NOT NULL AND e.planned_km>0 AND e.traveled_km>0
    GROUP BY 1,2 HAVING count(*)>=5000 ORDER BY 2,6""")

# ================================================ 15. FINAL CHECKS
if want("15"):
    show("15.1 is rider-level pain concentration a PERSON or a ROUTE/OFFICE effect?", """
    WITH r AS (
      SELECT stwid, any_value(office) AS off_name, count(*) AS legs,
             count(*) FILTER (pickup_late_min>15) AS late15
      FROM emp WHERE stwid NOT IN ('0','0.0') AND pickup_late_min IS NOT NULL
      GROUP BY 1 HAVING count(*)>=20),
    d AS (SELECT *, ntile(10) OVER (ORDER BY 1.0*late15/legs DESC) AS decile FROM r)
    SELECT off_name, count(*) AS riders_total,
      count(*) FILTER (decile=1) AS in_worst_decile,
      round(100.0*count(*) FILTER (decile=1)/count(*),1) AS pct_of_office_riders_in_worst_decile
    FROM d GROUP BY 1 HAVING count(*)>=200 ORDER BY pct_of_office_riders_in_worst_decile DESC""")

    show("15.2 within ONE office, do individual riders still differ? (Clearwater)", """
    WITH r AS (
      SELECT stwid, count(*) AS legs, count(*) FILTER (pickup_late_min>15) AS late15
      FROM emp WHERE office='Clearwater Campus' AND stwid NOT IN ('0','0.0')
        AND pickup_late_min IS NOT NULL GROUP BY 1 HAVING count(*)>=20),
    d AS (SELECT *, ntile(5) OVER (ORDER BY 1.0*late15/legs DESC) AS quintile FROM r)
    SELECT quintile, count(*) AS riders, sum(legs) AS legs, sum(late15) AS late15,
           round(100.0*sum(late15)/sum(legs),2) AS rate
    FROM d GROUP BY 1 ORDER BY 1""")

    show("15.3 headline restate: riders absorbing delay", """
    WITH r AS (
      SELECT stwid, count(*) AS legs, count(*) FILTER (pickup_late_min>15) AS late15,
             sum(greatest(pickup_late_min,0)) AS delay_min
      FROM emp WHERE stwid NOT IN ('0','0.0') AND pickup_late_min IS NOT NULL GROUP BY 1),
    d AS (SELECT *, ntile(20) OVER (ORDER BY late15 DESC) AS v FROM r)
    SELECT count(*) FILTER (v=1) AS riders_top5pct,
           (SELECT count(*) FROM r) AS riders_total,
           round(100.0*sum(late15) FILTER (v=1)/sum(late15),2) AS pct_late15_absorbed,
           round(100.0*sum(delay_min) FILTER (v=1)/sum(delay_min),2) AS pct_delaymin_absorbed,
           sum(late15) AS all_late15_events
    FROM d""")

    show("15.4 no-show improvement in absolute riders + trips affected", """
    SELECT month, count(*) AS legs,
      count(*) FILTER (boarding_status='Not Boarded') AS not_boarded,
      round(100.0*count(*) FILTER (boarding_status='Not Boarded')/count(*),2) AS nb_pct,
      count(DISTINCT trip_id) AS trips,
      count(DISTINCT trip_id) FILTER (boarding_status='Not Boarded') AS trips_with_a_noshow,
      round(100.0*count(DISTINCT trip_id) FILTER (boarding_status='Not Boarded')
            /count(DISTINCT trip_id),2) AS pct_trips_affected
    FROM emp GROUP BY 1 ORDER BY 1""")

    show("15.5 seats paid for but not used (planned legs that did not board)", """
    SELECT business_unit, month, count(*) AS planned_legs,
      count(*) FILTER (boarding_status='Not Boarded') AS wasted_seats
    FROM emp GROUP BY 1,2 ORDER BY 1,2""")

    show("15.6 shift 11:00/12:00 no-show: LOGIN or LOGOUT?", """
    SELECT e.shift_hour, t.trip_direction, count(*) AS n,
      round(100.0*avg(CASE WHEN e.boarding_status='Not Boarded' THEN 1.0 ELSE 0 END),2) AS nb_pct
    FROM emp e JOIN trips t USING (trip_id)
    WHERE e.shift_hour IN (10,11,12,13,21,22) GROUP BY 1,2 HAVING count(*)>=2000 ORDER BY 1,2""")

# ================================================ 16. JOIN HYGIENE
if want("16"):
    show("16.1 ride_data duplicate trip_id rows: exact dupes or conflicting?", """
    WITH d AS (SELECT trip_id, count(*) AS c,
                 count(DISTINCT trip_direction) AS dd,
                 count(DISTINCT delay_minutes) AS dm
               FROM trips GROUP BY 1 HAVING count(*)>1)
    SELECT count(*) AS dup_trip_ids, sum(c) AS rows_involved,
      count(*) FILTER (dd>1) AS conflicting_direction,
      count(*) FILTER (dm>1) AS conflicting_delay
    FROM d""")

    show("16.2 join fan-out impact on leg counts", """
    SELECT (SELECT count(*) FROM emp WHERE pickup_late_min IS NOT NULL) AS emp_legs_with_pickup,
           (SELECT count(*) FROM emp e JOIN trips t USING (trip_id)
            WHERE e.pickup_late_min IS NOT NULL) AS after_join""")

    show("16.3 dedup check: do headline direction numbers survive dedup?", """
    WITH tu AS (SELECT trip_id, any_value(trip_direction) AS trip_direction
                FROM trips GROUP BY 1)
    SELECT t.trip_direction, e.month, count(*) AS n,
      round(avg((e.pd-e.pp)/60.0),2) AS planned_min,
      round(avg((e.ad-e.ap)/60.0),2) AS actual_min,
      round(avg((e.ad-e.ap)/60.0)-avg((e.pd-e.pp)/60.0),2) AS overrun_min
    FROM emp e JOIN tu t USING (trip_id)
    WHERE e.pp IS NOT NULL AND e.ad IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")

# ================================================ D. delay_minutes SEMANTICS (referenced as QD*)
if want("D"):
    show("D3 last-leg drop_late vs trip delay_minutes, by direction", """
    WITH o AS (SELECT trip_id, drop_late_min,
                 row_number() OVER (PARTITION BY trip_id ORDER BY ad DESC) AS r
               FROM emp WHERE trip_id IS NOT NULL AND ad IS NOT NULL AND pd IS NOT NULL)
    SELECT t.trip_direction, count(*) AS n,
      round(avg(o.drop_late_min),2) AS avg_leg_droplate,
      round(avg(t.delay_minutes),2) AS avg_trip_delay,
      round(corr(o.drop_late_min,t.delay_minutes),4) AS c,
      round(avg(o.drop_late_min-t.delay_minutes),2) AS mean_gap
    FROM o JOIN trips t USING (trip_id)
    WHERE o.r=1 AND t.delay_minutes IS NOT NULL GROUP BY 1""")

    show("D3b corr of delay_minutes with rider drop vs rider pickup lateness", """
    SELECT count(*) AS legs,
      round(corr(e.drop_late_min, t.delay_minutes),4) AS corr_drop_vs_delay,
      round(corr(e.pickup_late_min, t.delay_minutes),4) AS corr_pickup_vs_delay
    FROM emp e JOIN trips t USING (trip_id) WHERE t.delay_minutes IS NOT NULL""")

    show("D4 delay_minutes distribution (clipped at zero?)", """
    SELECT count(*) AS n, count(*) FILTER (delay_minutes<0) AS neg,
      round(min(delay_minutes),1) AS mn, round(quantile_cont(delay_minutes,0.5),2) AS p50,
      round(quantile_cont(delay_minutes,0.9),2) AS p90, round(avg(delay_minutes),2) AS mean
    FROM trips WHERE delay_minutes IS NOT NULL""")

    show("D6 traveled_km=0 among BOARDED legs", """
    SELECT boarding_status, count(*) AS n, count(*) FILTER (traveled_km=0) AS zero_km,
      round(100.0*count(*) FILTER (traveled_km=0)/count(*),2) AS pct,
      count(*) FILTER (planned_km=0) AS zero_planned
    FROM emp GROUP BY 1""")

    show("D7 boarded + zero traveled_km legs: who?", """
    SELECT business_unit, product_type, count(*) AS n FROM emp
    WHERE boarding_status='Boarded' AND traveled_km=0 GROUP BY 1,2 ORDER BY n DESC LIMIT 12""")
