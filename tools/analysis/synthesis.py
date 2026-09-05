#!/usr/bin/env python
"""
synthesis.py — independent re-verification of the headline numbers claimed in
docs/findings/*.md before they go into docs/FINDINGS.md.

Every section re-derives a number from raw CSV. Nothing is carried over from
another agent's write-up.

Run:  .venv/bin/python tools/analysis/synthesis.py [section ...]
      sections: base ota shift spot dow ids bill fb emp alerts esc cost misc
      (default: all)
"""
import sys
import duckdb

RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw"
con = duckdb.connect()
con.sql("SET TimeZone='UTC'")


def show(title, sql):
    print(f"\n--- {title}")
    print(con.sql(sql))


def build():
    con.sql(f"""
    CREATE OR REPLACE VIEW trips AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, office, product_type, vendor_id, trip_direction,
      shift_type, coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason,
      route_source,
      strptime(trip_date,'%B %d, %Y')::DATE                           AS trip_date,
      date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE      AS month,
      TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)               AS delay_minutes,
      TRY_CAST(replace(traveled_km,',','') AS DOUBLE)                 AS traveled_km,
      TRY_CAST(replace(planned_km,',','')  AS DOUBLE)                 AS planned_km,
      TRY_CAST(actual_escort AS BOOLEAN)                              AS actual_escort,
      TRY_CAST(is_driver_nc AS BOOLEAN)                               AS is_driver_nc,
      TRY_CAST(is_cab_nc AS BOOLEAN)                                  AS is_cab_nc,
      TRY_CAST(actual_cab_capacity AS INT)                            AS cab_capacity,
      TRY_CAST(plannedemployee_cnt AS INT)                            AS emp_planned,
      TRY_CAST(actualemployee_cnt AS INT)                             AS emp_actual,
      TRY_CAST(noshow_cnt AS INT)                                     AS noshow,
      TRY_CAST(replace(planned_start_epoch,',','') AS BIGINT)         AS pse,
      TRY_CAST(replace(planned_end_epoch,',','')   AS BIGINT)         AS pee,
      TRY_CAST(replace(actual_start_epoch,',','')  AS BIGINT)         AS ase,
      TRY_CAST(replace(actual_end_epoch,',','')    AS BIGINT)         AS aee,
      CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5
           THEN 1 ELSE 0 END                                          AS on_time
    FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
      null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW bill AS SELECT
      trip_id AS trip_id_raw,
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, office, vendor, contract, slab_name,
      strptime(cycle_start,'%B %d, %Y, %I:%M %p')::DATE               AS cycle_start,
      date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE AS cycle_month,
      TRY_CAST(replace(total_trip_km,',','') AS DOUBLE)               AS km,
      TRY_CAST(replace(trip_cost,',','')     AS DOUBLE)               AS cost
    FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW emp AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, office, product_type, shift_type,
      strptime(trip_date,'%Y-%m-%d')::DATE                            AS trip_date,
      date_trunc('month', strptime(trip_date,'%Y-%m-%d'))::DATE       AS month,
      TRY_CAST(replace(planned_pickup_epoch,',','') AS BIGINT)        AS ppe,
      TRY_CAST(replace(planned_drop_epoch,',','')   AS BIGINT)        AS pde,
      TRY_CAST(replace(actual_pickup_epoch,',','')  AS BIGINT)        AS ape,
      TRY_CAST(replace(actual_drop_epoch,',','')    AS BIGINT)        AS ade,
      TRY_CAST(replace(planned_km,',','')  AS DOUBLE)                 AS planned_km,
      TRY_CAST(replace(traveled_km,',','') AS DOUBLE)                 AS traveled_km,
      stwid, signintype, gender, emp_role, boarding_status,
      not_boarding_reason, is_no_show
    FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW fb AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, trip_type, stwid,
      TRY_CAST(route_rating AS INT)   AS route_rating,
      TRY_CAST(driver_rating AS INT)  AS driver_rating,
      TRY_CAST(cab_rating AS INT)     AS cab_rating,
      TRY_CAST(safety_rating AS INT)  AS safety_rating,
      TRY_CAST(marshal_rating AS INT) AS marshal_rating,
      strptime(creation_time,'%B %d, %Y, %I:%M %p')                   AS created
    FROM read_csv('{RAW}/trip_feedback.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW alerts AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, stwid, event_id, event_type, state_text, severity, source,
      strptime(start_time,'%B %d, %Y, %I:%M %p')                      AS start_ts,
      strptime(acknowledge_time,'%B %d, %Y, %I:%M %p')                AS ack_ts,
      strptime(start_time,'%B %d, %Y, %I:%M %p')::DATE                AS start_date
    FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)
    """)


# ---------------------------------------------------------------- sections
def s_base():
    show("V0 row counts (claimed ride 615546 / bill 620942 / emp 1637906 / fb 512873 / alerts 51699)", """
      SELECT 'ride' t, count(*) n, count(DISTINCT trip_id) d FROM trips
      UNION ALL SELECT 'bill', count(*), count(DISTINCT trip_id) FROM bill
      UNION ALL SELECT 'emp',  count(*), count(DISTINCT trip_id) FROM emp
      UNION ALL SELECT 'fb',   count(*), count(DISTINCT trip_id) FROM fb
      UNION ALL SELECT 'alerts',count(*),count(DISTINCT trip_id) FROM alerts
    """)
    show("V0b trip_id parse failures + date range", """
      SELECT count(*) FILTER (WHERE trip_id IS NULL) AS unparsed_ride_ids,
             min(trip_date) mn, max(trip_date) mx, count(DISTINCT trip_date) n_days
      FROM trips
    """)
    show("V0c planned_km comma row (dataquality MEDIUM-10: 1 row, trip 1530501)", """
      SELECT count(*) n_comma FROM read_csv('""" + RAW + """/Ride_data*.csv',
        header=true, union_by_name=true, null_padding=true, ignore_errors=true,
        all_varchar=true, sample_size=-1) WHERE planned_km LIKE '%,%'
    """)


