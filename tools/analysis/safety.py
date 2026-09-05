#!/usr/bin/env python
"""
SAFETY & COMPLIANCE analysis  -- alerts_data + *_nc flags + escort flags.
Every number printed here is the raw output of a query that was actually run.
"""
import duckdb, sys, os

BASE = "/Users/ankitnehra/Documents/ankit/moveinsync assesment"
RAW = os.path.join(BASE, "data", "raw")

con = duckdb.connect()
con.sql("SET threads TO 8")

# ---------------------------------------------------------------- views
con.sql(f"""CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, actual_cab_fuel_type,
  route_source, strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) AS delay_minutes,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(planned_km AS DOUBLE) AS planned_km,
  TRY_CAST(actual_escort AS BOOLEAN) AS actual_escort,
  TRY_CAST(is_driver_nc AS BOOLEAN) AS is_driver_nc,
  TRY_CAST(is_cab_nc AS BOOLEAN) AS is_cab_nc,
  TRY_CAST(actual_cab_capacity AS INT) AS cab_capacity,
  TRY_CAST(plannedemployee_cnt AS INT) AS emp_planned,
  TRY_CAST(actualemployee_cnt AS INT) AS emp_actual,
  TRY_CAST(noshow_cnt AS INT) AS noshow,
  TRY_CAST(replace(planned_start_epoch,',','') AS BIGINT) AS planned_start_epoch,
  TRY_CAST(replace(planned_end_epoch,',','') AS BIGINT) AS planned_end_epoch,
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
  hour(strptime(start_time,'%B %d, %Y, %I:%M %p')) AS start_hour
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")

W = 118
def hdr(t):
    print("\n" + "=" * W); print(t); print("=" * W)

def p(title, q):
    print("\n### " + title)
    print("    " + q.strip().replace("\n", "\n    "))
    r = con.sql(q)
    cols = r.columns
    rows = r.fetchall()
    wid = [len(str(c)) for c in cols]
    srows = [[("" if v is None else str(v)) for v in row] for row in rows]
    for row in srows:
        for i, v in enumerate(row):
            wid[i] = max(wid[i], len(v))
    print("  " + " | ".join(str(c).ljust(wid[i]) for i, c in enumerate(cols)))
    print("  " + "-+-".join("-" * w for w in wid))
    for row in srows:
        print("  " + " | ".join(v.ljust(wid[i]) for i, v in enumerate(row)))
    print(f"  [{len(rows)} rows]")
    return rows

# ================================================================== 0 sanity
hdr("0. SANITY / PARSE INTEGRITY")
p("row counts + parse failures", """
SELECT (SELECT count(*) FROM alerts) AS alerts_rows,
       (SELECT count(*) FROM alerts WHERE start_ts IS NULL) AS alert_start_unparsed,
       (SELECT count(*) FROM alerts WHERE trip_id IS NULL) AS alert_tripid_null,
       (SELECT count(*) FROM trips) AS trip_rows,
       (SELECT count(*) FROM trips WHERE trip_date IS NULL) AS trip_date_unparsed,
       (SELECT count(*) FROM trips WHERE trip_id IS NULL) AS trip_tripid_null
""")
p("alerts date range & trips date range", """
SELECT 'alerts' src, min(start_date) mn, max(start_date) mx, count(*) n FROM alerts
UNION ALL SELECT 'trips', min(trip_date), max(trip_date), count(*) FROM trips
""")
p("do alert trip_ids join to trips?", """
SELECT count(*) alerts_total,
       count(*) FILTER (WHERE t.trip_id IS NOT NULL) AS matched,
       round(100.0*count(*) FILTER (WHERE t.trip_id IS NOT NULL)/count(*),2) pct_matched
FROM alerts a LEFT JOIN (SELECT DISTINCT trip_id FROM trips) t USING (trip_id)
""")
p("trips per month (denominator)", """
SELECT month, count(*) trips FROM trips GROUP BY 1 ORDER BY 1
""")

# ================================================================== 1 sign-off collapse
hdr("1. EMPLOYEE_SIGN_OFF_TIME_VIOLATION COLLAPSE -- exact cutover date?")
p("monthly counts all event types", """
SELECT event_type,
  count(*) FILTER (WHERE month='2026-05-01') AS may,
  count(*) FILTER (WHERE month='2026-06-01') AS jun,
  count(*) FILTER (WHERE month='2026-07-01') AS jul,
  count(*) tot
FROM alerts GROUP BY 1 ORDER BY 5 DESC
""")
p("SIGN_OFF daily counts, May 20 - Jun 15 (find cutover)", """
SELECT start_date, count(*) n, count(DISTINCT business_unit) bus
FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
  AND start_date BETWEEN '2026-05-20' AND '2026-06-15'
GROUP BY 1 ORDER BY 1
""")
p("SIGN_OFF: last date with >=50, and every date after with any", """
SELECT start_date, count(*) n FROM alerts
WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION' AND start_date>='2026-06-01'
GROUP BY 1 ORDER BY 1
""")
p("SIGN_OFF weekly (is it decay or a cliff?)", """
SELECT date_trunc('week',start_ts)::DATE wk, count(*) n
FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
GROUP BY 1 ORDER BY 1
""")
p("SIGN_OFF by BU x month + BU trip volume", """
SELECT a.business_unit,
  count(*) FILTER (WHERE a.month='2026-05-01') AS may,
  count(*) FILTER (WHERE a.month='2026-06-01') AS jun,
  count(*) FILTER (WHERE a.month='2026-07-01') AS jul
FROM alerts a WHERE a.event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: did trip volume in those BUs collapse too?", """
SELECT business_unit,
  count(*) FILTER (WHERE month='2026-05-01') AS trips_may,
  count(*) FILTER (WHERE month='2026-06-01') AS trips_jun,
  count(*) FILTER (WHERE month='2026-07-01') AS trips_jul
FROM trips GROUP BY 1 ORDER BY 2 DESC
""")
p("ARTIFACT CHECK: total alerts/1000 trips by month (did ALL alerting stop?)", """
SELECT m.month,
  m.alerts, t.trips, round(1000.0*m.alerts/t.trips,2) alerts_per_1k
FROM (SELECT month, count(*) alerts FROM alerts GROUP BY 1) m
JOIN (SELECT month, count(*) trips FROM trips GROUP BY 1) t USING (month)
ORDER BY 1
""")
p("SIGN_OFF May: severity / source / state profile vs Jun+Jul survivors", """
SELECT CASE WHEN month='2026-05-01' THEN 'May' ELSE 'Jun+Jul' END per,
  severity, source, state_text, count(*) n
FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
GROUP BY 1,2,3,4 ORDER BY 1,5 DESC
""")
p("SIGN_OFF hour-of-day profile May vs after", """
SELECT start_hour,
  count(*) FILTER (WHERE month='2026-05-01') AS may,
  count(*) FILTER (WHERE month<>'2026-05-01') AS jun_jul
FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
GROUP BY 1 ORDER BY 1
""")

# ================================================================== 2 alert rate normalised
hdr("2. ALERT RATE PER 1000 TRIPS -- normalised by volume")
p("per 1k trips by month x event_type", """
WITH tv AS (SELECT month, count(*) trips FROM trips GROUP BY 1)
SELECT a.event_type,
  round(1000.0*count(*) FILTER (WHERE a.month='2026-05-01')/(SELECT trips FROM tv WHERE month='2026-05-01'),3) may_per1k,
  round(1000.0*count(*) FILTER (WHERE a.month='2026-06-01')/(SELECT trips FROM tv WHERE month='2026-06-01'),3) jun_per1k,
  round(1000.0*count(*) FILTER (WHERE a.month='2026-07-01')/(SELECT trips FROM tv WHERE month='2026-07-01'),3) jul_per1k,
  count(*) n_total
FROM alerts a GROUP BY 1 ORDER BY 5 DESC
""")
p("per 1k trips by business_unit x month (all alerts)", """
WITH tv AS (SELECT business_unit, month, count(*) trips FROM trips GROUP BY 1,2),
     av AS (SELECT business_unit, month, count(*) alerts FROM alerts GROUP BY 1,2)
SELECT tv.business_unit,
  round(1000.0*max(CASE WHEN tv.month='2026-05-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-05-01' THEN tv.trips END),2) may,
  round(1000.0*max(CASE WHEN tv.month='2026-06-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-06-01' THEN tv.trips END),2) jun,
  round(1000.0*max(CASE WHEN tv.month='2026-07-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-07-01' THEN tv.trips END),2) jul,
  sum(av.alerts) n_alerts, sum(tv.trips) n_trips
FROM tv LEFT JOIN av USING (business_unit, month) GROUP BY 1 ORDER BY 5 DESC
""")
p("EXCLUDING SIGN_OFF: per 1k by BU x month (does the story change?)", """
WITH tv AS (SELECT business_unit, month, count(*) trips FROM trips GROUP BY 1,2),
     av AS (SELECT business_unit, month, count(*) alerts FROM alerts
            WHERE event_type<>'EMPLOYEE_SIGN_OFF_TIME_VIOLATION' GROUP BY 1,2)
SELECT tv.business_unit,
  round(1000.0*max(CASE WHEN tv.month='2026-05-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-05-01' THEN tv.trips END),2) may,
  round(1000.0*max(CASE WHEN tv.month='2026-06-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-06-01' THEN tv.trips END),2) jun,
  round(1000.0*max(CASE WHEN tv.month='2026-07-01' THEN av.alerts END)/max(CASE WHEN tv.month='2026-07-01' THEN tv.trips END),2) jul,
  sum(av.alerts) n_alerts, sum(tv.trips) n_trips
FROM tv LEFT JOIN av USING (business_unit, month) GROUP BY 1 ORDER BY 5 DESC
""")
p("per 1k by office (top offices by trips, n>=5000 trips)", """
WITH tv AS (SELECT office, count(*) trips FROM trips GROUP BY 1),
     av AS (SELECT t.office, count(*) alerts FROM alerts a JOIN trips t USING (trip_id) GROUP BY 1)
SELECT tv.office, tv.trips, coalesce(av.alerts,0) alerts,
  round(1000.0*coalesce(av.alerts,0)/tv.trips,2) per_1k
FROM tv LEFT JOIN av USING (office) WHERE tv.trips>=5000 ORDER BY 4 DESC
""")

# ================================================================== 3 ack latency
hdr("3. ACKNOWLEDGEMENT LATENCY")
p("ack null / negative / distribution overall", """
SELECT count(*) n,
  count(*) FILTER (WHERE ack_ts IS NULL) AS never_acked,
  round(100.0*count(*) FILTER (WHERE ack_ts IS NULL)/count(*),3) pct_never,
  count(*) FILTER (WHERE ack_ts < start_ts) AS negative_latency,
  round(median(date_diff('minute',start_ts,ack_ts)),2) med_min,
  round(avg(date_diff('minute',start_ts,ack_ts)),2) avg_min,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.90),2) p90,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.99),2) p99,
  max(date_diff('minute',start_ts,ack_ts)) max_min
