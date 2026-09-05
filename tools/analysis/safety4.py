#!/usr/bin/env python
"""
SAFETY & COMPLIANCE -- round 4.
Fixes two round-3 problems:
 (1) the UTC offset is 5-6h, not the 7h I assumed -> pin it down, then show the
     headline is robust to the choice, and prefer shift_hour (already local).
 (2) WTA "solo female" ground truth had only 31.6% precision -> test the better
     hypothesis: WTA = "the LAST employee dropped is female".
"""
import duckdb, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")
con = duckdb.connect(); con.sql("SET threads TO 8")

con.sql(f"""CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT) AS actual_start_epoch,
  TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW alerts AS SELECT
  business_unit, TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid, event_type, severity,
  strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_ts,
  hour(strptime(start_time,'%B %d, %Y, %I:%M %p')) AS start_hour
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW emp AS SELECT
  business_unit, office, trip_date::DATE AS trip_date,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  gender, emp_role, boarding_status, TRY_CAST(is_no_show AS BOOLEAN) AS is_no_show,
  TRY_CAST(actual_drop_epoch AS DOUBLE) AS actual_drop_epoch,
  TRY_CAST(actual_pickup_epoch AS DOUBLE) AS actual_pickup_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour
FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)""")

W = 118
def hdr(t): print("\n" + "=" * W); print(t); print("=" * W)
def p(title, q):
    print("\n### " + title); print("    " + q.strip().replace("\n", "\n    "))
    r = con.sql(q); cols = r.columns; rows = r.fetchall()
    wid = [len(str(c)) for c in cols]
    srows = [[("" if v is None else str(v)) for v in row] for row in rows]
    for row in srows:
        for i, v in enumerate(row): wid[i] = max(wid[i], len(v))
    print("  " + " | ".join(str(c).ljust(wid[i]) for i, c in enumerate(cols)))
    print("  " + "-+-".join("-" * w for w in wid))
    for row in srows: print("  " + " | ".join(v.ljust(wid[i]) for i, v in enumerate(row)))
    print(f"  [{len(rows)} rows]")

# =================================================== T2 pin the offset
hdr("T2. PIN THE UTC OFFSET (full histogram, two independent anchors)")
p("anchor A -- LOGOUT: (UTC trip-start hour - local shift hour) mod 24, histogram", """
SELECT (hour(to_timestamp(actual_start_epoch)) - shift_hour + 24) % 24 AS diff_h,
  count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
FROM trips WHERE trip_direction='LOGOUT' AND actual_start_epoch IS NOT NULL AND shift_hour IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 8
""")
p("anchor B -- LOGIN: (UTC trip-END hour - local shift hour) mod 24, histogram", """
SELECT (hour(to_timestamp(actual_end_epoch)) - shift_hour + 24) % 24 AS diff_h,
  count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
FROM trips WHERE trip_direction='LOGIN' AND actual_end_epoch IS NOT NULL AND shift_hour IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 8
""")
p("anchor C -- minutes, not hours: LOGOUT start minus shift start, at offset 6", """
SELECT round(median(date_diff('minute',
    make_timestamp(year(trip_date),month(trip_date),day(trip_date),shift_hour,0,0),
    to_timestamp(actual_start_epoch) - to_hours(6))),1) AS median_min_after_shift,
  count(*) n
FROM trips WHERE trip_direction='LOGOUT' AND actual_start_epoch IS NOT NULL AND shift_hour IS NOT NULL
""")
p("offset by office, modal diff for LOGOUT (do offices differ? = multi-timezone)", """
SELECT office, count(*) n,
  mode((hour(to_timestamp(actual_start_epoch)) - shift_hour + 24) % 24) AS modal_diff
FROM trips WHERE trip_direction='LOGOUT' AND actual_start_epoch IS NOT NULL AND shift_hour IS NOT NULL
GROUP BY 1 HAVING count(*)>=1000 ORDER BY 2 DESC
""")