def s_ota():
    show("V1 headline OTA by month (claimed 95.31 / 92.46 / 94.69)", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) ota_delay_col,
             round(100.0*avg(CASE WHEN aee-pee <= 300 THEN 1 ELSE 0 END),2) ota_end_epoch,
             round(100.0*avg(CASE WHEN ase-pse <= 300 THEN 1 ELSE 0 END),2) ota_start_epoch
      FROM trips GROUP BY 1 ORDER BY 1
    """)
    show("V2 delay_minutes is a function of delay_reason (claimed 0 contradictions)", """
      SELECT delay_reason, count(*) n,
             round(100.0*avg(CASE WHEN delay_minutes=0 THEN 1 ELSE 0 END),3) pct_zero,
             round(avg(delay_minutes),2) avg_delay,
             round(avg((aee-pee)/60.0),2) avg_epoch_end_late
      FROM trips GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V2b contradiction count + clipping (claimed min=0, median=0, p90=0, 0 negatives)", """
      SELECT count(*) FILTER (WHERE delay_reason='NODELAY' AND delay_minutes>0) nodelay_positive,
             count(*) FILTER (WHERE delay_reason<>'NODELAY' AND delay_minutes=0) reason_zero,
             min(delay_minutes) mn, median(delay_minutes) med,
             quantile_cont(delay_minutes,0.9) p90, max(delay_minutes) mx,
             count(*) FILTER (WHERE delay_minutes<0) n_negative
      FROM trips
    """)
    show("V2c 'agreement' depends on definition (timeliness 45.62% vs crosstable 4.75%)", """
      SELECT count(*) n,
        round(100.0*avg(CASE WHEN abs(delay_minutes - greatest(0,(aee-pee)/60.0))<1 THEN 1 ELSE 0 END),2) pct_match_clipped_1min,
        round(100.0*avg(CASE WHEN abs(delay_minutes - (aee-pee)/60.0)<1 THEN 1 ELSE 0 END),2) pct_match_raw_1min,
        round(avg(abs(delay_minutes - (aee-pee)/60.0)),2) mean_abs_gap_raw
      FROM trips
    """)
    show("V3 delay_minutes correlation with END vs START deviation, by direction (ex SPOT_2.0)", """
      SELECT trip_direction, count(*) n,
             round(corr(delay_minutes, (aee-pee)/60.0),3) corr_end,
             round(corr(delay_minutes, (ase-pse)/60.0),3) corr_start
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V4 LOGOUT CAB: reported OTA vs mean end deviation by rider count (the inversion)", """
      SELECT emp_actual riders, count(*) n, round(100.0*avg(on_time),2) reported_ota,
             round(avg((aee-pee)/60.0),2) mean_end_dev
      FROM trips WHERE product_type='CAB' AND trip_direction='LOGOUT' AND emp_actual BETWEEN 1 AND 6
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1
    """)


def s_shift():
    show("V5 :15/:16 shift codes (claimed 87,546 + 34,664, 100.00% and 99.64% OTA)", """
      SELECT CASE WHEN shift_type LIKE '%:%' THEN right(shift_type,2) ELSE shift_type END suffix,
             count(DISTINCT shift_type) shifts, count(*) n,
             round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay,
             max(delay_minutes) mx
      FROM trips GROUP BY 1 ORDER BY 3 DESC
    """)
    show("V6 headline OTA with/without :15,:16 (claimed 94.05 / 90.71 / 93.44)", """
      SELECT month, count(*) n_all,
             round(100.0*avg(on_time),2) ota_all,
             count(*) FILTER (WHERE right(shift_type,2) IN ('15','16')) n_1516,
             round(100.0*avg(on_time) FILTER (WHERE right(shift_type,2) NOT IN ('15','16')),2) ota_excl
      FROM trips GROUP BY 1 ORDER BY 1
    """)
    show("V7 :15/:16 are 100% LOGOUT and depart early but arrive late", """
      SELECT CASE WHEN right(shift_type,2) IN ('15','16') THEN '1516' ELSE 'normal' END g,
             count(*) n, round(100.0*avg(on_time),2) reported_ota,
             round(100.0*avg(CASE WHEN aee-pee<=300 THEN 1 ELSE 0 END),2) epoch_ota,
             round(avg((aee-pee)/60.0),2) mean_end_dev,
             round(avg((ase-pse)/60.0),2) mean_start_dev,
             round(100.0*avg(CASE WHEN trip_direction='LOGOUT' THEN 1 ELSE 0 END),2) pct_logout
      FROM trips GROUP BY 1
    """)


def s_spot():
    show("V8 SPOT_2.0 share of delay minutes (claimed 2,323 trips / 38.92%)", """
      SELECT product_type, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),1) mean_delay, round(sum(delay_minutes),0) delay_min,
             round(100.0*sum(delay_minutes)/(SELECT sum(delay_minutes) FROM trips),2) pct_all_delay
      FROM trips GROUP BY 1 ORDER BY 5 DESC
    """)
    show("V9 worst-1% concentration with vs without SPOT_2.0 (claimed 37.43 -> 7.80)", """
      WITH a AS (SELECT delay_minutes d, ntile(100) OVER (ORDER BY delay_minutes DESC) b
                 FROM trips WHERE delay_minutes>0),
           x AS (SELECT delay_minutes d, ntile(100) OVER (ORDER BY delay_minutes DESC) b
                 FROM trips WHERE delay_minutes>0 AND product_type<>'SPOT_2.0')
      SELECT 'ALL' pop, count(*) n, round(sum(d),0) tot,
             round(100.0*sum(d) FILTER (WHERE b=1)/sum(d),2) pct_worst1
      FROM a
      UNION ALL
      SELECT 'EX_SPOT', count(*), round(sum(d),0),
             round(100.0*sum(d) FILTER (WHERE b=1)/sum(d),2) FROM x
    """)
    show("V9b SLA minutes per trip flips sign when SPOT is excluded (1.47/1.35/1.01 vs 0.47/0.89/0.52)", """
      SELECT month, round(avg(delay_minutes),2) min_per_trip_all,
             round(avg(delay_minutes) FILTER (WHERE product_type<>'SPOT_2.0'),2) min_per_trip_exspot
      FROM trips GROUP BY 1 ORDER BY 1
    """)


def s_dow():
    show("V10 weekday OTA (claimed Tue 91.25 vs Fri 97.66)", """
      SELECT dayname(trip_date) dow, count(*) n,
             round(count(*)/count(DISTINCT trip_date),0) trips_per_day,
             round(sum(emp_actual)/count(DISTINCT trip_date),0) seats_per_day,
             round(100.0*avg(on_time),2) ota
      FROM trips WHERE dayofweek(trip_date) BETWEEN 1 AND 5
      GROUP BY 1 ORDER BY 5
    """)
    show("V11 within-office load quintile vs OTA (claimed 96.61 -> 92.21 monotonic)", """
      WITH d AS (SELECT office, trip_date, count(*) n, avg(on_time) ot
                 FROM trips WHERE dayofweek(trip_date) BETWEEN 1 AND 5
                 GROUP BY 1,2),
           q AS (SELECT *, ntile(5) OVER (PARTITION BY office ORDER BY n) qt FROM d)
      SELECT qt, count(*) office_days, round(avg(n),0) mean_trips_day,
             round(100.0*sum(n*ot)/sum(n),2) ota
      FROM q GROUP BY 1 ORDER BY 1
    """)
    show("V12 the June dip by ISO week (claimed wk23 = 89.44)", """
      SELECT weekofyear(trip_date) wk, min(trip_date) wk_start, count(*) n,
             round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1 ORDER BY 1
    """)


def s_ids():
    show("V13 trip_id collisions (claimed 6,753 ids, orbit-Slc <-> vanta-Aus)", """
      WITH d AS (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1)
      SELECT count(*) n_colliding_ids,
             (SELECT count(*) FROM trips WHERE trip_id IN (SELECT trip_id FROM d)) rows_affected
      FROM d
    """)
    show("V13b which BUs collide", """
      WITH d AS (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1)
      SELECT business_unit, count(*) rows_on_colliding_ids
      FROM trips WHERE trip_id IN (SELECT trip_id FROM d) GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V14 fan-out damage: join on trip_id vs (trip_id,BU) (claimed +Rs18.42M)", """
      SELECT 'trip_id only' j, count(*) n, round(sum(b.cost),2) tot
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id
      UNION ALL
      SELECT '(trip_id,BU)', count(*), round(sum(b.cost),2)
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
    """)


def s_bill():
    show("V15 gross / credits / net / overhead (claimed 849.48M / -15.50M / 833.98M / 4.46M)", """
      SELECT round(sum(cost) FILTER (WHERE cost>0),2) gross,
             round(sum(cost) FILTER (WHERE cost<0),2) credits,
             round(sum(cost),2) net,
             count(*) FILTER (WHERE cost<0) n_credit_rows,
             count(*) FILTER (WHERE trip_id_raw='OverHead') n_overhead,
             round(sum(cost) FILTER (WHERE trip_id_raw='OverHead'),2) overhead_spend
      FROM bill
    """)
    show("V16 credits by cycle month + top office/vendor (claimed 99.86% in May, Pinecrest negative)", """
      SELECT cycle_month, count(*) FILTER (WHERE cost<0) n_credits,
             round(sum(cost) FILTER (WHERE cost<0),2) credit_value
      FROM bill GROUP BY 1 ORDER BY 1
    """)
    show("V16b office net spend where credits land", """
      SELECT office, count(*) n, round(sum(cost),2) net,
             round(sum(cost) FILTER (WHERE cost>0),2) gross,
             round(sum(cost) FILTER (WHERE cost<0),2) credits
      FROM bill WHERE office IN ('Pinecrest Office','Denver Office','Maple Grove Office')
      GROUP BY 1 ORDER BY 3
    """)
    show("V17 zero-km share (claimed ~40% rows / 45.4% spend; per-contract split)", """
      SELECT round(100.0*avg(CASE WHEN km=0 THEN 1 ELSE 0 END),2) pct_rows_zero_km,
             round(100.0*sum(cost) FILTER (WHERE km=0)/sum(cost),2) pct_spend_zero_km,
             count(*) FILTER (WHERE km=0) n_zero
      FROM bill WHERE trip_id_raw<>'OverHead'
    """)
    show("V17b contract-level zero-km (fixed vs distance vs the mixed 6S-EV-HTK)", """
      SELECT contract, count(*) n, round(100.0*avg(CASE WHEN km=0 THEN 1 ELSE 0 END),2) pct_zero,
             round(sum(cost),0) spend
      FROM bill WHERE trip_id_raw<>'OverHead'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 3 DESC LIMIT 20
    """)
    show("V18 blended vs distance-only cost per km (claimed 146.70 vs 80.49)", """
      SELECT round(sum(cost)/sum(km),2) blended_cpk_all_rows,
             round(sum(cost) FILTER (WHERE km>0)/sum(km) FILTER (WHERE km>0),2) cpk_km_bearing_rows
      FROM bill WHERE trip_id_raw<>'OverHead' AND cost>0
    """)
    show("V19 slab_name label variants (claimed 30 raw -> 19 normalised)", """
      SELECT count(DISTINCT slab_name) raw_labels,
             count(DISTINCT CASE WHEN slab_name IN ('null','NA','0') THEN 'UNLABELLED'
                   ELSE upper(regexp_replace(regexp_replace(slab_name,'^[Ss]lab[- ]?',''),'[ _-]','','g')) END) normalised
      FROM bill
    """)
    show("V19b string 'null' sentinel spend (claimed 121,111 rows / Rs184.9M unlabelled)", """
      SELECT slab_name, count(*) n, round(sum(cost),0) spend
      FROM bill WHERE slab_name IN ('null','NA','0') GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V20 BUS-ORRNEW-TT vendor spread at Denver (claimed 1992.49 vs 1475.00 = 35.1%)", """
      SELECT office, vendor, count(*) n, round(avg(cost),2) avg_cost,
             round(median(cost),2) med_cost, round(sum(cost),2) spend, round(avg(km),2) avg_km
      FROM bill WHERE contract='BUS-ORRNEW-TT' AND cost>0
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 4 DESC
    """)


def s_fb():
    show("V21 marshal_rating distribution (claimed 473,692 zeros; avg 0.371 vs 4.857)", """
      SELECT marshal_rating v, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),3) pct
      FROM fb GROUP BY 1 ORDER BY 1
    """)
    show("V21b the 13x trap", """
      SELECT round(avg(marshal_rating),3) naive_avg,
             round(avg(marshal_rating) FILTER (WHERE marshal_rating>0),3) excl_zero,
             count(*) FILTER (WHERE marshal_rating>0) n_real
      FROM fb
    """)
    show("V21c marshal is rated iff an escort was aboard (claimed 98.43% vs 0.16%)", """
      SELECT t.actual_escort, count(*) n,
             count(*) FILTER (WHERE f.marshal_rating>0) marshal_rated,
             round(100.0*count(*) FILTER (WHERE f.marshal_rating>0)/count(*),2) pct
      FROM fb f JOIN trips t ON f.trip_id=t.trip_id AND f.business_unit=t.business_unit
      GROUP BY 1
    """)
    show("V22 DISCREPANCY CHECK: feedback coverage by BU, both join keys", """
      WITH tr AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           r_bu AS (SELECT business_unit, count(*) fb_rows,
                           count(DISTINCT trip_id) fb_trips FROM fb GROUP BY 1),
           j_id AS (SELECT t.business_unit, count(DISTINCT t.trip_id) covered
                    FROM trips t JOIN fb f ON t.trip_id=f.trip_id GROUP BY 1),
           j_bu AS (SELECT t.business_unit, count(DISTINCT t.trip_id) covered
                    FROM trips t JOIN fb f ON t.trip_id=f.trip_id
                                          AND t.business_unit=f.business_unit GROUP BY 1)
      SELECT tr.business_unit, tr.trips, r_bu.fb_rows,
             round(100.0*r_bu.fb_rows/tr.trips,2)      resp_rate_rows,
             round(100.0*j_bu.covered/tr.trips,2)      coverage_join_bu,
             round(100.0*j_id.covered/tr.trips,2)      coverage_join_tripid_only
      FROM tr JOIN r_bu USING (business_unit)
              JOIN j_id USING (business_unit) JOIN j_bu USING (business_unit)
      ORDER BY 5
    """)
    show("V23 detractor rate: feedback-weighted vs trip-weighted (claimed 0.50 vs 2.21)", """
      WITH d AS (SELECT f.business_unit bu, count(*) n,
                        100.0*count(*) FILTER (WHERE f.driver_rating<=2)/count(*) det
                 FROM fb f GROUP BY 1),
           t AS (SELECT business_unit bu, count(*) trips FROM trips GROUP BY 1)
      SELECT round(sum(d.n*d.det)/sum(d.n),4) det_feedback_weighted,
             round(sum(t.trips*d.det)/sum(t.trips),4) det_trip_weighted
      FROM d JOIN t USING (bu)
    """)
    show("V24 detractor rate by month is ~100x more sensitive than the mean (0.736/0.896/0.795)", """
      SELECT t.month, count(*) n, round(avg(f.route_rating),4) route_mean,
             round(100.0*avg(CASE WHEN f.route_rating=5 THEN 1 ELSE 0 END),3) pct_5star,
             round(100.0*avg(CASE WHEN f.route_rating<=2 THEN 1 ELSE 0 END),3) det_pct
      FROM fb f JOIN trips t ON f.trip_id=t.trip_id AND f.business_unit=t.business_unit
      GROUP BY 1 ORDER BY 1
    """)
    show("V25 rating dimensions are 2 questions not 5 (claimed r=0.94-0.95, route 0.85)", """
      SELECT round(corr(route_rating,driver_rating),4) route_driver,
             round(corr(driver_rating,cab_rating),4)   driver_cab,
             round(corr(driver_rating,safety_rating),4) driver_safety,
             round(corr(cab_rating,safety_rating),4)   cab_safety
      FROM fb
    """)
    show("V26 objective quality of rated vs unrated trips inside low-response BUs", """
      WITH r AS (SELECT DISTINCT trip_id, business_unit FROM fb)
      SELECT t.business_unit, CASE WHEN r.trip_id IS NULL THEN 'UNRATED' ELSE 'rated' END g,
             count(*) trips, round(100.0*avg(t.on_time),2) pct_on_time,
             round(avg(t.delay_minutes),2) avg_delay
      FROM trips t LEFT JOIN r ON t.trip_id=r.trip_id AND t.business_unit=r.business_unit
      GROUP BY 1,2 ORDER BY 1,2
    """)


def s_emp():
    show("V27 not-boarded vs is_no_show by BU (claimed pinnacle 14.87 > vanta-Sea 13.27)", """
      SELECT business_unit, count(*) legs,
             round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1 ELSE 0 END),2) not_boarded_pct,
             round(100.0*avg(CASE WHEN is_no_show='True' THEN 1 ELSE 0 END),2) noshow_flag_pct,
             round(100.0*avg(CASE WHEN not_boarding_reason='TRIP_CANCELLED_FROM_DASHBOARD' THEN 1 ELSE 0 END),2) cancel_pct
      FROM emp GROUP BY 1 ORDER BY 3 DESC
    """)
    show("V27b the two global no-show definitions (claimed 11.601 vs 7.206)", """
      SELECT round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1 ELSE 0 END),3) by_status,
             round(100.0*avg(CASE WHEN is_no_show='True' THEN 1 ELSE 0 END),3) by_flag,
             count(*) FILTER (WHERE not_boarding_reason='TRIP_CANCELLED_FROM_DASHBOARD') n_cancel
      FROM emp
    """)
    show("V28 rider pickup OTA vs trip OTA, same trips (claimed ~71.5 vs ~95)", """
      SELECT e.month, count(*) legs,
             round(100.0*avg(CASE WHEN (e.ape-e.ppe)/60.0<=5 THEN 1 ELSE 0 END),2) rider_pickup_ota,
             round(100.0*avg(t.on_time),2) trip_ota_same_legs
      FROM emp e JOIN trips t ON e.trip_id=t.trip_id AND e.business_unit=t.business_unit
      WHERE e.ape IS NOT NULL AND e.ppe IS NOT NULL
      GROUP BY 1 ORDER BY 1
    """)
    show("V29 in-cab planned vs actual minutes by direction (claimed LOGOUT +10 to +12)", """
      SELECT t.trip_direction, e.month, count(*) n,
             round(avg((e.pde-e.ppe)/60.0),2) planned_min,
             round(avg((e.ade-e.ape)/60.0),2) actual_min,
             round(avg((e.ade-e.ape)/60.0) - avg((e.pde-e.ppe)/60.0),2) overrun
      FROM emp e JOIN trips t ON e.trip_id=t.trip_id AND e.business_unit=t.business_unit
      WHERE e.ape IS NOT NULL AND e.ppe IS NOT NULL AND e.ade IS NOT NULL AND e.pde IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("V29b implied planned vs actual km/h by direction (claimed 21.7 vs 16.8 LOGOUT)", """
      SELECT t.trip_direction, count(*) n,
             round(avg(e.planned_km),2) avg_planned_km,
             round(avg((e.pde-e.ppe)/60.0),2) planned_min,
             round(avg(e.planned_km)/(avg((e.pde-e.ppe)/60.0)/60),1) planned_kmh,
             round(avg(e.planned_km)/(avg((e.ade-e.ape)/60.0)/60),1) actual_kmh
      FROM emp e JOIN trips t ON e.trip_id=t.trip_id AND e.business_unit=t.business_unit
      WHERE e.ape IS NOT NULL AND e.ade IS NOT NULL AND e.ppe IS NOT NULL AND e.pde IS NOT NULL
      GROUP BY 1
    """)
    show("V30 LOGOUT drop lateness >15 min (claimed ~1 in 3)", """
      SELECT t.trip_direction, e.month, count(*) n,
             round(100.0*avg(CASE WHEN (e.ade-e.pde)/60.0<=5 THEN 1 ELSE 0 END),2) drop_le5,
             round(100.0*avg(CASE WHEN (e.ade-e.pde)/60.0>15 THEN 1 ELSE 0 END),2) drop_gt15
      FROM emp e JOIN trips t ON e.trip_id=t.trip_id AND e.business_unit=t.business_unit
      WHERE e.ade IS NOT NULL AND e.pde IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("V31 rider pain concentration (claimed top 5% absorb 35% of >15-min-late pickups)", """
      WITH r AS (SELECT stwid, count(*) legs,
                        count(*) FILTER (WHERE (ape-ppe)/60.0>15) late15
                 FROM emp WHERE ape IS NOT NULL AND ppe IS NOT NULL
                   AND stwid NOT IN ('0','0.0') GROUP BY 1),
           q AS (SELECT *, ntile(20) OVER (ORDER BY late15 DESC) v FROM r WHERE late15>0 OR legs>0)
      SELECT count(*) riders, sum(late15) total_late15,
             round(100.0*sum(late15) FILTER (WHERE v=1)/sum(late15),2) pct_from_top5pct,
             round(100.0*sum(late15) FILTER (WHERE v<=2)/sum(late15),2) pct_from_top10pct
      FROM q
    """)
    show("V32 within-office rider spread, Clearwater (claimed 22x, 19.44% vs 0.88%)", """
      WITH r AS (SELECT stwid, count(*) legs, count(*) FILTER (WHERE (ape-ppe)/60.0>15) late15
                 FROM emp WHERE office='Clearwater Campus' AND ape IS NOT NULL AND ppe IS NOT NULL
                   AND stwid NOT IN ('0','0.0') GROUP BY 1 HAVING count(*)>=20),
           q AS (SELECT *, ntile(5) OVER (ORDER BY 1.0*late15/legs DESC) v FROM r)
      SELECT v quintile, count(*) riders, sum(legs) legs, sum(late15) late15,
             round(100.0*sum(late15)/sum(legs),2) rate
      FROM q GROUP BY 1 ORDER BY 1
    """)


def s_alerts():
    show("V33 ack-latency buckets: the T+24h auto-close spike (claimed 16,157 = 31.25%)", """
      WITH a AS (SELECT *, date_diff('minute', start_ts, ack_ts) m FROM alerts)
      SELECT CASE WHEN ack_ts IS NULL THEN 'never'
                  WHEN m<=5 THEN 'a <=5m' WHEN m<=15 THEN 'b 6-15m'
                  WHEN m<=60 THEN 'c 16-60m' WHEN m<=600 THEN 'd 1-10h'
                  WHEN m<1435 THEN 'e 10-23.9h'
                  WHEN m<=1450 THEN 'f 23.9-24.2h AUTOCLOSE'
                  ELSE 'g >24.2h' END bucket,
             count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
      FROM a GROUP BY 1 ORDER BY 1
    """)
    show("V34 auto-close by BU + severity='NA' marker", """
      WITH a AS (SELECT *, date_diff('minute', start_ts, ack_ts) m FROM alerts)
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE m BETWEEN 1435 AND 1450) autoclosed,
             round(100.0*count(*) FILTER (WHERE m BETWEEN 1435 AND 1450)/count(*),2) pct
      FROM a GROUP BY 1 ORDER BY 4 DESC
    """)
    show("V34b catalyst-Sac geofence: 100% auto-closed vs every other BU 0%", """
      WITH a AS (SELECT *, date_diff('minute', start_ts, ack_ts) m FROM alerts)
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE m BETWEEN 1435 AND 1450) autoclosed,
             round(100.0*count(*) FILTER (WHERE m BETWEEN 1435 AND 1450)/count(*),2) pct,
             round(median(m),1) med_min
      FROM a WHERE event_type='EMPLOYEE_GEOFENCE_VIOLATION' GROUP BY 1 ORDER BY 4 DESC
    """)
    show("V35 sign-off detector cliff on 2026-05-18 (claimed 7,666 before / 70 after)", """
      SELECT start_date d, count(*) n
      FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
        AND start_date BETWEEN DATE '2026-05-12' AND DATE '2026-05-25'
      GROUP BY 1 ORDER BY 1
    """)
    show("V35b every other event type grows across the same boundary", """
      SELECT event_type,
             count(*) FILTER (WHERE start_date < DATE '2026-05-18') n_before,
             count(*) FILTER (WHERE start_date >= DATE '2026-05-18') n_after,
             count(*) n
      FROM alerts GROUP BY 1 ORDER BY 4 DESC
    """)
    show("V36 severity taxonomy is per-BU config, not risk (claimed 648/656 Sev-1 in catalyst)", """
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE severity='Sev-1') sev1,
             count(*) FILTER (WHERE severity='Sev-2') sev2,
             count(*) FILTER (WHERE severity='Sev-3') sev3,
             count(*) FILTER (WHERE severity='NA') na,
             count(*) FILTER (WHERE severity='False') falsev
      FROM alerts GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V37 alerts.stwid=0 is a clean vehicle/employee split, not missingness", """
      SELECT event_type, count(*) n,
             round(100.0*avg(CASE WHEN stwid IN ('0','0.0') THEN 1 ELSE 0 END),2) pct_stwid0
      FROM alerts GROUP BY 1 ORDER BY 2 DESC
    """)
    show("V38 WTA detector coverage per 1k trips by BU (claimed off in 3 of 5 BUs)", """
      WITH t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           a AS (SELECT business_unit, count(*) wta FROM alerts
                 WHERE event_type='WOMAN_TRAVELLING_ALONE' GROUP BY 1)
      SELECT t.business_unit, t.trips, coalesce(a.wta,0) wta,
             round(1000.0*coalesce(a.wta,0)/t.trips,2) per_1k
      FROM t LEFT JOIN a USING (business_unit) ORDER BY 4 DESC
    """)


def s_esc():
    show("V39 escort rate by shift hour, LOGOUT CAB, female last drop (claimed cliff at 19:00)", """
      WITH ld AS (SELECT trip_id, business_unit,
                    arg_max(gender, ade) last_gender
                  FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT TRY_CAST(left(t.shift_type,2) AS INT) shift_hour,
             count(*) female_last_drop,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct_escort,
             count(*) FILTER (WHERE NOT t.actual_escort) n_unescorted,
             round(median((t.aee-t.ase)/60.0),1) med_dur_min
      FROM trips t JOIN ld ON t.trip_id=ld.trip_id AND t.business_unit=ld.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND ld.last_gender='FEMALE'
        AND t.shift_type LIKE '__:__'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1
    """)
    show("V40 same real-world exposure, different policy bucket (claimed 34.92 vs 95.98)", """
      WITH ld AS (SELECT trip_id, business_unit, arg_max(gender, ade) last_gender, max(ade) last_drop
                  FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT TRY_CAST(left(t.shift_type,2) AS INT) shift_hour, count(*) n,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct_escort
      FROM trips t JOIN ld ON t.trip_id=ld.trip_id AND t.business_unit=ld.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND ld.last_gender='FEMALE'
        AND t.shift_type IN ('18:00','19:00','18:30','19:30')
        AND (t.aee - t.ase)/60.0 BETWEEN 0 AND 300
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1
    """)
    show("V41 unescorted female-last-drop night LOGOUT by BU (claimed orbit-Slc 23.28%)", """
      WITH ld AS (SELECT trip_id, business_unit, arg_max(gender, ade) last_gender
                  FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT t.business_unit, count(*) n,
             count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*avg(CASE WHEN NOT t.actual_escort THEN 1 ELSE 0 END),2) pct_no_escort
      FROM trips t JOIN ld ON t.trip_id=ld.trip_id AND t.business_unit=ld.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND ld.last_gender='FEMALE'
        AND (TRY_CAST(left(t.shift_type,2) AS INT) >= 19
             OR TRY_CAST(left(t.shift_type,2) AS INT) <= 5)
      GROUP BY 1 ORDER BY 4 DESC
    """)
    show("V42 breach trend: unescorted night LOGOUT whose last drop was female (220/44/4)", """
      WITH ld AS (SELECT trip_id, business_unit, arg_max(gender, ade) last_gender
                  FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT t.month, count(*) unescorted_night_logout,
             count(*) FILTER (WHERE ld.last_gender='FEMALE') last_drop_female,
             round(100.0*avg(CASE WHEN ld.last_gender='FEMALE' THEN 1 ELSE 0 END),2) pct
      FROM trips t JOIN ld ON t.trip_id=ld.trip_id AND t.business_unit=ld.business_unit
      WHERE t.trip_direction='LOGOUT' AND NOT t.actual_escort
        AND (TRY_CAST(left(t.shift_type,2) AS INT) >= 19
             OR TRY_CAST(left(t.shift_type,2) AS INT) <= 5)
      GROUP BY 1 ORDER BY 1
    """)
    show("V43 escort composition test excluding escort legs (claimed 99.70% female-only night)", """
      WITH comp AS (
        SELECT trip_id, business_unit,
               count(*) FILTER (WHERE gender='FEMALE') f,
               count(*) FILTER (WHERE gender='MALE') m
        FROM emp WHERE boarding_status='Boarded' AND coalesce(emp_role,'x')<>'escort'
        GROUP BY 1,2)
      SELECT CASE WHEN f>0 AND m=0 THEN 'female-only' WHEN m>0 AND f=0 THEN 'male-only'
                  WHEN f>0 AND m>0 THEN 'mixed' ELSE 'other' END composition,
             CASE WHEN TRY_CAST(left(t.shift_type,2) AS INT)>=19
                    OR TRY_CAST(left(t.shift_type,2) AS INT)<=5 THEN 'night' ELSE 'day' END tod,
             count(*) trips, count(*) FILTER (WHERE t.actual_escort) escorted,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct
      FROM trips t JOIN comp c ON t.trip_id=c.trip_id AND t.business_unit=c.business_unit
      WHERE t.shift_type LIKE '__:__'
      GROUP BY 1,2 ORDER BY 1,2
    """)


def s_cost():
    show("V44 no-show cost, raw vs controlled for contract (claimed reverses)", """
      WITH j AS (SELECT t.trip_id, t.business_unit, t.noshow, t.emp_planned, t.emp_actual,
                        b.contract, b.cost
                 FROM trips t JOIN bill b
                   ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
                 WHERE b.cost>0 AND b.trip_id_raw<>'OverHead')
      SELECT CASE WHEN noshow=0 THEN '0' WHEN noshow=1 THEN '1'
                  WHEN noshow=2 THEN '2' ELSE '3+' END g,
             count(*) n, round(avg(cost),2) avg_cost,
             round(avg(emp_planned),2) planned, round(avg(emp_actual),2) actual
      FROM j GROUP BY 1 ORDER BY 1
    """)
    show("V44b same, within contract (n>=1000 both cells)", """
      WITH j AS (SELECT t.noshow, b.contract, b.cost
                 FROM trips t JOIN bill b
                   ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
                 WHERE b.cost>0 AND b.trip_id_raw<>'OverHead')
      SELECT contract, count(*) FILTER (WHERE noshow=0) n_no_ns,
             round(avg(cost) FILTER (WHERE noshow=0),2) cost_no_ns,
             count(*) FILTER (WHERE noshow>0) n_ns,
             round(avg(cost) FILTER (WHERE noshow>0),2) cost_ns,
             round(avg(cost) FILTER (WHERE noshow>0) - avg(cost) FILTER (WHERE noshow=0),2) delta
      FROM j GROUP BY 1
      HAVING count(*) FILTER (WHERE noshow=0)>=1000 AND count(*) FILTER (WHERE noshow>0)>=1000
      ORDER BY 6
    """)
    show("V45 no-show seat value by month (claimed Rs48.68M, 7.32->4.41%)", """
      WITH j AS (SELECT t.month, t.noshow, t.emp_planned, b.cost
                 FROM trips t JOIN bill b
                   ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
                 WHERE b.cost>0 AND b.trip_id_raw<>'OverHead' AND t.emp_planned>0)
      SELECT month, count(*) n, sum(noshow) seats_noshow, round(sum(cost),0) spend,
             round(sum(cost*noshow/emp_planned),0) noshow_seat_value,
             round(100.0*sum(cost*noshow/emp_planned)/sum(cost),2) pct_of_spend
      FROM j GROUP BY 1 ORDER BY 1
    """)
    show("V46 Meera Lebedev Travel vs its own office+month peers (claimed -28.85pt OTA gap)", """
      WITH p AS (SELECT office, month, sum(on_time) s, count(*) c FROM trips GROUP BY 1,2)
      SELECT t.vendor_id, count(*) n, round(100.0*avg(t.on_time),2) ota_vendor,
             round(100.0*sum(p.s - t.on_time)/sum(p.c - 1),2) peer_ota,
             round(100.0*avg(t.on_time) - 100.0*sum(p.s - t.on_time)/sum(p.c - 1),2) gap
      FROM trips t JOIN p ON t.office=p.office AND t.month=p.month
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY 5 LIMIT 6
    """)
    show("V46b Meera Lebedev profile (claimed 180.96 alerts/1k, 28.7% occ, growing)", """
      WITH a AS (SELECT trip_id, business_unit, count(*) c FROM alerts GROUP BY 1,2)
      SELECT t.month, count(*) n, round(100.0*avg(t.on_time),2) ota,
             round(1000.0*sum(coalesce(a.c,0))/count(*),2) alerts_per_1k,
             round(avg(t.emp_actual),2) riders, round(avg(t.cab_capacity),2) cap
      FROM trips t LEFT JOIN a ON t.trip_id=a.trip_id AND t.business_unit=a.business_unit
      WHERE t.vendor_id='Meera Lebedev Travel' GROUP BY 1 ORDER BY 1
    """)
    show("V47 vendor cost index on identical contract+BU+month (claimed 6.6pt spread)", """
      WITH j AS (SELECT b.vendor, b.contract, b.business_unit, b.cycle_month, b.cost
                 FROM bill b WHERE b.cost>0 AND b.trip_id_raw<>'OverHead'),
           p AS (SELECT contract, business_unit, cycle_month, avg(cost) peer FROM j GROUP BY 1,2,3)
      SELECT j.vendor, count(*) n, round(100.0*avg(j.cost/p.peer),2) cost_index
      FROM j JOIN p USING (contract, business_unit, cycle_month)
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY 3 DESC
    """)


def s_misc():
    show("V48 WTA flagged rider rates safety 16x worse (claimed 12.99% vs 0.793%)", """
      WITH w AS (SELECT DISTINCT trip_id, business_unit, stwid FROM alerts
                 WHERE event_type='WOMAN_TRAVELLING_ALONE')
      SELECT 'flagged rider' g, count(*) n, round(avg(f.safety_rating),3) safety,
             round(100.0*avg(CASE WHEN f.safety_rating<=3 THEN 1 ELSE 0 END),3) pct_le3
      FROM fb f JOIN w ON f.trip_id=w.trip_id AND f.business_unit=w.business_unit
                      AND f.stwid=w.stwid
      UNION ALL
      SELECT 'all feedback baseline', count(*), round(avg(safety_rating),3),
             round(100.0*avg(CASE WHEN safety_rating<=3 THEN 1 ELSE 0 END),3) FROM fb
    """)
    show("V49 over-speeding alerts score HIGHER on safety (claimed 4.8988 vs 4.8879)", """
      WITH o AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE event_type='OVER_SPEEDING')
      SELECT CASE WHEN o.trip_id IS NULL THEN 'no overspeed alert' ELSE 'OVERSPEED' END g,
             count(*) n, round(avg(f.safety_rating),4) safety,
             round(100.0*avg(CASE WHEN f.safety_rating<=2 THEN 1 ELSE 0 END),3) det_pct
      FROM fb f LEFT JOIN o ON f.trip_id=o.trip_id AND f.business_unit=o.business_unit
      GROUP BY 1
    """)
    show("V50 is_driver_nc / is_cab_nc are NOT dead columns (timeliness claimed 0 on all rows)", """
      SELECT count(*) n,
             count(*) FILTER (WHERE is_driver_nc) driver_nc_true,
             count(*) FILTER (WHERE is_cab_nc) cab_nc_true,
             count(*) FILTER (WHERE is_driver_nc IS NULL) driver_nc_null
      FROM trips
    """)
    show("V50b driver-NC by BU+vendor (claimed 772/784 pinnacle, Rohan 1.401%)", """
      SELECT business_unit, vendor_id, count(*) n,
             count(*) FILTER (WHERE is_driver_nc) nc,
             round(100.0*avg(CASE WHEN is_driver_nc THEN 1 ELSE 0 END),3) pct
      FROM trips GROUP BY 1,2 HAVING count(*) FILTER (WHERE is_driver_nc)>0
      ORDER BY 5 DESC LIMIT 8
    """)
    show("V51 route_source SHUTTLE_SERVICE reclassification in July (169/196/8274)", """
      SELECT route_source,
             count(*) FILTER (WHERE month=DATE '2026-05-01') may,
             count(*) FILTER (WHERE month=DATE '2026-06-01') jun,
             count(*) FILTER (WHERE month=DATE '2026-07-01') jul
      FROM trips GROUP BY 1 ORDER BY 4 DESC
    """)
    show("V52 emp_planned = emp_actual + noshow holds only ~74% (claimed 73.93%)", """
      SELECT round(100.0*avg(CASE WHEN emp_planned = emp_actual + noshow THEN 1 ELSE 0 END),2) pct_exact,
             round(100.0*avg(CASE WHEN emp_actual + noshow > emp_planned THEN 1 ELSE 0 END),2) pct_over,
             round(100.0*avg(CASE WHEN emp_actual + noshow < emp_planned THEN 1 ELSE 0 END),2) pct_under,
             min(emp_actual) min_emp_actual
      FROM trips
    """)
    show("V53 2026-05-28 pinnacle outage across all four files", """
      SELECT d, ride, emp, fb, alerts FROM (
        SELECT trip_date d, count(*) ride,
          (SELECT count(*) FROM emp e WHERE e.trip_date=t.trip_date AND e.business_unit='pinnacle-Slc') emp,
          (SELECT count(*) FROM fb f JOIN trips t2 ON f.trip_id=t2.trip_id AND f.business_unit=t2.business_unit
             WHERE t2.trip_date=t.trip_date AND t2.business_unit='pinnacle-Slc') fb,
          (SELECT count(*) FROM alerts a WHERE a.start_date=t.trip_date AND a.business_unit='pinnacle-Slc') alerts
        FROM trips t WHERE t.business_unit='pinnacle-Slc'
          AND t.trip_date BETWEEN DATE '2026-05-26' AND DATE '2026-06-02'
        GROUP BY 1) ORDER BY 1
    """)
    show("V54 escort trips look better on OTA until you control (claimed effect vanishes)", """
      SELECT actual_escort, count(*) n, round(100.0*avg(on_time),2) ota,
             round(100.0*avg(CASE WHEN trip_direction='LOGOUT' THEN 1 ELSE 0 END),2) pct_logout,
             round(100.0*avg(CASE WHEN right(shift_type,2) IN ('15','16') THEN 1 ELSE 0 END),2) pct_1516
      FROM trips GROUP BY 1
    """)
    show("V55 solo trips: planned vs no-show driven (claimed 148,893 planned solo = 24.19%)", """
      SELECT count(*) n,
             count(*) FILTER (WHERE emp_actual=1) solo,
             count(*) FILTER (WHERE emp_actual=1 AND emp_planned=1) planned_solo,
             count(*) FILTER (WHERE emp_actual=1 AND emp_planned>1) became_solo,
             round(100.0*count(*) FILTER (WHERE emp_actual=1 AND emp_planned=1)/count(*),2) pct_planned_solo
      FROM trips
    """)
    show("V55b pinnacle-Slc same-fleet solo-rate contrast (claimed 44.79 vs 19.29)", """
      SELECT office, count(*) n,
             round(100.0*avg(CASE WHEN cab_capacity=3 THEN 1 ELSE 0 END),2) pct_cap3,
             round(100.0*avg(CASE WHEN emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
             round(avg(emp_planned),2) mean_planned_riders
      FROM trips WHERE business_unit='pinnacle-Slc'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 4 DESC
    """)


SECTIONS = {
    "base": s_base, "ota": s_ota, "shift": s_shift, "spot": s_spot, "dow": s_dow,
    "ids": s_ids, "bill": s_bill, "fb": s_fb, "emp": s_emp, "alerts": s_alerts,
    "esc": s_esc, "cost": s_cost, "misc": s_misc,
}

if __name__ == "__main__":
    build()
    want = sys.argv[1:] or list(SECTIONS)
    for s in want:
        print(f"\n{'='*78}\n== {s.upper()}\n{'='*78}")
        SECTIONS[s]()