FROM alerts
""")
p("ack latency by severity", """
SELECT severity, count(*) n,
  count(*) FILTER (WHERE ack_ts IS NULL) AS never_acked,
  round(median(date_diff('minute',start_ts,ack_ts)),2) med_min,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.90),2) p90_min,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.99),2) p99_min,
  max(date_diff('minute',start_ts,ack_ts)) max_min,
  round(100.0*count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts)>15)/count(*),2) pct_gt15m
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("ack latency by event_type", """
SELECT event_type, count(*) n,
  count(*) FILTER (WHERE ack_ts IS NULL) AS never_acked,
  round(median(date_diff('minute',start_ts,ack_ts)),2) med_min,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.90),2) p90_min,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.99),2) p99_min,
  max(date_diff('minute',start_ts,ack_ts)) max_min
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("PANIC + Sev-1 specifically: latency buckets", """
SELECT CASE WHEN event_type LIKE 'PANIC%' THEN 'PANIC_*' ELSE 'other' END grp,
  CASE WHEN ack_ts IS NULL THEN 'never'
       WHEN date_diff('minute',start_ts,ack_ts)<=5 THEN 'a. <=5m'
       WHEN date_diff('minute',start_ts,ack_ts)<=15 THEN 'b. 6-15m'
       WHEN date_diff('minute',start_ts,ack_ts)<=60 THEN 'c. 16-60m'
       WHEN date_diff('minute',start_ts,ack_ts)<=1440 THEN 'd. 1-24h'
       ELSE 'e. >24h' END bucket,
  count(*) n
FROM alerts GROUP BY 1,2 ORDER BY 1,2
""")
p("ARTIFACT CHECK: is ack latency just clock granularity? distinct latency values", """
SELECT date_diff('minute',start_ts,ack_ts) lat_min, count(*) n
FROM alerts WHERE ack_ts IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20
""")
p("ack latency by BU x month (is anyone degrading?)", """
SELECT business_unit,
  round(median(date_diff('minute',start_ts,ack_ts)) FILTER (WHERE month='2026-05-01'),2) may_med,
  round(median(date_diff('minute',start_ts,ack_ts)) FILTER (WHERE month='2026-06-01'),2) jun_med,
  round(median(date_diff('minute',start_ts,ack_ts)) FILTER (WHERE month='2026-07-01'),2) jul_med,
  round(quantile_cont(date_diff('minute',start_ts,ack_ts),0.95),2) p95_all,
  count(*) n
FROM alerts GROUP BY 1 ORDER BY 6 DESC
""")
p("slow acks (>60min) -- who and what", """
SELECT business_unit, event_type, count(*) n,
  round(median(date_diff('minute',start_ts,ack_ts)),1) med
FROM alerts WHERE date_diff('minute',start_ts,ack_ts)>60
GROUP BY 1,2 HAVING count(*)>=20 ORDER BY 3 DESC
""")
p("overnight-hangover check: slow acks by alert start hour", """
SELECT start_hour, count(*) n,
  round(100.0*count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts)>60)/count(*),2) pct_gt60m,
  round(median(date_diff('minute',start_ts,ack_ts)),1) med_min
