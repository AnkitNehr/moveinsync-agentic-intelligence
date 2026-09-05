#!/usr/bin/env python
"""
SAFETY & COMPLIANCE -- round 2: artifact checks on every round-1 finding.
Every number printed is raw query output.
"""
import duckdb, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")
con = duckdb.connect()
con.sql("SET threads TO 8")

con.sql(f"""CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes,
  TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
  TRY_CAST(is_driver_nc AS BOOLEAN) AS is_driver_nc,
  TRY_CAST(is_cab_nc AS BOOLEAN) AS is_cab_nc,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
  TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(noshow_cnt AS INT) AS noshow,
  TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT) AS actual_start_epoch,
  TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour,
  CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW alerts AS SELECT
  business_unit,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  event_id, event_type,
  strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_ts,
  strptime(acknowledge_time,'%B %d, %Y, %I:%M %p') AS ack_ts,
  state_text, severity, source,
  strptime(start_time,'%B %d, %Y, %I:%M %p')::DATE AS start_date,
  date_trunc('month', strptime(start_time,'%B %d, %Y, %I:%M %p'))::DATE AS month,
  hour(strptime(start_time,'%B %d, %Y, %I:%M %p')) AS start_hour,
  date_diff('minute', strptime(start_time,'%B %d, %Y, %I:%M %p'),
                      strptime(acknowledge_time,'%B %d, %Y, %I:%M %p')) AS ack_min
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW emp AS SELECT
  business_unit, office, product_type, trip_date::DATE AS trip_date, shift_type,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  gender, emp_role, boarding_status, not_boarding_reason,
  TRY_CAST(is_no_show AS BOOLEAN) AS is_no_show,
  TRY_CAST(actual_pickup_epoch AS DOUBLE) AS actual_pickup_epoch,
  TRY_CAST(actual_drop_epoch AS DOUBLE) AS actual_drop_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour
FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)""")

W = 118
def hdr(t):
    print("\n" + "=" * W); print(t); print("=" * W)

def p(title, q):
    print("\n### " + title)
    print("    " + q.strip().replace("\n", "\n    "))
    r = con.sql(q); cols = r.columns; rows = r.fetchall()
    wid = [len(str(c)) for c in cols]
    srows = [[("" if v is None else str(v)) for v in row] for row in rows]
    for row in srows:
        for i, v in enumerate(row): wid[i] = max(wid[i], len(v))
    print("  " + " | ".join(str(c).ljust(wid[i]) for i, c in enumerate(cols)))
    print("  " + "-+-".join("-" * w for w in wid))
    for row in srows:
        print("  " + " | ".join(v.ljust(wid[i]) for i, v in enumerate(row)))
    print(f"  [{len(rows)} rows]")

# ============================================================ A. 24h auto-close
hdr("A. IS THE ~1440-MINUTE ACK CLUSTER AN AUTO-CLOSE? (artifact check on 'ack SLA')")
p("latency histogram in coarse buckets", """
SELECT CASE WHEN ack_min IS NULL THEN 'never'
  WHEN ack_min<=5 THEN 'a <=5m' WHEN ack_min<=15 THEN 'b 6-15m'
  WHEN ack_min<=60 THEN 'c 16-60m' WHEN ack_min<=600 THEN 'd 1-10h'
  WHEN ack_min<1435 THEN 'e 10-23.9h'
  WHEN ack_min<=1450 THEN 'f 23.9-24.2h  <-- suspicious spike'
  ELSE 'g >24.2h' END bucket,
  count(*) n, round(100.0*count(*)/(SELECT count(*) FROM alerts),2) pct
FROM alerts GROUP BY 1 ORDER BY 1
""")
p("PROOF: does ack time-of-day equal start time-of-day for the 1435-1450 group?", """
SELECT count(*) n,
  count(*) FILTER (WHERE ack_ts::DATE = start_ts::DATE + INTERVAL 1 DAY) AS ack_next_day,
  round(avg(abs(date_diff('minute', start_ts, ack_ts) - 1440)),2) AS avg_abs_dev_from_exactly_24h,
  min(ack_min) AS min_lat, max(ack_min) AS max_lat
FROM alerts WHERE ack_min BETWEEN 1435 AND 1450
""")
p("severity x 24h-cluster crosstab -- is severity='NA' the auto-close marker?", """
SELECT severity, count(*) n,
  count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS in_24h_cluster,
  round(100.0*count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500)/count(*),2) pct_autoclosed
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("flip it: what is inside the 24h cluster?", """
SELECT severity, event_type, business_unit, count(*) n
FROM alerts WHERE ack_min BETWEEN 1400 AND 1500 GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 12
""")
p("HUMAN-TRIAGED ONLY (exclude 24h auto-close): real ack latency by severity", """
SELECT severity, count(*) n,
  round(median(ack_min),2) med, round(quantile_cont(ack_min,0.90),2) p90,
  round(quantile_cont(ack_min,0.99),2) p99, max(ack_min) AS mx,
  round(100.0*count(*) FILTER (WHERE ack_min>15)/count(*),2) pct_gt15m
FROM alerts WHERE ack_min IS NOT NULL AND ack_min NOT BETWEEN 1400 AND 1500
GROUP BY 1 ORDER BY 2 DESC
""")
p("HEADLINE: auto-close (untriaged) share by BU x month", """
SELECT business_unit,
  round(100.0*count(*) FILTER (WHERE month='2026-05-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-05-01'),0),2) AS may_pct,
  round(100.0*count(*) FILTER (WHERE month='2026-06-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-06-01'),0),2) AS jun_pct,
  round(100.0*count(*) FILTER (WHERE month='2026-07-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-07-01'),0),2) AS jul_pct,
  count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS n_autoclosed, count(*) AS n_alerts