# =================================================== E2 escort keyed on LOCAL shift_hour only
hdr("E2. ESCORT COVERAGE KEYED ON shift_hour ONLY (already local -- no conversion risk)")
con.sql("""CREATE OR REPLACE VIEW pax AS
SELECT trip_id,
  count(*) AS n_boarded,
  count(*) FILTER (WHERE gender='FEMALE') AS n_female,
  arg_max(gender, actual_drop_epoch) AS last_drop_gender,
  arg_min(gender, actual_pickup_epoch) AS first_pickup_gender
FROM emp WHERE boarding_status='Boarded' AND emp_role='employee'
  AND actual_drop_epoch IS NOT NULL AND actual_pickup_epoch IS NOT NULL
GROUP BY 1""")
p("sanity: pax view size + coverage of CAB trips", """
SELECT (SELECT count(*) FROM pax) AS pax_trips,
       (SELECT count(*) FROM trips WHERE product_type='CAB') AS cab_trips,
       (SELECT count(*) FROM trips t JOIN pax USING (trip_id) WHERE t.product_type='CAB') AS joined
""")
p("escort rate by shift_hour x last-drop gender (CAB, LOGOUT)", """
SELECT t.shift_hour, count(*) n,
  count(*) FILTER (WHERE p.last_drop_gender='FEMALE') AS last_drop_female,
  round(100.0*count(*) FILTER (WHERE p.last_drop_gender='FEMALE' AND t.actual_escort)
        /nullif(count(*) FILTER (WHERE p.last_drop_gender='FEMALE'),0),2) AS female_pct_escort,
  round(100.0*count(*) FILTER (WHERE p.last_drop_gender='MALE' AND t.actual_escort)
        /nullif(count(*) FILTER (WHERE p.last_drop_gender='MALE'),0),2) AS male_pct_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT'
GROUP BY 1 ORDER BY 1
""")
p("HEADLINE (local shift band): last-drop-female LOGOUT, night shift 19:00-05:59, by BU", """
SELECT t.business_unit, count(*) AS last_drop_female_night,
  count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("CONTROL: same for last-drop-MALE (is the gap gender-aware or universal?)", """
SELECT t.business_unit, count(*) AS last_drop_male_night,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) AS pct_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='MALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("SENSITIVITY: headline no-escort % at drop-hour offsets 5, 6, 7 (does it move?)", """
SELECT t.business_unit,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort AND
    (hour(to_timestamp(t.actual_end_epoch)-to_hours(5))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(5))<=5))
    /nullif(count(*) FILTER (WHERE (hour(to_timestamp(t.actual_end_epoch)-to_hours(5))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(5))<=5)),0),2) AS off5,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort AND
    (hour(to_timestamp(t.actual_end_epoch)-to_hours(6))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(6))<=5))
    /nullif(count(*) FILTER (WHERE (hour(to_timestamp(t.actual_end_epoch)-to_hours(6))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(6))<=5)),0),2) AS off6,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort AND
    (hour(to_timestamp(t.actual_end_epoch)-to_hours(7))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(7))<=5))
    /nullif(count(*) FILTER (WHERE (hour(to_timestamp(t.actual_end_epoch)-to_hours(7))>=21 OR hour(to_timestamp(t.actual_end_epoch)-to_hours(7))<=5)),0),2) AS off7,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort AND (t.shift_hour>=19 OR t.shift_hour<=5))
    /nullif(count(*) FILTER (WHERE (t.shift_hour>=19 OR t.shift_hour<=5)),0),2) AS by_shift_hour
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.actual_end_epoch IS NOT NULL
GROUP BY 1 ORDER BY 1
""")
p("scale: absolute count of unescorted female-last-drop night LOGOUTs per month", """
SELECT t.month, count(*) AS female_last_drop_night,
  count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5)