FROM alerts GROUP BY 1 ORDER BY 1
""")

# ================================================================== 4 open alerts
hdr("4. OPEN / NEW ALERTS NEVER CLOSED")
p("state_text x ack null", """
SELECT state_text, count(*) n, count(*) FILTER (WHERE ack_ts IS NULL) AS unacked,
  min(start_date) oldest, max(start_date) newest
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("open/new detail: BU x event_type x severity", """
SELECT business_unit, event_type, severity, state_text, count(*) n,
  min(start_date) oldest, max(start_date) newest,
  round(avg(date_diff('day', start_ts, DATE '2026-07-31')),1) avg_age_days_at_dataset_end
FROM alerts WHERE state_text IN ('OPEN','NEW') GROUP BY 1,2,3,4 ORDER BY 5 DESC
""")
p("ARTIFACT CHECK: are OPEN/NEW just the newest rows (tail effect)?", """
SELECT month, count(*) FILTER (WHERE state_text IN ('OPEN','NEW')) AS open_new, count(*) tot,
  round(100.0*count(*) FILTER (WHERE state_text IN ('OPEN','NEW'))/count(*),4) pct
FROM alerts GROUP BY 1 ORDER BY 1
""")
p("OPEN/NEW by start_date (are they spread or clustered?)", """
SELECT start_date, count(*) n, string_agg(DISTINCT event_type,'; ') AS types
FROM alerts WHERE state_text IN ('OPEN','NEW') GROUP BY 1 ORDER BY 1
""")

