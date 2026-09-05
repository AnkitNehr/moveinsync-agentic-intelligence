#!/usr/bin/env python
"""
SAFETY & COMPLIANCE -- round 3.
Round 2 section D used hour(to_timestamp(epoch)) which is UTC, while shift_type is
local. That inverted the escort curve. Establish the offset empirically, then redo.
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
  TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT) AS actual_start_epoch,
  TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW alerts AS SELECT
  business_unit, TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid, event_type,
  strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_ts,
  hour(strptime(start_time,'%B %d, %Y, %I:%M %p')) AS start_hour,
  severity, state_text
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")

con.sql(f"""CREATE OR REPLACE VIEW emp AS SELECT
  business_unit, office, trip_date::DATE AS trip_date,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  gender, emp_role, boarding_status, TRY_CAST(is_no_show AS BOOLEAN) AS is_no_show,
  TRY_CAST(actual_drop_epoch AS DOUBLE) AS actual_drop_epoch
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

# ============================================ TZ
hdr("T. TIMEZONE: epoch is UTC, shift_type is local. Establish the offset.")
p("METHOD 1 -- LOGOUT trips: mode of (UTC start hour - shift hour) by office", """
SELECT office, count(*) n,
  mode((hour(to_timestamp(actual_start_epoch)) - shift_hour + 24) % 24) AS modal_offset_h,
  round(avg(CASE WHEN (hour(to_timestamp(actual_start_epoch)) - shift_hour + 24) % 24 = 7 THEN 100.0 ELSE 0 END),1) AS pct_offset_7,
  round(avg(CASE WHEN (hour(to_timestamp(actual_start_epoch)) - shift_hour + 24) % 24 = 8 THEN 100.0 ELSE 0 END),1) AS pct_offset_8
FROM trips WHERE trip_direction='LOGOUT' AND actual_start_epoch IS NOT NULL AND shift_hour IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
""")
p("METHOD 2 -- offset that makes to_timestamp(epoch)::DATE agree with local trip_date", """
SELECT off AS offset_hours, count(*) AS n,
  round(100.0*count(*) FILTER (WHERE (to_timestamp(actual_start_epoch) - to_hours(off))::DATE = trip_date)/count(*),2) AS pct_date_match
FROM trips, (SELECT unnest([0,4,5,6,7,8,9]) AS off)
WHERE actual_start_epoch IS NOT NULL GROUP BY 1 ORDER BY 3 DESC
""")
p("METHOD 3 -- cross-check vs alerts_data start_time (already local text)", """
WITH a AS (SELECT trip_id, min(start_ts) AS alert_ts FROM alerts GROUP BY 1)
SELECT round(median(date_diff('minute', a.alert_ts, to_timestamp(t.actual_start_epoch)))/60.0,2) AS median_hours_utc_minus_local,
  count(*) n
FROM a JOIN trips t USING (trip_id) WHERE t.actual_start_epoch IS NOT NULL
""")
p("per-office offset check with the winning offset (7h)", """
SELECT office, count(*) n,
  round(100.0*count(*) FILTER (WHERE (to_timestamp(actual_start_epoch) - to_hours(7))::DATE = trip_date)/count(*),2) AS pct_match_7h,
  round(100.0*count(*) FILTER (WHERE (to_timestamp(actual_start_epoch) - to_hours(8))::DATE = trip_date)/count(*),2) AS pct_match_8h
FROM trips WHERE actual_start_epoch IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================ escort ground truth
hdr("V. VALIDATE actual_escort AGAINST emp_Data escort ROWS")
p("crosstab: ride actual_escort vs presence of an emp_role='escort' row", """
WITH e AS (SELECT trip_id, count(*) FILTER (WHERE emp_role='escort') AS escort_rows FROM emp GROUP BY 1)
SELECT t.actual_escort, (e.escort_rows>0) AS has_escort_row, count(*) n
FROM trips t JOIN e USING (trip_id) GROUP BY 1,2 ORDER BY 3 DESC
""")
p("boarding_status values (is 'Boarded' the right ground-truth filter?)", """
SELECT boarding_status, count(*) n, count(*) FILTER (WHERE is_no_show) AS noshow
FROM emp GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================ redo D in local time
hdr("D2. SOLO-FEMALE ESCORT COVERAGE IN LOCAL TIME (offset -7h)")
con.sql("""CREATE OR REPLACE VIEW solo AS
WITH b AS (SELECT trip_id, count(*) AS n_boarded,
             count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT t.*, b.n_female,
  hour(to_timestamp(t.actual_end_epoch) - to_hours(7)) AS local_drop_hour,
  hour(to_timestamp(t.actual_start_epoch) - to_hours(7)) AS local_start_hour
FROM trips t JOIN b USING (trip_id)
WHERE t.product_type='CAB' AND b.n_boarded=1 AND t.actual_end_epoch IS NOT NULL""")

p("solo-employee trips by LOCAL drop hour x gender, escort rate", """
SELECT local_drop_hour,
  count(*) FILTER (WHERE n_female=1) AS solo_female,
  round(100.0*count(*) FILTER (WHERE n_female=1 AND actual_escort)
        /nullif(count(*) FILTER (WHERE n_female=1),0),2) AS female_pct_escort,
  count(*) FILTER (WHERE n_female=0) AS solo_male,
  round(100.0*count(*) FILTER (WHERE n_female=0 AND actual_escort)
        /nullif(count(*) FILTER (WHERE n_female=0),0),2) AS male_pct_escort
FROM solo GROUP BY 1 ORDER BY 1
""")
p("HEADLINE: solo-female LOCAL night drop (21:00-05:59) escort rate by BU", """
SELECT business_unit, count(*) AS solo_female_night_drops,
  count(*) FILTER (WHERE NOT actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT actual_escort)/count(*),2) AS pct_no_escort
FROM solo WHERE n_female=1 AND (local_drop_hour>=21 OR local_drop_hour<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("CONTROL: solo-male LOCAL night drop escort rate by BU", """
SELECT business_unit, count(*) AS solo_male_night_drops,
  round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) AS pct_escort
FROM solo WHERE n_female=0 AND (local_drop_hour>=21 OR local_drop_hour<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("solo-female night-drop escort by BU x month (trend / is it improving?)", """
SELECT business_unit,
  round(100.0*count(*) FILTER (WHERE month='2026-05-01' AND actual_escort)
        /nullif(count(*) FILTER (WHERE month='2026-05-01'),0),2) AS may,
  round(100.0*count(*) FILTER (WHERE month='2026-06-01' AND actual_escort)
        /nullif(count(*) FILTER (WHERE month='2026-06-01'),0),2) AS jun,
  round(100.0*count(*) FILTER (WHERE month='2026-07-01' AND actual_escort)
        /nullif(count(*) FILTER (WHERE month='2026-07-01'),0),2) AS jul,
  count(*) AS n
FROM solo WHERE n_female=1 AND (local_drop_hour>=21 OR local_drop_hour<=5)
GROUP BY 1 ORDER BY 5 DESC
""")
p("EXPOSURE: is the last drop the risky one? escort by whether drop is after 22:00 local", """
SELECT CASE WHEN local_drop_hour BETWEEN 21 AND 21 THEN '21:00-21:59'
            WHEN local_drop_hour BETWEEN 22 AND 23 THEN '22:00-23:59'
            WHEN local_drop_hour <= 2 THEN '00:00-02:59'
            WHEN local_drop_hour <= 5 THEN '03:00-05:59'
            ELSE 'day 06:00-20:59' END AS band,
  count(*) FILTER (WHERE n_female=1) AS solo_female,
  round(100.0*count(*) FILTER (WHERE n_female=1 AND NOT actual_escort)
        /nullif(count(*) FILTER (WHERE n_female=1),0),2) AS pct_no_escort
FROM solo GROUP BY 1 ORDER BY 1
""")
p("HEADLINE: solo-female night drops with NO escort AND no WTA alert (invisible risk)", """
SELECT s.business_unit, count(*) AS unescorted_solo_female_night,
  count(*) FILTER (WHERE w.trip_id IS NOT NULL) AS had_wta_alert,
  round(100.0*count(*) FILTER (WHERE w.trip_id IS NULL)/count(*),2) AS pct_no_alert_no_escort
FROM solo s LEFT JOIN (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE') w
  ON w.trip_id=s.trip_id
WHERE s.n_female=1 AND NOT s.actual_escort AND (s.local_drop_hour>=21 OR s.local_drop_hour<=5)
GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: are unescorted solo-female night drops concentrated in a few offices?", """
SELECT office, count(*) AS solo_female_night, count(*) FILTER (WHERE NOT actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT actual_escort)/count(*),2) AS pct_no_escort
FROM solo WHERE n_female=1 AND (local_drop_hour>=21 OR local_drop_hour<=5)
GROUP BY 1 HAVING count(*)>=500 ORDER BY 3 DESC
""")
p("ARTIFACT CHECK: LOGIN vs LOGOUT (a night LOGIN pickup is a different risk to a drop)", """
SELECT trip_direction, count(*) FILTER (WHERE n_female=1) AS solo_female_night,
  round(100.0*count(*) FILTER (WHERE n_female=1 AND NOT actual_escort)
        /nullif(count(*) FILTER (WHERE n_female=1),0),2) AS pct_no_escort
FROM solo WHERE (local_drop_hour>=21 OR local_drop_hour<=5) GROUP BY 1 ORDER BY 2 DESC
""")

# ============================================ WTA detector recall in local time
hdr("W. WTA DETECTOR RECALL vs GROUND TRUTH")
p("recall + precision of the WTA detector by BU (solo-female = ground truth)", """
WITH w AS (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
SELECT s.business_unit,
  count(*) FILTER (WHERE s.n_female=1) AS solo_female_trips,
  count(*) FILTER (WHERE s.n_female=1 AND w.trip_id IS NOT NULL) AS alerted_and_solo_female,
  round(100.0*count(*) FILTER (WHERE s.n_female=1 AND w.trip_id IS NOT NULL)
        /nullif(count(*) FILTER (WHERE s.n_female=1),0),2) AS recall_pct
FROM solo s LEFT JOIN w USING (trip_id) GROUP BY 1 ORDER BY 2 DESC
""")
p("of ALL trips carrying a WTA alert, how many really were a lone female? (precision)", """
WITH b AS (SELECT trip_id, count(*) AS n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT count(*) AS trips_with_wta_alert,
  count(*) FILTER (WHERE b.n_boarded=1 AND b.n_female=1) AS truly_solo_female,
  count(*) FILTER (WHERE b.n_boarded>1) AS more_than_one_boarded,
  count(*) FILTER (WHERE b.n_female=0) AS zero_females_boarded,
  round(100.0*count(*) FILTER (WHERE b.n_boarded=1 AND b.n_female=1)/count(*),2) AS precision_pct
FROM (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE') w
JOIN b USING (trip_id)
""")
p("what ARE the WTA-alerted trips then? boarded-count distribution", """
WITH b AS (SELECT trip_id, count(*) AS n_boarded, count(*) FILTER (WHERE gender='FEMALE') AS n_female
           FROM emp WHERE boarding_status='Boarded' AND emp_role='employee' GROUP BY 1)
SELECT b.n_boarded, b.n_female, count(*) n
FROM (SELECT DISTINCT trip_id FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE') w
JOIN b USING (trip_id) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 12
""")

# ============================================ FIRST_MALE_NO_SHOW
hdr("X. FIRST_MALE_NO_SHOW -- small n, characterise carefully")
p("FMNS by BU x month with trip denominators", """
WITH tv AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1)
SELECT tv.business_unit, tv.trips,
  count(*) FILTER (WHERE a.event_type='FIRST_MALE_NO_SHOW') AS fmns,
  round(1000.0*count(*) FILTER (WHERE a.event_type='FIRST_MALE_NO_SHOW')/tv.trips,3) AS per_1k
FROM tv LEFT JOIN alerts a ON a.business_unit=tv.business_unit GROUP BY 1,2 ORDER BY 3 DESC
""")
p("GROUND TRUTH: no-show rate by gender and by BU (is the male-no-show risk real?)", """
SELECT business_unit, count(*) n,
  round(100.0*count(*) FILTER (WHERE is_no_show AND gender='MALE')
        /nullif(count(*) FILTER (WHERE gender='MALE'),0),2) AS male_noshow_pct,
  round(100.0*count(*) FILTER (WHERE is_no_show AND gender='FEMALE')
        /nullif(count(*) FILTER (WHERE gender='FEMALE'),0),2) AS female_noshow_pct
FROM emp GROUP BY 1 ORDER BY 2 DESC
""")

print("\n\nDONE3")