FROM alerts GROUP BY 1 ORDER BY 6 DESC
""")
p("ARTIFACT CHECK: same, EXCLUDING the SIGN_OFF flood (is pinnacle really fixed?)", """
SELECT business_unit,
  round(100.0*count(*) FILTER (WHERE month='2026-05-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-05-01'),0),2) AS may_pct,
  round(100.0*count(*) FILTER (WHERE month='2026-06-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-06-01'),0),2) AS jun_pct,
  round(100.0*count(*) FILTER (WHERE month='2026-07-01' AND ack_min BETWEEN 1400 AND 1500)
        /nullif(count(*) FILTER (WHERE month='2026-07-01'),0),2) AS jul_pct,
  count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS n_autoclosed, count(*) AS n_alerts
FROM alerts WHERE event_type<>'EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
GROUP BY 1 ORDER BY 6 DESC
""")
p("catalyst-Sac auto-close by event_type (is it one detector or all?)", """
SELECT event_type, count(*) n, count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS autoclosed,
  round(100.0*count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500)/count(*),2) pct
FROM alerts WHERE business_unit='catalyst-Sac' GROUP BY 1 ORDER BY 2 DESC
""")
p("GEOFENCE auto-close by BU (is catalyst uniquely bad or is the detector itself untriaged?)", """
SELECT business_unit, count(*) n, count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS autoclosed,
  round(100.0*count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500)/count(*),2) pct,
  round(median(ack_min),1) med_min