# ================================================================== 5 severity False
hdr("5. SEVERITY FIELD INTEGRITY -- the 'False' and 'NA' values")
p("severity x event_type matrix", """
SELECT event_type,
  count(*) FILTER (WHERE severity='Sev-1') AS sev1,
  count(*) FILTER (WHERE severity='Sev-2') AS sev2,
  count(*) FILTER (WHERE severity='Sev-3') AS sev3,
  count(*) FILTER (WHERE severity='NA') AS na,
  count(*) FILTER (WHERE severity='False') AS falsev,
  count(*) tot,
  round(100.0*count(*) FILTER (WHERE severity IN ('False','NA'))/count(*),2) pct_unusable
FROM alerts GROUP BY 1 ORDER BY 7 DESC
""")
p("severity='False' by month/source -- is it a period-bounded bug?", """
SELECT month, source,
  count(*) FILTER (WHERE severity='False') AS falsev, count(*) tot,
  round(100.0*count(*) FILTER (WHERE severity='False')/count(*),2) pct_false
FROM alerts GROUP BY 1,2 ORDER BY 1,3 DESC
""")
p("severity='False' daily trend (start/stop dates?)", """
SELECT date_trunc('week',start_ts)::DATE wk,
  count(*) FILTER (WHERE severity='False') AS falsev, count(*) tot,
  round(100.0*count(*) FILTER (WHERE severity='False')/count(*),2) pct
FROM alerts GROUP BY 1 ORDER BY 1
""")
p("ARTIFACT CHECK: within DEVICE_NOT_REACHABLE, do Sev-3 and False behave the same?", """
SELECT event_type, severity, count(*) n,
  round(median(date_diff('minute',start_ts,ack_ts)),2) med_ack,
  round(avg(start_hour),2) avg_hour
FROM alerts WHERE event_type IN ('DEVICE_NOT_REACHABLE','VEHICLE_STOPPAGE','OVER_SPEEDING')
GROUP BY 1,2 ORDER BY 1,3 DESC
""")
p("Sev-1 / Sev-2 : which event types, and are they acked?", """
SELECT severity, event_type, business_unit, count(*) n,
  count(*) FILTER (WHERE ack_ts IS NULL) AS unacked,
  round(median(date_diff('minute',start_ts,ack_ts)),2) med_ack
FROM alerts WHERE severity IN ('Sev-1','Sev-2') GROUP BY 1,2,3 ORDER BY 1,4 DESC
""")