GROUP BY 1 ORDER BY 1
""")
p("ARTIFACT CHECK: pinnacle-Slc -- is the escort simply not staffed, or route-specific?", """
SELECT t.office, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5) AND t.business_unit='pinnacle-Slc'
GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: vendor mix of the unescorted female-last-drop night trips", """
SELECT t.vendor_id, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5)
GROUP BY 1 HAVING count(*)>=1000 ORDER BY 4 DESC LIMIT 12
""")

# =================================================== W2 WTA detector semantics
hdr("W2. WHAT DOES THE WTA DETECTOR ACTUALLY FIRE ON?")
p("precision of 3 competing definitions, on WTA-alerted trips", """
WITH w AS (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
SELECT count(*) AS wta_trips,
  round(100.0*count(*) FILTER (WHERE p.n_boarded=1 AND p.n_female=1)/count(*),2) AS pct_solo_female,
  round(100.0*count(*) FILTER (WHERE p.last_drop_gender='FEMALE')/count(*),2) AS pct_last_drop_female,
  round(100.0*count(*) FILTER (WHERE p.first_pickup_gender='FEMALE')/count(*),2) AS pct_first_pickup_female,
  round(100.0*count(*) FILTER (WHERE p.n_female>=1)/count(*),2) AS pct_any_female
FROM w JOIN pax p USING (trip_id)
""")
p("base rates for the same definitions on ALL CAB trips (is 'last drop female' informative?)", """
SELECT count(*) AS cab_trips,
  round(100.0*count(*) FILTER (WHERE p.n_boarded=1 AND p.n_female=1)/count(*),2) AS pct_solo_female,
  round(100.0*count(*) FILTER (WHERE p.last_drop_gender='FEMALE')/count(*),2) AS pct_last_drop_female,
  round(100.0*count(*) FILTER (WHERE p.first_pickup_gender='FEMALE')/count(*),2) AS pct_first_pickup_female
FROM trips t JOIN pax p USING (trip_id) WHERE t.product_type='CAB'
""")
p("restrict to the 2 BUs where the detector is ON -- precision there", """
WITH w AS (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
SELECT t.business_unit, count(*) AS wta_trips,
  round(100.0*count(*) FILTER (WHERE p.last_drop_gender='FEMALE')/count(*),2) AS pct_last_drop_female,
  round(100.0*count(*) FILTER (WHERE p.n_boarded=1 AND p.n_female=1)/count(*),2) AS pct_solo_female
FROM w JOIN trips t USING (trip_id) JOIN pax p USING (trip_id)
GROUP BY 1 ORDER BY 2 DESC
""")
p("RECALL of the detector against 'last drop female', in the 2 live BUs only", """
WITH w AS (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
SELECT t.business_unit, count(*) AS last_drop_female_trips,
  count(*) FILTER (WHERE w.trip_id IS NOT NULL) AS alerted,
  round(100.0*count(*) FILTER (WHERE w.trip_id IS NOT NULL)/count(*),2) AS recall_pct
FROM trips t JOIN pax p USING (trip_id) LEFT JOIN w ON w.trip_id=t.trip_id
WHERE t.product_type='CAB' AND p.last_drop_gender='FEMALE' AND t.trip_direction='LOGOUT'
GROUP BY 1 ORDER BY 2 DESC
""")

# =================================================== repeat employees, corrected
hdr("R. WTA REPEAT EMPLOYEES -- corrected concentration (round 2 query was wrong)")
p("distribution of WTA alerts per employee, vanta-Sea only", """
SELECT CASE WHEN c>=40 THEN 'a >=40' WHEN c>=20 THEN 'b 20-39' WHEN c>=10 THEN 'c 10-19'
            WHEN c>=5 THEN 'd 5-9' ELSE 'e 1-4' END grp,
  count(*) AS employees, sum(c) AS wta_alerts,
  round(100.0*sum(c)/(SELECT count(*) FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE'
                      AND business_unit='vanta-Sea' AND stwid<>0),2) AS pct_of_bu_wta
FROM (SELECT stwid, count(*) c FROM alerts
      WHERE event_type='WOMAN_TRAVELLING_ALONE' AND business_unit='vanta-Sea' AND stwid<>0
      GROUP BY 1) GROUP BY 1 ORDER BY 1
""")
p("normalise: are the heavy-repeat employees just heavy travellers?", """
WITH w AS (SELECT stwid, count(*) c FROM alerts
           WHERE event_type='WOMAN_TRAVELLING_ALONE' AND business_unit='vanta-Sea' AND stwid<>0 GROUP BY 1),
     e AS (SELECT stwid, count(*) legs FROM emp WHERE business_unit='vanta-Sea' GROUP BY 1)
SELECT CASE WHEN w.c>=40 THEN 'a >=40' WHEN w.c>=20 THEN 'b 20-39' WHEN w.c>=10 THEN 'c 10-19'
            WHEN w.c>=5 THEN 'd 5-9' ELSE 'e 1-4' END grp,
  count(*) AS employees, sum(w.c) AS wta, sum(e.legs) AS legs,
  round(1.0*sum(e.legs)/count(*),1) AS avg_legs_per_emp,
  round(100.0*sum(w.c)/sum(e.legs),2) AS wta_per_100_legs
FROM w JOIN e USING (stwid) GROUP BY 1 ORDER BY 1
""")
p("baseline legs/emp for vanta-Sea employees with NO WTA alert", """
WITH w AS (SELECT DISTINCT stwid FROM alerts
           WHERE event_type='WOMAN_TRAVELLING_ALONE' AND business_unit='vanta-Sea' AND stwid<>0),
     e AS (SELECT stwid, count(*) legs FROM emp WHERE business_unit='vanta-Sea' GROUP BY 1)
SELECT (w.stwid IS NOT NULL) AS has_wta_alert, count(*) AS employees,
  round(avg(e.legs),1) AS avg_legs
FROM e LEFT JOIN w USING (stwid) GROUP BY 1 ORDER BY 2 DESC
""")

print("\n\nDONE4")
