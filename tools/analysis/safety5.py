#!/usr/bin/env python
"""SAFETY & COMPLIANCE -- round 5: nail the escort policy cliff and the orbit-Slc gap."""
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
  TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT) AS actual_start_epoch,
  TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
  TRY_CAST(split_part(shift_type,':',1) AS INT) AS shift_hour
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)""")
con.sql(f"""CREATE OR REPLACE VIEW alerts AS SELECT
  business_unit, TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id, event_type, severity, state_text
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")
con.sql(f"""CREATE OR REPLACE VIEW emp AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id, gender, emp_role, boarding_status,
  TRY_CAST(actual_drop_epoch AS DOUBLE) AS actual_drop_epoch,
  TRY_CAST(actual_pickup_epoch AS DOUBLE) AS actual_pickup_epoch
FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)""")
con.sql("""CREATE OR REPLACE VIEW pax AS
SELECT trip_id, count(*) AS n_boarded,
  arg_max(gender, actual_drop_epoch) AS last_drop_gender
FROM emp WHERE boarding_status='Boarded' AND emp_role='employee'
  AND actual_drop_epoch IS NOT NULL GROUP BY 1""")

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

hdr("P. THE ESCORT POLICY CLIFF -- is the 19:00 boundary defensible?")
p("trip duration is offset-free: median LOGOUT duration by shift_hour -> implied drop clock time", """
SELECT t.shift_hour, count(*) n,
  round(median((t.actual_end_epoch - t.actual_start_epoch)/60.0),1) AS med_dur_min,
  round(quantile_cont((t.actual_end_epoch - t.actual_start_epoch)/60.0,0.90),1) AS p90_dur_min,
  round(t.shift_hour + median((t.actual_end_epoch - t.actual_start_epoch)/60.0)/60.0,2) AS implied_median_last_drop_hour,
  round(t.shift_hour + quantile_cont((t.actual_end_epoch - t.actual_start_epoch)/60.0,0.90)/60.0,2) AS implied_p90_last_drop_hour
FROM trips t WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT'
  AND t.actual_end_epoch IS NOT NULL AND t.actual_start_epoch IS NOT NULL
  AND t.shift_hour BETWEEN 15 AND 23
GROUP BY 1 ORDER BY 1
""")
p("HEADLINE: the cliff -- female last drop, shift 16..21, escort vs implied drop time", """
SELECT t.shift_hour, count(*) AS female_last_drop,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) AS pct_escort,
  count(*) FILTER (WHERE NOT t.actual_escort) AS n_unescorted,
  round(median((t.actual_end_epoch - t.actual_start_epoch)/60.0),1) AS med_dur_min,
  round(t.shift_hour + quantile_cont((t.actual_end_epoch - t.actual_start_epoch)/60.0,0.90)/60.0,2) AS p90_drop_hour
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.shift_hour BETWEEN 16 AND 21 AND t.actual_end_epoch IS NOT NULL
GROUP BY 1 ORDER BY 1
""")
p("how many shift-18 female last drops actually END at/after 19:00 local-equivalent?", """
SELECT t.shift_hour, count(*) n,
  count(*) FILTER (WHERE t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 >= 19*60) AS drop_after_1900,
  round(100.0*count(*) FILTER (WHERE t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 >= 19*60)/count(*),2) AS pct,
  count(*) FILTER (WHERE t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 >= 20*60) AS drop_after_2000
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.shift_hour IN (17,18) AND t.actual_end_epoch IS NOT NULL
GROUP BY 1 ORDER BY 1
""")
p("SIZE OF THE GAP: shift 17+18 female last drops ending >=19:00 with no escort, by BU", """
SELECT t.business_unit, count(*) AS exposed_trips,
  count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.shift_hour IN (17,18) AND t.actual_end_epoch IS NOT NULL
  AND t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 >= 19*60
GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: control -- same exposure for MALE last drop (already ~0 escort anyway?)", """
SELECT p.last_drop_gender, count(*) AS exposed_trips,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) AS pct_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT'
  AND t.shift_hour IN (17,18) AND t.actual_end_epoch IS NOT NULL
  AND t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 >= 19*60
GROUP BY 1 ORDER BY 2 DESC
""")
p("and the shift-19 comparison group (same real drop window, different policy bucket)", """
SELECT t.shift_hour, count(*) AS female_last_drop,
  round(100.0*count(*) FILTER (WHERE t.actual_escort)/count(*),2) AS pct_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.shift_hour IN (18,19) AND t.actual_end_epoch IS NOT NULL
  AND t.shift_hour*60 + (t.actual_end_epoch-t.actual_start_epoch)/60.0 BETWEEN 19*60 AND 21*60
GROUP BY 1 ORDER BY 1
""")

hdr("O. orbit-Slc ESCORT GAP -- the worst night performer")
p("orbit-Slc female-last-drop night LOGOUT by month", """
SELECT t.month, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5) AND t.business_unit='orbit-Slc'
GROUP BY 1 ORDER BY 1
""")
p("orbit-Slc by shift_hour (which shifts are uncovered?)", """
SELECT t.shift_hour, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND t.business_unit='orbit-Slc' GROUP BY 1 ORDER BY 1
""")
p("orbit-Slc by vendor", """
SELECT t.vendor_id, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) AS pct_no_escort
FROM trips t JOIN pax p USING (trip_id)
WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
  AND (t.shift_hour>=19 OR t.shift_hour<=5) AND t.business_unit='orbit-Slc'
GROUP BY 1 ORDER BY 2 DESC
""")

hdr("S. SEVERITY TAXONOMY IS BU-SPECIFIC + Sev-1 ack (negative finding check)")
p("severity distribution by BU", """
SELECT business_unit, count(*) n,
  count(*) FILTER (WHERE severity='Sev-1') AS sev1,
  count(*) FILTER (WHERE severity='Sev-2') AS sev2,
  count(*) FILTER (WHERE severity='Sev-3') AS sev3,
  count(*) FILTER (WHERE severity='NA') AS na,
  count(*) FILTER (WHERE severity='False') AS falsev
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("state_text NEW/OPEN by BU (unclosed backlog)", """
SELECT business_unit, count(*) FILTER (WHERE state_text IN ('NEW','OPEN')) AS open_new, count(*) n
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")

hdr("N. DO UNESCORTED FEMALE-LAST-DROP NIGHT TRIPS CARRY MORE ALERTS?")
p("alerts per 1000 trips, escorted vs not, female-last-drop night LOGOUT", """
WITH base AS (
  SELECT t.trip_id, t.actual_escort FROM trips t JOIN pax p USING (trip_id)
  WHERE t.product_type='CAB' AND t.trip_direction='LOGOUT' AND p.last_drop_gender='FEMALE'
    AND (t.shift_hour>=19 OR t.shift_hour<=5)),
  al AS (SELECT trip_id, count(*) c FROM alerts GROUP BY 1)
SELECT b.actual_escort, count(*) AS trips, coalesce(sum(al.c),0) AS alerts,
  round(1000.0*coalesce(sum(al.c),0)/count(*),2) AS alerts_per_1k
FROM base b LEFT JOIN al USING (trip_id) GROUP BY 1 ORDER BY 2 DESC
""")
print("\n\nDONE5")