# ================================================================== 6 gender-safety alerts
hdr("6. WOMAN_TRAVELLING_ALONE + FIRST_MALE_NO_SHOW")
p("WTA + FMNS per 1k trips by month", """
WITH tv AS (SELECT month, count(*) trips FROM trips GROUP BY 1)
SELECT a.month, tv.trips,
  count(*) FILTER (WHERE event_type='WOMAN_TRAVELLING_ALONE') AS wta,
  round(1000.0*count(*) FILTER (WHERE event_type='WOMAN_TRAVELLING_ALONE')/tv.trips,3) wta_per1k,
  count(*) FILTER (WHERE event_type='FIRST_MALE_NO_SHOW') AS fmns,
  round(1000.0*count(*) FILTER (WHERE event_type='FIRST_MALE_NO_SHOW')/tv.trips,3) fmns_per1k
FROM alerts a JOIN tv ON a.month=tv.month GROUP BY 1,2 ORDER BY 1
""")
p("WTA by hour of day (night concentration?)", """
SELECT start_hour, count(*) FILTER (WHERE event_type='WOMAN_TRAVELLING_ALONE') AS wta,
  count(*) FILTER (WHERE event_type='FIRST_MALE_NO_SHOW') AS fmns, count(*) all_alerts
FROM alerts GROUP BY 1 ORDER BY 1
""")
p("WTA night vs day band, joined to trips for escort status", """
WITH j AS (
  SELECT a.event_type, a.start_hour, t.actual_escort, t.trip_direction, t.business_unit,
    CASE WHEN t.shift_hour>=21 OR t.shift_hour<=5 THEN 'night' ELSE 'day' END band
  FROM alerts a JOIN trips t USING (trip_id)
  WHERE a.event_type='WOMAN_TRAVELLING_ALONE')
SELECT band, count(*) n,
  count(*) FILTER (WHERE actual_escort) AS with_escort,
  round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escorted
FROM j GROUP BY 1 ORDER BY 2 DESC
""")
p("HEADLINE CANDIDATE: WTA alerts on NIGHT trips WITHOUT escort, by BU", """
WITH j AS (
  SELECT a.event_id, t.business_unit, t.actual_escort, t.shift_hour,
    CASE WHEN t.shift_hour>=21 OR t.shift_hour<=5 THEN 'night' ELSE 'day' END band
  FROM alerts a JOIN trips t USING (trip_id)
  WHERE a.event_type='WOMAN_TRAVELLING_ALONE')
SELECT business_unit, band, count(*) n,
  count(*) FILTER (WHERE NOT actual_escort) AS no_escort,
  round(100.0*count(*) FILTER (WHERE NOT actual_escort)/count(*),2) pct_no_escort
FROM j GROUP BY 1,2 HAVING count(*)>=100 ORDER BY 5 DESC
""")
p("WTA per 1k by BU (normalised)", """
WITH tv AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1)
SELECT tv.business_unit, tv.trips,
  count(*) FILTER (WHERE a.event_type='WOMAN_TRAVELLING_ALONE') AS wta,
  round(1000.0*count(*) FILTER (WHERE a.event_type='WOMAN_TRAVELLING_ALONE')/tv.trips,3) wta_per1k,
  count(*) FILTER (WHERE a.event_type='FIRST_MALE_NO_SHOW') AS fmns
FROM tv LEFT JOIN alerts a ON a.business_unit=tv.business_unit GROUP BY 1,2 ORDER BY 4 DESC
""")

