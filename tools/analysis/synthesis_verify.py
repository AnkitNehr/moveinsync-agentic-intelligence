#!/usr/bin/env python
"""
synthesis_verify.py -- independent re-verification of headline numbers claimed by the
seven area findings docs (timeliness, cost, safety, employees, feedback, dataquality,
crosstable) before they go into docs/FINDINGS.md.

Every check here is written from scratch against data/raw/, NOT copied from the other
agents' scripts, so agreement is real corroboration.

Run:  ./.venv/bin/python tools/analysis/synthesis_verify.py [check ...]
      (no args = run all)
"""
import sys
import duckdb

RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw"
con = duckdb.connect()
con.sql("SET TimeZone='UTC'")


def show(label, sql):
    print(f"\n--- {label}")
    rel = con.sql(sql)
    cols = rel.columns
    rows = [["" if v is None else (f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
             for v in r] for r in rel.fetchall()]
    w = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * w[i] for i in range(len(cols))))
    for r in rows:
        print("  ".join(r[i].ljust(w[i]) for i in range(len(cols))))
    print(f"[{len(rows)} rows]")


def build():
    con.sql(f"""
    CREATE OR REPLACE VIEW trips AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, office, product_type, vendor_id, trip_direction, shift_type,
      coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, route_source,
      strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
      date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
      TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes,
      TRY_CAST(replace(traveled_km,',','') AS DOUBLE) AS traveled_km,
      TRY_CAST(replace(planned_km,',','') AS DOUBLE) AS planned_km,
      TRY_CAST(planned_km AS DOUBLE) AS planned_km_naive,
      TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
      TRY_CAST(is_driver_nc AS BOOLEAN) AS is_driver_nc,
      TRY_CAST(is_cab_nc AS BOOLEAN) AS is_cab_nc,
      TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
      TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
      TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
      TRY_CAST(noshow_cnt AS INT) AS noshow,
      TRY_CAST(replace(planned_start_epoch,',','') AS BIGINT) AS planned_start_epoch,
      TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT) AS actual_start_epoch,
      TRY_CAST(replace(planned_end_epoch,',','') AS BIGINT) AS planned_end_epoch,
      TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
      CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
    FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
      null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW bill AS SELECT
      trip_id AS trip_id_raw,
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, office, vendor AS vendor_id, contract AS contract_name, slab_name,
      TRY_CAST(replace(trip_cost,',','') AS DOUBLE) AS trip_cost,
      TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS total_trip_km,
      date_trunc('month', strptime(cycle_start,'%B %d, %Y, %I:%M %p'))::DATE AS cycle_month
    FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW emp AS SELECT
      TRY_CAST(replace(CAST(trip_id AS VARCHAR),',','') AS BIGINT) AS trip_id,
      business_unit, office, product_type, shift_type,
      stwid, gender, emp_role, signintype,
      boarding_status, is_no_show, not_boarding_reason,
      TRY_CAST(trip_date AS DATE) AS trip_date,
      date_trunc('month', TRY_CAST(trip_date AS DATE))::DATE AS month,
      TRY_CAST(replace(CAST(planned_pickup_epoch AS VARCHAR),',','') AS BIGINT) AS planned_pickup_epoch,
      TRY_CAST(replace(CAST(actual_pickup_epoch  AS VARCHAR),',','') AS BIGINT) AS actual_pickup_epoch,
      TRY_CAST(replace(CAST(planned_drop_epoch   AS VARCHAR),',','') AS BIGINT) AS planned_drop_epoch,
      TRY_CAST(replace(CAST(actual_drop_epoch    AS VARCHAR),',','') AS BIGINT) AS actual_drop_epoch,
      TRY_CAST(replace(CAST(traveled_km AS VARCHAR),',','') AS DOUBLE) AS traveled_km,
      TRY_CAST(replace(CAST(planned_km AS VARCHAR),',','') AS DOUBLE) AS planned_km
    FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW fb AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, trip_type, stwid,
      TRY_CAST(route_rating AS INT) route_rating,
      TRY_CAST(driver_rating AS INT) driver_rating,
      TRY_CAST(cab_rating AS INT) cab_rating,
      TRY_CAST(safety_rating AS INT) safety_rating,
      TRY_CAST(marshal_rating AS INT) marshal_rating,
      strptime(creation_time,'%B %d, %Y, %I:%M %p') AS creation_time
    FROM read_csv('{RAW}/trip_feedback.csv', header=true, all_varchar=true, sample_size=-1)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW alerts AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, event_id, event_type, severity, state_text, stwid, source,
      strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_time,
      strptime(acknowledge_time,'%B %d, %Y, %I:%M %p') AS ack_time
    FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)
    """)


CHECKS = {}


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


@check
def c01_rowcounts():
    """V1: row counts across all 5 files"""
    show("row counts", """
      SELECT 'trips' t, count(*) n, count(DISTINCT trip_id) d_id FROM trips
      UNION ALL SELECT 'bill', count(*), count(DISTINCT trip_id) FROM bill
      UNION ALL SELECT 'emp', count(*), count(DISTINCT trip_id) FROM emp
      UNION ALL SELECT 'fb', count(*), count(DISTINCT trip_id) FROM fb
      UNION ALL SELECT 'alerts', count(*), count(DISTINCT trip_id) FROM alerts
    """)