FROM alerts WHERE event_type='EMPLOYEE_GEOFENCE_VIOLATION' GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================================ B. detector coverage
hdr("B. DETECTOR COVERAGE MATRIX -- are BUs even running the same alert catalogue?")
p("event_type x BU, alerts per 1000 trips (0.000 = detector appears OFF)", """
WITH tv AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1)
SELECT a.event_type,
  round(1000.0*count(*) FILTER (WHERE a.business_unit='pinnacle-Slc')/(SELECT trips FROM tv WHERE business_unit='pinnacle-Slc'),2) AS pinnacle_Slc,
  round(1000.0*count(*) FILTER (WHERE a.business_unit='vanta-Sea')/(SELECT trips FROM tv WHERE business_unit='vanta-Sea'),2) AS vanta_Sea,
  round(1000.0*count(*) FILTER (WHERE a.business_unit='vanta-Aus')/(SELECT trips FROM tv WHERE business_unit='vanta-Aus'),2) AS vanta_Aus,
  round(1000.0*count(*) FILTER (WHERE a.business_unit='catalyst-Sac')/(SELECT trips FROM tv WHERE business_unit='catalyst-Sac'),2) AS catalyst_Sac,
  round(1000.0*count(*) FILTER (WHERE a.business_unit='orbit-Slc')/(SELECT trips FROM tv WHERE business_unit='orbit-Slc'),2) AS orbit_Slc
FROM alerts a GROUP BY 1 ORDER BY 1
""")
p("count of detectors with ZERO alerts, per BU (out of 10 real event types)", """
WITH g AS (SELECT business_unit, event_type, count(*) n FROM alerts GROUP BY 1,2),
     bu AS (SELECT DISTINCT business_unit FROM trips),
     et AS (SELECT DISTINCT event_type FROM alerts WHERE event_type<>'SUPPLEMENTARY_ALERT')
SELECT bu.business_unit, count(*) FILTER (WHERE g.n IS NULL) AS detectors_silent,
  count(*) AS detectors_possible,
  (SELECT count(*) FROM trips t WHERE t.business_unit=bu.business_unit) AS trips
FROM bu CROSS JOIN et LEFT JOIN g ON g.business_unit=bu.business_unit AND g.event_type=et.event_type
GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================================ C. escort semantics
hdr("C. ESCORT FLAG SEMANTICS -- does actualemployee_cnt include the escort?")
p("emp_actual distribution by escort flag (CAB only)", """
SELECT actual_escort, count(*) n, min(emp_actual) AS mn, max(emp_actual) AS mx,
  round(avg(emp_actual),3) AS avg_emp,
  count(*) FILTER (WHERE emp_actual=1) AS emp_eq1,
  count(*) FILTER (WHERE emp_actual=0) AS emp_eq0
FROM trips WHERE product_type='CAB' GROUP BY 1 ORDER BY 2 DESC
""")
p("GROUND TRUTH from emp_Data: does the escort appear as an emp_role row?", """
SELECT emp_role, count(*) n, count(DISTINCT trip_id) trips FROM emp GROUP BY 1 ORDER BY 2 DESC
""")
p("emp_Data gender distribution + no-show", """
SELECT gender, count(*) n, count(*) FILTER (WHERE is_no_show) AS noshow,
  round(100.0*count(*) FILTER (WHERE is_no_show)/count(*),2) pct_noshow
FROM emp GROUP BY 1 ORDER BY 2 DESC
""")
p("CROSS-CHECK: emp_Data rows per trip vs ride actualemployee_cnt, split by escort", """
WITH e AS (SELECT trip_id, count(*) rows_in_emp,
             count(*) FILTER (WHERE emp_role<>'employee') AS non_employee_rows
           FROM emp GROUP BY 1)
SELECT t.actual_escort, count(*) trips,
  round(avg(t.emp_actual),3) AS avg_ride_emp_cnt,
  round(avg(e.rows_in_emp),3) AS avg_emp_data_rows,
  round(avg(e.non_employee_rows),3) AS avg_non_employee_rows
FROM trips t JOIN e USING (trip_id) WHERE t.product_type='CAB'
GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================================ D. WTA ground truth
hdr("D. WOMAN-ALONE: ALERT vs GROUND TRUTH FROM emp_Data.gender")
p("WTA alert: what shift_hour are the underlying trips? (alert clock-hour != shift hour)", """
SELECT t.shift_hour, count(*) AS wta_alerts,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) pct_escort,
  count(DISTINCT t.trip_id) trips
FROM alerts a JOIN trips t USING (trip_id)
WHERE a.event_type='WOMAN_TRAVELLING_ALONE' GROUP BY 1 ORDER BY 2 DESC LIMIT 15
""")
p("GROUND TRUTH: trips where the ONLY boarded employee is FEMALE (all BUs, CAB)", """
WITH b AS (SELECT trip_id, count(*) n_boarded,
             count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT t.business_unit, count(*) AS solo_female_trips,
  count(*) FILTER (WHERE t.actual_escort) AS escorted,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) pct_escorted
FROM trips t JOIN b USING (trip_id)
WHERE t.product_type='CAB' AND b.n_boarded=1 AND b.n_female=1
GROUP BY 1 ORDER BY 2 DESC
""")
p("HEADLINE: solo-female trips by clock hour of actual drop, escort rate", """
WITH b AS (SELECT trip_id, count(*) n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT hour(to_timestamp(t.actual_end_epoch)) AS drop_hour, count(*) AS solo_female_trips,
  count(*) FILTER (WHERE t.actual_escort) AS escorted,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) pct_escorted
FROM trips t JOIN b USING (trip_id)
WHERE t.product_type='CAB' AND b.n_boarded=1 AND b.n_female=1 AND t.actual_end_epoch IS NOT NULL
GROUP BY 1 ORDER BY 1
""")
p("SAME for solo-MALE trips (control: is low escort female-specific or universal?)", """
WITH b AS (SELECT trip_id, count(*) n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT CASE WHEN b.n_female=1 THEN 'solo FEMALE' ELSE 'solo MALE' END grp,
  CASE WHEN hour(to_timestamp(t.actual_end_epoch)) >= 21
         OR hour(to_timestamp(t.actual_end_epoch)) <= 5 THEN 'night drop(21-05)'
       ELSE 'day drop(06-20)' END band,
  count(*) n, count(*) FILTER (WHERE t.actual_escort) AS escorted,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) pct_escorted
FROM trips t JOIN b USING (trip_id)
WHERE t.product_type='CAB' AND b.n_boarded=1 AND t.actual_end_epoch IS NOT NULL
GROUP BY 1,2 ORDER BY 1,2
""")
p("HEADLINE: solo-female NIGHT drops with NO escort, by BU (the actionable list)", """
WITH b AS (SELECT trip_id, count(*) n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT t.business_unit, count(*) AS solo_female_night_drops,
  count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort,
  count(*) FILTER (WHERE a.trip_id IS NOT NULL) AS had_wta_alert
FROM trips t JOIN b USING (trip_id)
LEFT JOIN (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE') a
  ON a.trip_id=t.trip_id
WHERE t.product_type='CAB' AND b.n_boarded=1 AND b.n_female=1
  AND t.actual_end_epoch IS NOT NULL
  AND (hour(to_timestamp(t.actual_end_epoch))>=21 OR hour(to_timestamp(t.actual_end_epoch))<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("ALERT RECALL: of all solo-female CAB trips, what share generated a WTA alert? by BU", """
WITH b AS (SELECT trip_id, count(*) n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT t.business_unit, count(*) AS solo_female_trips,
  count(*) FILTER (WHERE a.trip_id IS NOT NULL) AS with_wta_alert,
  round(100.0*count(*) FILTER (WHERE a.trip_id IS NOT NULL)/count(*),2) pct_alerted
FROM trips t JOIN b USING (trip_id)
LEFT JOIN (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE') a
  ON a.trip_id=t.trip_id
WHERE t.product_type='CAB' AND b.n_boarded=1 AND b.n_female=1
GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: female share of workforce by BU (is catalyst/orbit just all-male?)", """
SELECT business_unit, count(*) n,
  count(*) FILTER (WHERE gender='FEMALE') AS female,
  round(100.0*count(*) FILTER (WHERE gender='FEMALE')/count(*),2) pct_female,
  count(DISTINCT stwid) distinct_emp
FROM emp GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================================ E. repeat employees
hdr("E. WTA REPEAT EMPLOYEES -- routing problem or just high travellers?")
p("normalise: WTA alerts per 100 trips for the top repeat employees (vanta-Sea)", """
WITH w AS (SELECT stwid, count(*) wta FROM alerts
           WHERE event_type='WOMAN_TRAVELLING_ALONE' AND stwid<>0 GROUP BY 1),
     e AS (SELECT stwid, count(*) trips FROM emp WHERE business_unit='vanta-Sea' GROUP BY 1)
SELECT CASE WHEN w.wta>=20 THEN 'a >=20 WTA' WHEN w.wta>=10 THEN 'b 10-19'
            WHEN w.wta>=5 THEN 'c 5-9' ELSE 'd 1-4' END grp,
  count(*) AS employees, sum(w.wta) AS wta_alerts, sum(e.trips) AS their_trips,
  round(100.0*sum(w.wta)/sum(e.trips),2) AS wta_per_100_trips
FROM w JOIN e USING (stwid) GROUP BY 1 ORDER BY 1
""")
p("baseline: WTA per 100 trips for ALL vanta-Sea employees", """
SELECT round(100.0*(SELECT count(*) FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE'
                    AND business_unit='vanta-Sea')
            /(SELECT count(*) FROM emp WHERE business_unit='vanta-Sea'),3) AS wta_per_100_emp_legs
""")
p("concentration: cumulative share of WTA alerts from the top-N employees (vanta-Sea)", """
WITH w AS (SELECT stwid, count(*) c FROM alerts
           WHERE event_type='WOMAN_TRAVELLING_ALONE' AND business_unit='vanta-Sea' AND stwid<>0 GROUP BY 1),
     r AS (SELECT *, row_number() OVER (ORDER BY c DESC) rn, sum(c) OVER () tot FROM w)
SELECT rn AS top_n_employees, sum(c) OVER (ORDER BY rn) AS cum_alerts,
  round(100.0*sum(c) OVER (ORDER BY rn)/max(tot) OVER (),2) AS cum_pct
FROM r WHERE rn IN (25,50,100,200,300,500,1000,1668) ORDER BY 1
""")

# ============================================================ F. sign-off cutover
hdr("F. SIGN_OFF CUTOVER -- exact date")
p("daily May 1-31 pinnacle-Slc", """
SELECT start_date, count(*) n,
  count(*) FILTER (WHERE severity='NA') AS sev_na,
  count(*) FILTER (WHERE ack_min BETWEEN 1400 AND 1500) AS autoclosed
FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION' AND start_date<='2026-05-31'
GROUP BY 1 ORDER BY 1
""")
p("ARTIFACT CHECK: did pinnacle's OTHER alerts continue after the cutover?", """
SELECT date_trunc('week',start_ts)::DATE wk,
  count(*) FILTER (WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION') AS signoff,
  count(*) FILTER (WHERE event_type<>'EMPLOYEE_SIGN_OFF_TIME_VIOLATION') AS other_alerts
FROM alerts WHERE business_unit='pinnacle-Slc' GROUP BY 1 ORDER BY 1
""")

# ============================================================ G. vendor within BU
hdr("G. VENDOR SAFETY, HOLDING BUSINESS UNIT FIXED")
p("OVER_SPEEDING per 1k within catalyst-Sac + pinnacle-Slc (n>=2000)", """
WITH tv AS (SELECT business_unit, vendor_id, count(*) trips FROM trips GROUP BY 1,2),
     av AS (SELECT t.business_unit, t.vendor_id, count(*) c FROM alerts a JOIN trips t USING (trip_id)
            WHERE a.event_type='OVER_SPEEDING' GROUP BY 1,2)
SELECT tv.business_unit, tv.vendor_id, tv.trips, coalesce(av.c,0) AS speeding,
  round(1000.0*coalesce(av.c,0)/tv.trips,3) per_1k
FROM tv LEFT JOIN av USING (business_unit, vendor_id)
WHERE tv.trips>=2000 AND tv.business_unit IN ('catalyst-Sac','pinnacle-Slc','orbit-Slc')
ORDER BY 1, 5 DESC
""")
p("PANIC per 1k within catalyst-Sac + vanta-Sea (n>=2000)", """
WITH tv AS (SELECT business_unit, vendor_id, count(*) trips FROM trips GROUP BY 1,2),
     av AS (SELECT t.business_unit, t.vendor_id, count(*) c FROM alerts a JOIN trips t USING (trip_id)
            WHERE a.event_type LIKE 'PANIC%' GROUP BY 1,2)
SELECT tv.business_unit, tv.vendor_id, tv.trips, coalesce(av.c,0) AS panic,
  round(1000.0*coalesce(av.c,0)/tv.trips,3) per_1k
FROM tv LEFT JOIN av USING (business_unit, vendor_id)
WHERE tv.trips>=2000 AND tv.business_unit IN ('catalyst-Sac','vanta-Sea')
ORDER BY 1, 5 DESC
""")
p("driver_nc within pinnacle-Slc: alert load + OTA of NC trips", """
SELECT is_driver_nc, count(*) trips, round(100.0*avg(on_time),2) ota
FROM trips WHERE business_unit='pinnacle-Slc' GROUP BY 1 ORDER BY 2 DESC
""")
p("Rohan Mikhailov driver_nc by month (getting better or worse?)", """
SELECT vendor_id, month, count(*) trips, count(*) FILTER (WHERE is_driver_nc) AS drv_nc,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) pct
FROM trips WHERE business_unit='pinnacle-Slc'
  AND vendor_id IN ('Rohan Mikhailov Travel','Rahul Mikhailov Travel','Pooja Mikhailov Travel')
GROUP BY 1,2 ORDER BY 1,2
""")

print("\n\nDONE2")