# ================================================================== 7 escort compliance
hdr("7. ESCORT COMPLIANCE -- night vs day")
p("escort rate by shift band, all trips", """
SELECT CASE WHEN shift_hour>=21 OR shift_hour<=5 THEN 'night(21-05)' ELSE 'day(06-20)' END band,
  count(*) n, count(*) FILTER (WHERE actual_escort) AS escorted,
  round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escort,
  count(*) FILTER (WHERE actual_escort IS NULL) AS null_escort
FROM trips GROUP BY 1 ORDER BY 2 DESC
""")
p("escort rate by shift hour (full curve)", """
SELECT shift_hour, count(*) n, round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escort
FROM trips GROUP BY 1 ORDER BY 1
""")
p("escort rate night by BU x month", """
SELECT business_unit,
  count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5) AS night_n,
  round(100.0*count(*) FILTER (WHERE (shift_hour>=21 OR shift_hour<=5) AND actual_escort)
        /nullif(count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5),0),2) night_pct,
  round(100.0*count(*) FILTER (WHERE NOT (shift_hour>=21 OR shift_hour<=5) AND actual_escort)
        /nullif(count(*) FILTER (WHERE NOT (shift_hour>=21 OR shift_hour<=5)),0),2) day_pct
FROM trips GROUP BY 1 ORDER BY 2 DESC
""")
p("night escort rate by month (trend)", """
SELECT month,
  count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5) AS night_n,
  round(100.0*count(*) FILTER (WHERE (shift_hour>=21 OR shift_hour<=5) AND actual_escort)
        /nullif(count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5),0),2) night_escort_pct,
  round(100.0*count(*) FILTER (WHERE NOT (shift_hour>=21 OR shift_hour<=5) AND actual_escort)
        /nullif(count(*) FILTER (WHERE NOT (shift_hour>=21 OR shift_hour<=5)),0),2) day_escort_pct
FROM trips GROUP BY 1 ORDER BY 1
""")
p("ARTIFACT CHECK: escort by product_type (is escort even applicable to BUS?)", """
SELECT product_type, count(*) n, round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escort,
  round(100.0*count(*) FILTER (WHERE (shift_hour>=21 OR shift_hour<=5) AND actual_escort)
        /nullif(count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5),0),2) night_pct_escort,
  count(*) FILTER (WHERE shift_hour>=21 OR shift_hour<=5) AS night_n
FROM trips GROUP BY 1 ORDER BY 2 DESC
""")
p("HEADLINE: LAST-DROP / FIRST-PICKUP risk -- escort on night CAB by direction", """
SELECT trip_direction,
  CASE WHEN shift_hour>=21 OR shift_hour<=5 THEN 'night' ELSE 'day' END band,
  count(*) n, round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escort
FROM trips WHERE product_type='CAB' GROUP BY 1,2 ORDER BY 1,2
""")
p("escort x noshow: does escort survive when the trip is nearly empty?", """
SELECT CASE WHEN shift_hour>=21 OR shift_hour<=5 THEN 'night' ELSE 'day' END band,
  emp_actual, count(*) n, round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escort
FROM trips WHERE product_type='CAB' AND emp_actual BETWEEN 0 AND 5
GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2
""")