@check
def c02_ota_month():
    """V2: headline OTA by month (claim 95.31/92.46/94.69)"""
    show("reported OTA by month", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) reported_ota,
             round(100.0*avg(CASE WHEN actual_end_epoch<=planned_end_epoch+300 THEN 1 ELSE 0 END),2) epoch_end_ota,
             round(median((actual_end_epoch-planned_end_epoch)/60.0),2) med_end_late_min
      FROM trips GROUP BY 1 ORDER BY 1
    """)


@check
def c03_delay_gate():
    """V3: delay_minutes is perfectly gated by delay_reason (dataquality HIGH-2 / crosstable F1)"""
    show("delay_reason vs delay_minutes", """
      SELECT delay_reason, count(*) n,
             round(100.0*avg(CASE WHEN delay_minutes=0 THEN 1 ELSE 0 END),3) pct_zero,
             round(avg(delay_minutes),2) avg_delay,
             round(avg(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)),2) avg_epoch_end_late
      FROM trips GROUP BY 1 ORDER BY n DESC
    """)
    show("contradictions", """
      SELECT count(*) n,
        count(*) FILTER (WHERE delay_reason='NODELAY' AND delay_minutes>0) nodelay_but_positive,
        count(*) FILTER (WHERE delay_reason<>'NODELAY' AND delay_minutes=0) reason_but_zero,
        round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(actual_end_epoch-planned_end_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),3) pct_agree_within_1min
      FROM trips
    """)


@check
def c04_shift_suffix():
    """V4: :15/:16 shift codes score ~100% OTA (timeliness F2)"""
    show("OTA by shift-time minute suffix", """
      SELECT CASE WHEN shift_type LIKE '%:%' THEN right(shift_type,2) ELSE shift_type END sfx,
             count(DISTINCT shift_type) n_shifts, count(*) n,
             round(100.0*avg(on_time),2) reported_ota,
             round(avg(delay_minutes),3) mean_delay,
             round(100.0*avg(CASE WHEN trip_direction='LOGOUT' THEN 1 ELSE 0 END),1) pct_logout
      FROM trips GROUP BY 1 ORDER BY n DESC
    """)
    show("headline OTA with and without :15/:16", """
      SELECT month, count(*) n_all,
        count(*) FILTER (WHERE right(shift_type,2) IN ('15','16') AND shift_type LIKE '%:%') n_1516,
        round(100.0*avg(on_time),2) headline_ota,
        round(100.0*avg(on_time) FILTER (WHERE NOT (right(shift_type,2) IN ('15','16') AND shift_type LIKE '%:%')),2) ota_excl
      FROM trips GROUP BY 1 ORDER BY 1
    """)


@check
def c05_spot():
    """V5: SPOT_2.0 carries ~39% of all delay minutes (timeliness F4)"""
    show("delay minutes by product", """
      SELECT product_type, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),1) mean_delay, round(sum(delay_minutes),0) delay_min,
             round(100.0*sum(delay_minutes)/(SELECT sum(delay_minutes) FROM trips),2) pct_all_delay_min
      FROM trips GROUP BY 1 ORDER BY delay_min DESC
    """)
    show("concentration of delay with / without SPOT_2.0", """
      WITH a AS (SELECT delay_minutes, ntile(100) OVER (ORDER BY delay_minutes DESC) p
                 FROM trips WHERE delay_minutes>0),
           b AS (SELECT delay_minutes, ntile(100) OVER (ORDER BY delay_minutes DESC) p
                 FROM trips WHERE delay_minutes>0 AND product_type<>'SPOT_2.0')
      SELECT 'ALL' pop, count(*) n, round(sum(delay_minutes),0) tot,
             round(100.0*sum(delay_minutes) FILTER (WHERE p=1)/sum(delay_minutes),2) pct_worst_1pct FROM a
      UNION ALL
      SELECT 'EXCL SPOT_2.0', count(*), round(sum(delay_minutes),0),
             round(100.0*sum(delay_minutes) FILTER (WHERE p=1)/sum(delay_minutes),2) FROM b
    """)


@check
def c06_dow():
    """V6: Tuesday vs Friday OTA (timeliness F5)"""
    show("OTA by weekday", """
      SELECT dayname(trip_date) AS dow, count(*) n,
             round(count(*)/count(DISTINCT trip_date),0) trips_per_day,
             round(sum(emp_actual)/count(DISTINCT trip_date),0) seats_per_day,
             round(100.0*avg(on_time),2) ota
      FROM trips WHERE dayofweek(trip_date) BETWEEN 1 AND 5
      GROUP BY 1 ORDER BY seats_per_day DESC
    """)


@check
def c07_marshal():
    """V7: marshal_rating=0 sentinel (feedback F1 / dataquality HIGH-4)"""
    show("marshal distribution", """
      SELECT marshal_rating v, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),3) pct
      FROM fb GROUP BY 1 ORDER BY 1
    """)
    show("naive vs filtered mean, and zeros in the other 4 dims", """
      SELECT round(avg(marshal_rating),3) naive_avg,
             round(avg(marshal_rating) FILTER (WHERE marshal_rating>0),3) avg_excl_zero,
             count(*) FILTER (WHERE marshal_rating>0) n_real,
             count(*) FILTER (WHERE route_rating=0) route_zero,
             count(*) FILTER (WHERE driver_rating=0) driver_zero,
             count(*) FILTER (WHERE safety_rating=0) safety_zero
      FROM fb
    """)
    show("marshal rated vs actual_escort (the decisive test)", """
      SELECT t.actual_escort, count(*) n,
             count(*) FILTER (WHERE f.marshal_rating>0) marshal_rated,
             round(100.0*count(*) FILTER (WHERE f.marshal_rating>0)/count(*),2) pct
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY 1
    """)


@check
def c08_fb_coverage():
    """V8: feedback coverage by BU -- two definitions (feedback F2 vs dataquality HIGH-3)"""
    show("coverage: distinct rated trips vs raw fb rows", """
      WITH t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           r AS (SELECT business_unit, count(*) fb_rows, count(DISTINCT trip_id) rated_trips
                 FROM fb GROUP BY 1)
      SELECT t.business_unit, trips, fb_rows, rated_trips,
             round(100.0*fb_rows/trips,2) pct_rows_over_trips,
             round(100.0*rated_trips/trips,2) pct_trips_rated
      FROM t JOIN r USING (business_unit) ORDER BY pct_trips_rated
    """)
    show("detractor rate by BU, feedback-weighted vs trip-weighted", """
      WITH d AS (SELECT business_unit,
                        count(*) n,
                        100.0*count(*) FILTER (WHERE driver_rating<=2)/count(*) det
                 FROM fb GROUP BY 1),
           t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1)
      SELECT round(sum(d.det*d.n)/sum(d.n),4) det_feedback_wtd,
             round(sum(d.det*t.trips)/sum(t.trips),4) det_trip_wtd
      FROM d JOIN t USING (business_unit)
    """)


@check
def c09_trip_id_collisions():
    """V9: trip_id is not a PK (dataquality HIGH-1, crosstable F7)"""
    show("collision profile", """
      WITH d AS (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1)
      SELECT (SELECT count(*) FROM d) colliding_ids,
             (SELECT count(*) FROM trips) ride_rows,
             (SELECT count(DISTINCT trip_id) FROM trips) ride_distinct_ids,
             (SELECT count(*) FROM (SELECT trip_id, business_unit FROM trips
                                    GROUP BY 1,2 HAVING count(*)>1)) dup_on_id_bu
    """)
    show("fan-out damage: join on trip_id vs (trip_id, business_unit)", """
      SELECT 'USING(trip_id)' j, count(*) n, round(sum(b.trip_cost),2) tot
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id
      UNION ALL
      SELECT '(trip_id,BU)', count(*), round(sum(b.trip_cost),2)
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
    """)


@check
def c10_bill_money():
    """V10: gross / credits / net / OverHead (cost F2, F3; dataquality MEDIUM-6)"""
    show("the headline is three numbers", """
      SELECT round(sum(trip_cost),2) net_billed,
             round(sum(trip_cost) FILTER (WHERE trip_cost>0),2) gross_charges,
             round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credit_notes,
             count(*) FILTER (WHERE trip_cost<0) n_credits,
             round(sum(trip_cost) FILTER (WHERE trip_id_raw='OverHead'),2) overhead_lines,
             count(*) FILTER (WHERE trip_id_raw='OverHead') n_overhead,
             count(*) FILTER (WHERE trip_id_raw<>'OverHead') trip_rows
      FROM bill
    """)
    show("credits by month and owner", """
      SELECT cycle_month, count(*) n, round(sum(trip_cost),2) credit_value
      FROM bill WHERE trip_cost<0 GROUP BY 1 ORDER BY 1
    """)
    show("credit concentration", """
      SELECT business_unit, vendor_id, contract_name, count(*) n, round(sum(trip_cost),2) amt
      FROM bill WHERE trip_cost<0 GROUP BY 1,2,3 ORDER BY amt LIMIT 5
    """)
    show("does a plain CAST crash?", """
      SELECT count(*) n_overhead_rows, min(trip_cost) mn, max(trip_cost) mx,
             round(avg(trip_cost),2) avg_cost, count(DISTINCT office) offices,
             count(DISTINCT vendor_id) vendors
      FROM bill WHERE trip_id_raw='OverHead'
    """)


@check
def c11_zerokm():
    """V11: zero-km rows are fixed-rate contracts, not missing data (rule C)"""
    show("zero-km share overall", """
      SELECT count(*) n, count(*) FILTER (WHERE total_trip_km=0) zero_km,
             round(100.0*count(*) FILTER (WHERE total_trip_km=0)/count(*),2) pct_rows,
             round(100.0*sum(trip_cost) FILTER (WHERE total_trip_km=0)/sum(trip_cost),2) pct_spend
      FROM bill WHERE trip_id_raw<>'OverHead'
    """)
    show("zero-km by contract (top 12 by rows)", """
      SELECT contract_name, count(*) n,
             round(100.0*count(*) FILTER (WHERE total_trip_km=0)/count(*),2) pct_zero_km,
             round(sum(trip_cost),0) spend
      FROM bill WHERE trip_id_raw<>'OverHead'
      GROUP BY 1 ORDER BY n DESC LIMIT 12
    """)
    show("blended vs segmented cost-per-km", """
      WITH c AS (SELECT contract_name,
                        100.0*count(*) FILTER (WHERE total_trip_km=0)/count(*) pz
                 FROM bill WHERE trip_id_raw<>'OverHead' GROUP BY 1)
      SELECT round(sum(b.trip_cost)/nullif(sum(b.total_trip_km),0),2) blended_cpk_all,
             round(sum(b.trip_cost) FILTER (WHERE c.pz<=20)/
                   nullif(sum(b.total_trip_km) FILTER (WHERE c.pz<=20),0),2) distance_only_cpk
      FROM bill b JOIN c USING (contract_name) WHERE b.trip_id_raw<>'OverHead' AND b.trip_cost>=0
    """)


@check
def c12_bus_orrnew():
    """V12: BUS-ORRNEW-TT vendor price spread at one office (cost F1)"""
    show("BUS-ORRNEW-TT by office x vendor (n>=500)", """
      SELECT office, vendor_id, count(*) n, round(avg(trip_cost),2) avg_cost,
             round(median(trip_cost),2) med_cost, round(sum(trip_cost),2) spend,
             round(avg(total_trip_km),2) avg_km
      FROM bill WHERE contract_name='BUS-ORRNEW-TT' AND trip_cost>0
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY avg_cost DESC
    """)
    show("contract shape", """
      SELECT count(*) n, count(DISTINCT slab_name) n_slab_labels,
             count(DISTINCT office) offices, count(DISTINCT vendor_id) vendors,
             round(avg(total_trip_km),3) avg_km
      FROM bill WHERE contract_name='BUS-ORRNEW-TT'
    """)


@check
def c13_notboarded():
    """V13: no-show label vs boarding_status by BU (employees F3, dataquality MEDIUM-9)"""
    show("two definitions", """
      SELECT count(*) n,
             round(100.0*count(*) FILTER (WHERE boarding_status='Not Boarded')/count(*),3) not_boarded_rate,
             round(100.0*count(*) FILTER (WHERE lower(CAST(is_no_show AS VARCHAR))='true')/count(*),3) noshow_flag_rate,
             count(*) FILTER (WHERE not_boarding_reason='TRIP_CANCELLED_FROM_DASHBOARD') n_cancelled
      FROM emp
    """)
    show("by BU -- the league table flips", """
      SELECT business_unit, count(*) n,
             round(100.0*count(*) FILTER (WHERE lower(CAST(is_no_show AS VARCHAR))='true')/count(*),2) noshow_label,
             round(100.0*count(*) FILTER (WHERE not_boarding_reason='TRIP_CANCELLED_FROM_DASHBOARD')/count(*),2) cancel_label,
             round(100.0*count(*) FILTER (WHERE boarding_status='Not Boarded')/count(*),2) not_boarded
      FROM emp GROUP BY 1 ORDER BY not_boarded DESC
    """)


@check
def c14_rider_ota():
    """V14: rider-level pickup OTA vs trip OTA (employees F2, crosstable F1)"""
    show("rider pickup OTA by month", """
      SELECT month, count(*) n_legs,
             round(100.0*avg(CASE WHEN (actual_pickup_epoch-planned_pickup_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) rider_pickup_ota,
             round(100.0*avg(CASE WHEN (actual_drop_epoch-planned_drop_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) rider_drop_ota,
             round(100.0*avg(CASE WHEN (actual_drop_epoch-planned_drop_epoch)/60.0>15 THEN 1 ELSE 0 END),2) drop_gt15
      FROM emp
      WHERE actual_pickup_epoch IS NOT NULL AND planned_pickup_epoch IS NOT NULL
        AND actual_drop_epoch IS NOT NULL AND planned_drop_epoch IS NOT NULL
      GROUP BY 1 ORDER BY 1
    """)
    show("LOGOUT drop lateness vs trip OTA -- the gap (direction comes from trips)", """
      SELECT t.trip_direction, e.month, count(*) n,
             round(100.0*avg(CASE WHEN (e.actual_drop_epoch-e.planned_drop_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) drop_le5,
             round(100.0*avg(CASE WHEN (e.actual_drop_epoch-e.planned_drop_epoch)/60.0>15 THEN 1 ELSE 0 END),2) drop_gt15,
             round(100.0*avg(CASE WHEN (e.actual_drop_epoch-e.planned_drop_epoch)/60.0>30 THEN 1 ELSE 0 END),2) drop_gt30
      FROM emp e JOIN trips t USING (trip_id, business_unit)
      WHERE e.actual_drop_epoch IS NOT NULL AND e.planned_drop_epoch IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("trip OTA by direction/month for comparison", """
      SELECT trip_direction, month, count(*) n, round(100.0*avg(on_time),2) trip_ota
      FROM trips GROUP BY 1,2 ORDER BY 1,2
    """)


@check
def c15_logout_speed():
    """V15: LOGOUT plans assume a speed that doesn't exist (employees F1)"""
    show("planned vs actual in-cab minutes by direction x month", """
      SELECT t.trip_direction, e.month, count(*) n,
             round(avg((e.planned_drop_epoch-e.planned_pickup_epoch)/60.0),2) planned_min,
             round(avg((e.actual_drop_epoch-e.actual_pickup_epoch)/60.0),2) actual_min,
             round(avg((e.actual_drop_epoch-e.actual_pickup_epoch)/60.0)
                 - avg((e.planned_drop_epoch-e.planned_pickup_epoch)/60.0),2) overrun
      FROM emp e JOIN trips t USING (trip_id, business_unit)
      WHERE e.planned_pickup_epoch IS NOT NULL AND e.actual_pickup_epoch IS NOT NULL
        AND e.planned_drop_epoch IS NOT NULL AND e.actual_drop_epoch IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("implied speed by direction", """
      SELECT t.trip_direction, count(*) n,
             round(avg(e.planned_km),2) avg_planned_km,
             round(avg(e.planned_km)/(avg((e.planned_drop_epoch-e.planned_pickup_epoch)/3600.0)),1) planned_kmh,
             round(avg(e.planned_km)/(avg((e.actual_drop_epoch-e.actual_pickup_epoch)/3600.0)),1) actual_kmh
      FROM emp e JOIN trips t USING (trip_id, business_unit)
      WHERE e.planned_pickup_epoch IS NOT NULL AND e.actual_pickup_epoch IS NOT NULL
        AND e.planned_drop_epoch IS NOT NULL AND e.actual_drop_epoch IS NOT NULL
      GROUP BY 1 ORDER BY 1
    """)
    show("single-rider LOGOUT control (no co-passenger waiting possible)", """
      SELECT t.trip_direction, e.month, count(*) n,
             round(avg((e.planned_drop_epoch-e.planned_pickup_epoch)/60.0),2) planned_min,
             round(avg((e.actual_drop_epoch-e.actual_pickup_epoch)/60.0),2) actual_min,
             round(avg((e.actual_drop_epoch-e.actual_pickup_epoch)/60.0)
                 - avg((e.planned_drop_epoch-e.planned_pickup_epoch)/60.0),2) overrun
      FROM emp e JOIN trips t USING (trip_id, business_unit)
      WHERE t.emp_actual=1 AND e.planned_pickup_epoch IS NOT NULL AND e.actual_pickup_epoch IS NOT NULL
        AND e.planned_drop_epoch IS NOT NULL AND e.actual_drop_epoch IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)


@check
def c16_alerts_autoclose():
    """V16: 24h auto-close cluster, severity='NA' marker (safety HIGH-1)"""
    show("ack latency buckets", """
      WITH a AS (SELECT *, date_diff('minute', start_time, ack_time) m FROM alerts)
      SELECT CASE WHEN ack_time IS NULL THEN 'never'
                  WHEN m<=5 THEN 'a <=5m' WHEN m<=15 THEN 'b 6-15m'
                  WHEN m<=60 THEN 'c 16-60m' WHEN m<=600 THEN 'd 1-10h'
                  WHEN m<1434 THEN 'e 10-23.9h'
                  WHEN m<=1452 THEN 'f 23.9-24.2h <-- spike'
                  ELSE 'g >24.2h' END bucket,
             count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
      FROM a GROUP BY 1 ORDER BY 1
    """)
    show("severity distribution + autoclose share", """
      WITH a AS (SELECT *, date_diff('minute', start_time, ack_time) m FROM alerts)
      SELECT severity, count(*) n,
             count(*) FILTER (WHERE m BETWEEN 1434 AND 1452) in_24h_cluster,
             round(100.0*count(*) FILTER (WHERE m BETWEEN 1434 AND 1452)/count(*),2) pct_autoclosed
      FROM a GROUP BY 1 ORDER BY n DESC
    """)
    show("autoclose by BU", """
      WITH a AS (SELECT *, date_diff('minute', start_time, ack_time) m FROM alerts)
      SELECT business_unit, count(*) n_alerts,
             count(*) FILTER (WHERE m BETWEEN 1434 AND 1452) n_autoclosed,
             round(100.0*count(*) FILTER (WHERE m BETWEEN 1434 AND 1452)/count(*),2) pct
      FROM a GROUP BY 1 ORDER BY pct DESC
    """)
    show("catalyst-Sac geofence: 100% autoclosed vs everyone else", """
      WITH a AS (SELECT *, date_diff('minute', start_time, ack_time) m FROM alerts)
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE m BETWEEN 1434 AND 1452) autoclosed,
             round(100.0*count(*) FILTER (WHERE m BETWEEN 1434 AND 1452)/count(*),2) pct,
             round(median(m),1) med_min
      FROM a WHERE event_type='EMPLOYEE_GEOFENCE_VIOLATION' GROUP BY 1 ORDER BY pct DESC
    """)


@check
def c17_signoff_cliff():
    """V17: EMPLOYEE_SIGN_OFF_TIME_VIOLATION dies on 2026-05-18 (safety HIGH-2, dataquality MEDIUM-7)"""
    show("daily counts around the cliff", """
      SELECT start_time::DATE d, count(*) n
      FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
        AND start_time::DATE BETWEEN '2026-05-12' AND '2026-05-22'
      GROUP BY 1 ORDER BY 1
    """)
    show("every other event type grows across the boundary", """
      SELECT event_type,
             count(*) FILTER (WHERE start_time::DATE < '2026-05-18') n_before,
             count(*) FILTER (WHERE start_time::DATE >= '2026-05-18') n_after,
             count(*) n
      FROM alerts GROUP BY 1 ORDER BY n DESC
    """)
    show("platform alert rate with and without sign-off", """
      SELECT date_trunc('month', a.start_time)::DATE mo,
             count(*) n_all,
             count(*) FILTER (WHERE event_type<>'EMPLOYEE_SIGN_OFF_TIME_VIOLATION') n_excl
      FROM alerts a GROUP BY 1 ORDER BY 1
    """)


@check
def c18_escort():
    """V18: escort coverage on female-last-drop night LOGOUT (safety HIGH-5, employees F5)"""
    con.sql("""
      CREATE OR REPLACE TEMP VIEW lastdrop AS
      SELECT trip_id, business_unit,
             arg_max(gender, actual_drop_epoch) last_gender
      FROM emp WHERE actual_drop_epoch IS NOT NULL AND emp_role<>'escort'
      GROUP BY 1,2
    """)
    show("female-last-drop night LOGOUT, % unescorted, by BU", """
      SELECT t.business_unit, count(*) n,
             count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t JOIN lastdrop l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB'
        AND l.last_gender='FEMALE'
        AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT) >= 19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT) <= 5)
      GROUP BY 1 ORDER BY pct_no_escort DESC
    """)
    show("escort rule keyed to shift start: the 19:00 cliff", """
      SELECT TRY_CAST(split_part(t.shift_type,':',1) AS INT) shift_hour,
             count(*) n_female_last_drop,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct_escort
      FROM trips t JOIN lastdrop l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND l.last_gender='FEMALE'
        AND t.shift_type LIKE '%:%'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1
    """)
    show("unescorted night LOGOUT trips whose last drop was female, by month", """
      SELECT t.month, count(*) unescorted_night_logout,
             count(*) FILTER (WHERE l.last_gender='FEMALE') last_drop_female,
             round(100.0*count(*) FILTER (WHERE l.last_gender='FEMALE')/count(*),3) pct
      FROM trips t JOIN lastdrop l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND NOT t.actual_escort
        AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT) >= 19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT) <= 5)
      GROUP BY 1 ORDER BY 1
    """)


@check
def c19_wta():
    """V19: WOMAN_TRAVELLING_ALONE detector coverage + rating impact (safety HIGH-4, crosstable F4)"""
    show("WTA alerts per 1000 trips by BU", """
      WITH t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           a AS (SELECT business_unit, count(*) wta FROM alerts
                 WHERE event_type='WOMAN_TRAVELLING_ALONE' GROUP BY 1)
      SELECT t.business_unit, trips, coalesce(wta,0) wta,
             round(1000.0*coalesce(wta,0)/trips,2) per_1k
      FROM t LEFT JOIN a USING (business_unit) ORDER BY per_1k DESC
    """)
    show("female share by BU (are those BUs womanless?)", """
      SELECT business_unit, count(*) n, count(*) FILTER (WHERE gender='FEMALE') female,
             round(100.0*count(*) FILTER (WHERE gender='FEMALE')/count(*),2) pct_female
      FROM emp GROUP BY 1 ORDER BY 1
    """)
    show("ratings on WTA-alerted trips vs baseline", """
      WITH wta AS (SELECT DISTINCT trip_id, business_unit FROM alerts
                   WHERE event_type='WOMAN_TRAVELLING_ALONE')
      SELECT CASE WHEN w.trip_id IS NULL THEN 'no WTA alert' ELSE 'WTA alerted' END g,
             count(*) n_ratings, round(avg(f.safety_rating),3) safety,
             round(100.0*count(*) FILTER (WHERE f.safety_rating<=3)/count(*),3) pct_safety_le3
      FROM fb f LEFT JOIN wta w USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY 1
    """)


@check
def c20_planned_km_drift():
    """V20: the one comma'd planned_km row that breaks the boilerplate (dataquality MEDIUM-10)"""
    show("rows where naive TRY_CAST(planned_km) NULLs but replace() works", """
      SELECT trip_id, business_unit, office, trip_date, planned_km, traveled_km
      FROM trips WHERE planned_km_naive IS NULL AND planned_km IS NOT NULL
    """)
    show("count", """
      SELECT count(*) FILTER (WHERE planned_km_naive IS NULL) naive_nulls,
             count(*) FILTER (WHERE planned_km IS NULL) fixed_nulls
      FROM trips
    """)


@check
def c21_noshow_seats():
    """V21: no-show seat value (crosstable F5)"""
    show("no-show seat value by month", """
      WITH j AS (
        SELECT t.month, t.noshow, t.emp_planned, b.trip_cost
        FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
        WHERE b.trip_cost>0 AND t.emp_planned>0)
      SELECT month, count(*) n, sum(noshow) seats_noshow,
             round(sum(trip_cost),0) spend,
             round(sum(trip_cost*noshow/emp_planned),0) noshow_seat_value,
             round(100.0*sum(trip_cost*noshow/emp_planned)/sum(trip_cost),2) pct_of_spend
      FROM j GROUP BY 1 ORDER BY 1
    """)
    show("by office (top 5)", """
      WITH j AS (
        SELECT t.business_unit, t.office, t.noshow, t.emp_planned, b.trip_cost
        FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
        WHERE b.trip_cost>0 AND t.emp_planned>0)
      SELECT business_unit, office, count(*) n, sum(noshow) seats,
             round(sum(trip_cost*noshow/emp_planned),0) noshow_seat_value,
             round(100.0*sum(trip_cost*noshow/emp_planned)/sum(trip_cost),2) pct_of_spend
      FROM j GROUP BY 1,2 ORDER BY noshow_seat_value DESC LIMIT 5
    """)
    show("does a no-show cost extra rupees? control for contract", """
      WITH j AS (
        SELECT b.contract_name, t.noshow, b.trip_cost
        FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
        WHERE b.trip_cost>0)
      SELECT contract_name, count(*) n,
             round(avg(trip_cost) FILTER (WHERE noshow=0),2) cost_no_ns,
             count(*) FILTER (WHERE noshow>0) n_ns,
             round(avg(trip_cost) FILTER (WHERE noshow>0),2) cost_ns,
             round(avg(trip_cost) FILTER (WHERE noshow>0)-avg(trip_cost) FILTER (WHERE noshow=0),2) delta
      FROM j GROUP BY 1 HAVING count(*) FILTER (WHERE noshow>0)>=500
      ORDER BY n DESC LIMIT 10
    """)


@check
def c22_meera_lebedev():
    """V22: the one genuinely bad vendor (crosstable F6)"""
    show("Meera Lebedev Travel vs same office+month peers", """
      WITH j AS (SELECT t.*, b.trip_cost, b.contract_name
                 FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
                 WHERE b.trip_cost>0),
           peer AS (SELECT business_unit, office, month, avg(on_time) peer_ota FROM j GROUP BY 1,2,3)
      SELECT j.vendor_id, count(*) n, round(100.0*avg(j.on_time),2) ota_vendor,
             round(100.0*avg(p.peer_ota),2) peer_ota, round(100.0*(avg(j.on_time)-avg(p.peer_ota)),2) gap,
             round(avg(j.trip_cost)/avg(j.emp_actual),2) cost_per_rider,
             round(100.0*avg(j.emp_actual*1.0/nullif(j.cab_capacity,0)),1) occ_pct
      FROM j JOIN peer p USING (business_unit, office, month)
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY gap LIMIT 6
    """)
    show("Meera Lebedev by month", """
      SELECT t.month, count(*) n, round(100.0*avg(t.on_time),2) ota,
             any_value(b.contract_name) contract, any_value(t.office) office,
             round(avg(t.emp_actual),2) riders, round(avg(t.cab_capacity),2) cap,
             round(sum(b.trip_cost),0) spend
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
      WHERE t.vendor_id='Meera Lebedev Travel' AND b.trip_cost>0
      GROUP BY 1 ORDER BY 1
    """)
    show("alerts per 1000 trips by vendor (n>=1000)", """
      WITH t AS (SELECT vendor_id, count(*) trips FROM trips GROUP BY 1),
           a AS (SELECT t.vendor_id, count(*) al FROM alerts x
                 JOIN trips t ON x.trip_id=t.trip_id AND x.business_unit=t.business_unit GROUP BY 1)
      SELECT t.vendor_id, trips, coalesce(al,0) alerts, round(1000.0*coalesce(al,0)/trips,2) per_1k
      FROM t LEFT JOIN a USING (vendor_id) WHERE trips>=1000 ORDER BY per_1k DESC LIMIT 5
    """)


@check
def c23_solo():
    """V23: planned-solo rate inside one BU on one fleet (timeliness M2)"""
    show("pinnacle-Slc: same BU, same 3-seat fleet, 2.3x the solo rate", """
      SELECT business_unit, office, count(*) n,
             round(100.0*avg(CASE WHEN cab_capacity=3 THEN 1 ELSE 0 END),2) pct_cap3,
             round(100.0*avg(CASE WHEN emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
             round(avg(emp_planned),2) mean_planned_riders,
             round(100.0*avg(emp_actual*1.0/nullif(cab_capacity,0)),2) seat_fill
      FROM trips WHERE business_unit='pinnacle-Slc'
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY pct_planned_solo DESC
    """)


@check
def c24_slab_labels():
    """V24: slab_name label fragmentation (dataquality HIGH-5)"""
    show("raw vs normalised label count", """
      SELECT count(DISTINCT slab_name) raw_labels,
             count(DISTINCT upper(replace(replace(replace(
               regexp_replace(slab_name,'^Slab[- ]?','') ,' ',''),'-',''),'_',''))) normalised_labels
      FROM bill
    """)
    show("labels that collapse to the same slab", """
      WITH n AS (SELECT slab_name,
                        upper(replace(replace(replace(
                          regexp_replace(slab_name,'^Slab[- ]?','') ,' ',''),'-',''),'_','')) norm,
                        trip_cost FROM bill)
      SELECT norm, count(DISTINCT slab_name) raw_variants,
             string_agg(DISTINCT slab_name, ',') variants,
             count(*) n, round(sum(trip_cost),0) amt
      FROM n GROUP BY 1 HAVING count(DISTINCT slab_name)>1 ORDER BY n DESC
    """)
    show("string sentinels, not SQL NULL", """
      SELECT count(*) FILTER (WHERE slab_name IS NULL) sql_null,
             count(*) FILTER (WHERE slab_name='null') str_null,
             count(*) FILTER (WHERE slab_name='NA') str_na,
             count(*) FILTER (WHERE slab_name='0') str_zero
      FROM bill
    """)


@check
def c25_outage():
    """V25: the 2026-05-28 multi-file outage and the 2026-06-01 feedback-only outage"""
    show("pinnacle-Slc daily rows across 4 files", """
      WITH r AS (SELECT trip_date d, count(*) ride FROM trips WHERE business_unit='pinnacle-Slc' GROUP BY 1),
           e AS (SELECT trip_date d, count(*) emp FROM emp WHERE business_unit='pinnacle-Slc' GROUP BY 1),
           f AS (SELECT creation_time::DATE d, count(*) fb FROM fb WHERE business_unit='pinnacle-Slc' GROUP BY 1),
           a AS (SELECT start_time::DATE d, count(*) al FROM alerts WHERE business_unit='pinnacle-Slc' GROUP BY 1)
      SELECT r.d, ride, emp, fb, al FROM r
      LEFT JOIN e USING (d) LEFT JOIN f USING (d) LEFT JOIN a USING (d)
      WHERE r.d BETWEEN '2026-05-26' AND '2026-06-02' ORDER BY 1
    """)
    show("feedback coverage by day around 2026-06-01", """
      WITH t AS (SELECT trip_date d, count(*) trips FROM trips GROUP BY 1),
           f AS (SELECT trip_date d, count(DISTINCT t.trip_id) rated
                 FROM trips t WHERE EXISTS (SELECT 1 FROM fb WHERE fb.trip_id=t.trip_id
                                            AND fb.business_unit=t.business_unit) GROUP BY 1)
      SELECT t.d, trips, coalesce(rated,0) rated, round(100.0*coalesce(rated,0)/trips,2) coverage_pct
      FROM t LEFT JOIN f USING (d) WHERE t.d BETWEEN '2026-05-26' AND '2026-06-03' ORDER BY 1
    """)


@check
def c26_ratings_vs_delay():
    """V26: mean rating is dead, detractor rate is the sensitive metric (feedback F5)"""
    show("monthly route rating vs detractor rate", """
      SELECT date_trunc('month', creation_time)::DATE mo, count(*) n,
             round(avg(route_rating),4) route_mean,
             round(100.0*count(*) FILTER (WHERE route_rating=5)/count(*),3) pct_5star,
             round(100.0*count(*) FILTER (WHERE route_rating<=2)/count(*),3) det_pct,
             count(*) FILTER (WHERE route_rating<=2) n_detractors
      FROM fb WHERE creation_time < '2026-08-01' GROUP BY 1 ORDER BY 1
    """)
    show("corr(delay_minutes, rating) at trip level", """
      SELECT count(*) n,
             round(corr(t.delay_minutes, f.driver_rating),5) corr_driver,
             round(corr(t.delay_minutes, f.route_rating),5) corr_route,
             round(corr(t.delay_minutes, f.cab_rating),5) corr_cab
      FROM fb f JOIN trips t USING (trip_id, business_unit)
    """)
    show("rating dimension inter-correlation (halo)", """
      SELECT round(corr(route_rating,driver_rating),4) route_driver,
             round(corr(driver_rating,cab_rating),4) driver_cab,
             round(corr(driver_rating,safety_rating),4) driver_safety,
             round(corr(cab_rating,safety_rating),4) cab_safety
      FROM fb
    """)


@check
def c27_ota_vs_csat():
    """V27: OTA and satisfaction are decoupled (feedback F3)"""
    show("BU: objective OTA vs detractor rate", """
      WITH t AS (SELECT business_unit, count(*) trips, 100.0*avg(on_time) ota FROM trips GROUP BY 1),
           f AS (SELECT business_unit, count(*) fb_rows,
                        100.0*count(*) FILTER (WHERE driver_rating<=2)/count(*) driver_det,
                        100.0*count(*) FILTER (WHERE route_rating<=2)/count(*) route_det
                 FROM fb GROUP BY 1)
      SELECT t.business_unit, trips, round(ota,2) objective_ota, fb_rows,
             round(100.0*fb_rows/trips,2) fb_rows_per_100_trips,
             round(driver_det,3) driver_det_pct, round(route_det,3) route_det_pct
      FROM t JOIN f USING (business_unit) ORDER BY ota DESC
    """)


@check
def c28_billing_recon():
    """V28: unbilled rides rising (cost supporting)"""
    show("rides never billed, by month", """
      SELECT t.month, count(*) n
      FROM trips t LEFT JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
      WHERE b.trip_id IS NULL GROUP BY 1 ORDER BY 1
    """)
    show("bill rows with no ride", """
      SELECT count(*) n, round(sum(b.trip_cost),2) amt
      FROM bill b LEFT JOIN trips t ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
      WHERE t.trip_id IS NULL AND b.trip_id_raw<>'OverHead'
    """)
    show("zero-cost bill rows and their slab", """
      SELECT count(*) zero_cost_rows,
             count(*) FILTER (WHERE slab_name IN ('null','NA','0')) with_null_slab,
             round(100.0*count(*) FILTER (WHERE slab_name IN ('null','NA','0'))/count(*),2) pct
      FROM bill WHERE trip_cost=0
    """)


@check
def c29_dead_columns():
    """V29: is_driver_nc / is_cab_nc -- dead in ride? (timeliness DQ1 vs safety MEDIUM-7 CONTRADICTION)"""
    show("is_driver_nc / is_cab_nc raw value distribution", """
      SELECT is_driver_nc, count(*) n FROM trips GROUP BY 1 ORDER BY n DESC
    """)
    show("is_cab_nc", """
      SELECT is_cab_nc, count(*) n FROM trips GROUP BY 1 ORDER BY n DESC
    """)
    show("driver-NC concentration by BU x vendor", """
      SELECT business_unit, vendor_id, count(*) n,
             count(*) FILTER (WHERE is_driver_nc) nc,
             round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) drv_nc_pct
      FROM trips GROUP BY 1,2 HAVING count(*) FILTER (WHERE is_driver_nc)>0
      ORDER BY drv_nc_pct DESC LIMIT 8
    """)


@check
def c30_route_source():
    """V30: SHUTTLE_SERVICE reclassification in July (timeliness DQ2)"""
    show("route_source by month", """
      SELECT route_source, count(*) FILTER (WHERE month='2026-05-01') may,
             count(*) FILTER (WHERE month='2026-06-01') jun,
             count(*) FILTER (WHERE month='2026-07-01') jul, count(*) n
      FROM trips GROUP BY 1 ORDER BY n DESC
    """)
    show("Denver Office BUS: MANUAL falls exactly as SHUTTLE_SERVICE appears", """
      SELECT month, route_source, count(*) n
      FROM trips WHERE office='Denver Office' AND product_type='BUS'
        AND route_source IN ('MANUAL','SHUTTLE_SERVICE')
      GROUP BY 1,2 ORDER BY 2,1
    """)


def main():
    build()
    args = sys.argv[1:]
    names = args if args else list(CHECKS)
    for nm in names:
        matches = [k for k in CHECKS if k == nm or k.split('_', 1)[1] == nm or k.startswith(nm)]
        if not matches:
            print(f"!! no such check: {nm}")
            continue
        for m in matches:
            print(f"\n{'='*78}\n== {m}: {CHECKS[m].__doc__}\n{'='*78}")
            try:
                CHECKS[m]()
            except Exception as e:
                print(f"!! FAILED {m}: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()