# ================================================================== 8 driver/cab NC by vendor
hdr("8. NON-COMPLIANCE (is_driver_nc / is_cab_nc) BY VENDOR")
p("overall NC rates + null share", """
SELECT count(*) n,
  count(*) FILTER (WHERE is_driver_nc) AS driver_nc, round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) driver_nc_pct,
  count(*) FILTER (WHERE is_cab_nc) AS cab_nc, round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct,
  count(*) FILTER (WHERE is_driver_nc IS NULL) AS driver_null,
  count(*) FILTER (WHERE is_driver_nc AND is_cab_nc) AS both_nc
FROM trips
""")
p("NC by month", """
SELECT month, count(*) n,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) driver_nc_pct,
  round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct
FROM trips GROUP BY 1 ORDER BY 1
""")
p("NC by vendor, n>=2000 trips", """
SELECT vendor_id, count(*) n,
  count(*) FILTER (WHERE is_driver_nc) AS drv_nc,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) drv_nc_pct,
  count(*) FILTER (WHERE is_cab_nc) AS cab_nc,
  round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct
FROM trips GROUP BY 1 HAVING count(*)>=2000 ORDER BY 4 DESC LIMIT 30
""")
p("NC by vendor BOTTOM (best) for contrast", """
SELECT vendor_id, count(*) n,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) drv_nc_pct,
  round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct
FROM trips GROUP BY 1 HAVING count(*)>=2000 ORDER BY 3 ASC LIMIT 10
""")
p("ARTIFACT CHECK: is NC confounded by business_unit? vendor x BU spread", """
SELECT business_unit, count(*) n,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) drv_nc_pct,
  round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct,
  count(DISTINCT vendor_id) vendors
FROM trips GROUP BY 1 ORDER BY 2 DESC
""")
p("WITHIN-BU vendor NC: top offenders holding BU fixed (n>=2000)", """
SELECT business_unit, vendor_id, count(*) n,
  round(100.0*count(*) FILTER (WHERE is_driver_nc)/count(*),3) drv_nc_pct,
  round(100.0*count(*) FILTER (WHERE is_cab_nc)/count(*),3) cab_nc_pct
FROM trips GROUP BY 1,2 HAVING count(*)>=2000 ORDER BY 4 DESC LIMIT 15
""")
p("does NC co-occur with lateness / alerts? (does the flag mean anything?)", """
SELECT is_driver_nc, is_cab_nc, count(*) n,
  round(100.0*avg(on_time),2) ota,
  round(median(delay_minutes),2) med_delay
FROM trips GROUP BY 1,2 ORDER BY 3 DESC
""")
p("NC trips: do they carry more alerts per 1k?", """
WITH t AS (SELECT trip_id, (is_driver_nc OR is_cab_nc) AS anync FROM trips),
     a AS (SELECT trip_id, count(*) c FROM alerts GROUP BY 1)
SELECT t.anync, count(*) trips, coalesce(sum(a.c),0) alerts,
  round(1000.0*coalesce(sum(a.c),0)/count(*),2) alerts_per1k
FROM t LEFT JOIN a USING (trip_id) GROUP BY 1 ORDER BY 2 DESC
""")

# ================================================================== 9 speeding & panic by vendor
hdr("9. OVER_SPEEDING & PANIC_* BY VENDOR (per 1000 trips)")
p("OVER_SPEEDING per 1k by vendor (n>=2000 trips)", """
WITH tv AS (SELECT vendor_id, count(*) trips FROM trips GROUP BY 1),
     av AS (SELECT t.vendor_id, count(*) c FROM alerts a JOIN trips t USING (trip_id)
            WHERE a.event_type='OVER_SPEEDING' GROUP BY 1)
SELECT tv.vendor_id, tv.trips, coalesce(av.c,0) speeding,
  round(1000.0*coalesce(av.c,0)/tv.trips,3) per_1k
FROM tv LEFT JOIN av USING (vendor_id) WHERE tv.trips>=2000 ORDER BY 4 DESC LIMIT 20
""")
p("PANIC_* per 1k by vendor (n>=2000 trips)", """
WITH tv AS (SELECT vendor_id, count(*) trips FROM trips GROUP BY 1),
     av AS (SELECT t.vendor_id, count(*) c FROM alerts a JOIN trips t USING (trip_id)
            WHERE a.event_type LIKE 'PANIC%' GROUP BY 1)
SELECT tv.vendor_id, tv.trips, coalesce(av.c,0) panic,
  round(1000.0*coalesce(av.c,0)/tv.trips,3) per_1k
FROM tv LEFT JOIN av USING (vendor_id) WHERE tv.trips>=2000 ORDER BY 4 DESC LIMIT 20
""")
p("ARTIFACT CHECK: PANIC source is device-based -- what share of trips have a device at all? by BU", """
WITH tv AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
     av AS (SELECT business_unit, count(*) FILTER (WHERE event_type LIKE 'PANIC%') AS panic,
                   count(*) FILTER (WHERE event_type='OVER_SPEEDING') AS speed,
                   count(*) FILTER (WHERE event_type='DEVICE_NOT_REACHABLE') AS dnr
            FROM alerts GROUP BY 1)
SELECT tv.business_unit, tv.trips, coalesce(av.panic,0) panic, coalesce(av.speed,0) speed, coalesce(av.dnr,0) dnr,
  round(1000.0*coalesce(av.panic,0)/tv.trips,3) panic_per1k,
  round(1000.0*coalesce(av.speed,0)/tv.trips,3) speed_per1k,
  round(1000.0*coalesce(av.dnr,0)/tv.trips,3) dnr_per1k
FROM tv LEFT JOIN av USING (business_unit) ORDER BY 2 DESC
""")
p("PANIC by type x BU x month (real events or device noise?)", """
SELECT event_type, business_unit,
  count(*) FILTER (WHERE month='2026-05-01') AS may,
  count(*) FILTER (WHERE month='2026-06-01') AS jun,
  count(*) FILTER (WHERE month='2026-07-01') AS jul, count(*) tot
FROM alerts WHERE event_type LIKE 'PANIC%' GROUP BY 1,2 ORDER BY 6 DESC
""")
p("PANIC repeat offenders: same trip multiple panics?", """
SELECT panics_on_trip, count(*) n_trips FROM (
  SELECT trip_id, count(*) panics_on_trip FROM alerts WHERE event_type LIKE 'PANIC%' GROUP BY 1)
GROUP BY 1 ORDER BY 1
""")
p("OVER_SPEEDING by hour of day", """
SELECT start_hour, count(*) FILTER (WHERE event_type='OVER_SPEEDING') AS speeding,
  count(*) FILTER (WHERE event_type LIKE 'PANIC%') AS panic
FROM alerts GROUP BY 1 ORDER BY 1
""")

# ================================================================== 10 alert->trip linkage
hdr("10. ALERT CONCENTRATION / REPEAT-OFFENDER STRUCTURE")
p("alerts per trip distribution", """
SELECT alerts_on_trip, count(*) n_trips, sum(alerts_on_trip) total_alerts FROM (
  SELECT trip_id, count(*) alerts_on_trip FROM alerts WHERE trip_id IS NOT NULL GROUP BY 1)
GROUP BY 1 ORDER BY 1 LIMIT 25
""")
p("share of alerts on the top 1% of alerting trips", """
WITH t AS (SELECT trip_id, count(*) c FROM alerts WHERE trip_id IS NOT NULL GROUP BY 1),
     r AS (SELECT *, ntile(100) OVER (ORDER BY c DESC) pct FROM t)
SELECT CASE WHEN pct<=1 THEN 'top 1%' WHEN pct<=10 THEN 'top 2-10%' ELSE 'bottom 90%' END grp,
  count(*) trips, sum(c) alerts, round(100.0*sum(c)/(SELECT sum(c) FROM t),2) pct_of_alerts
FROM r GROUP BY 1 ORDER BY 3 DESC
""")
p("stwid placeholder share by event_type (can we attribute to an employee?)", """
SELECT event_type, count(*) n, count(*) FILTER (WHERE stwid=0) AS stwid_zero,
  round(100.0*count(*) FILTER (WHERE stwid=0)/count(*),2) pct_zero,
  count(DISTINCT nullif(stwid,0)) distinct_real_emp
FROM alerts GROUP BY 1 ORDER BY 2 DESC
""")
p("repeat employees on WTA (excluding stwid 0)", """
SELECT wta_alerts_per_emp, count(*) n_employees FROM (
  SELECT stwid, count(*) wta_alerts_per_emp FROM alerts
  WHERE event_type='WOMAN_TRAVELLING_ALONE' AND stwid<>0 GROUP BY 1)
GROUP BY 1 ORDER BY 1 DESC LIMIT 15
""")
p("HEADLINE CANDIDATE: employees with >=10 WTA alerts", """
WITH e AS (SELECT stwid, business_unit, count(*) c FROM alerts
           WHERE event_type='WOMAN_TRAVELLING_ALONE' AND stwid<>0 GROUP BY 1,2)
SELECT business_unit, count(*) FILTER (WHERE c>=10) AS emp_ge10,
  count(*) FILTER (WHERE c>=5) AS emp_ge5, count(*) all_emp, sum(c) alerts,
  round(100.0*sum(c) FILTER (WHERE c>=5)/sum(c),2) pct_alerts_from_ge5
FROM e GROUP BY 1 ORDER BY 5 DESC
""")

print("\n\nDONE")
