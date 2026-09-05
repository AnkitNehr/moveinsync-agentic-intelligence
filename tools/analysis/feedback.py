"""Feedback & sentiment analysis on trip_feedback.csv.

Run:  .venv/bin/python tools/analysis/feedback.py [section]
Every number printed here is produced by an actually-executed DuckDB query.
"""
import sys
import duckdb

RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw"
con = duckdb.connect()
con.sql("SET preserve_insertion_order=false")

con.sql(f"""
CREATE OR REPLACE VIEW fb AS SELECT
  business_unit,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  trip_type,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  strptime(trip_date,'%B %d, %Y, %I:%M %p') AS trip_ts,
  strptime(creation_time,'%B %d, %Y, %I:%M %p') AS created_ts,
  date_trunc('month', strptime(trip_date,'%B %d, %Y, %I:%M %p'))::DATE AS month,
  TRY_CAST(route_rating AS INT)   AS route_rating,
  TRY_CAST(driver_rating AS INT)  AS driver_rating,
  TRY_CAST(cab_rating AS INT)     AS cab_rating,
  TRY_CAST(safety_rating AS INT)  AS safety_rating,
  TRY_CAST(marshal_rating AS INT) AS marshal_rating
FROM read_csv('{RAW}/trip_feedback.csv', header=true, all_varchar=true, sample_size=-1)
""")

con.sql(f"""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, actual_cab_fuel_type,
  route_source,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
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
  TRY_CAST(replace(planned_end_epoch,',','') AS BIGINT) AS planned_end_epoch,
  TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
  CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
FROM read_csv('{RAW}/Ride_data*.csv', header=true, union_by_name=true,
  null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
""")

con.sql(f"""
CREATE OR REPLACE VIEW alerts AS SELECT
  business_unit,
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  event_type, state_text, severity, source,
  strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_ts
FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)
""")


def show(title, sql):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    cells = [[("" if v is None else str(v)) for v in r] for r in rows]
    w = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * w[i] for i in range(len(cols))))
    for r in cells:
        print("  ".join(r[i].ljust(w[i]) for i in range(len(cols))))
    print(f"[{len(rows)} rows]")


def mkfbt():
    """Feedback joined to ride_data on the ONLY unique key: (trip_id, business_unit).
    Joining on trip_id alone fans out 15,480 rows (6,753 ids collide across BUs)."""
    con.sql("""CREATE OR REPLACE VIEW fbt AS
      SELECT f.*, t.office, t.product_type, t.vendor_id, t.shift_type, t.trip_direction,
             t.trip_nodal, t.delay_reason, t.delay_minutes, t.on_time, t.route_source,
             t.is_driver_nc, t.is_cab_nc, t.actual_escort, t.noshow, t.cab_capacity,
             t.traveled_km, t.emp_planned, t.emp_actual
      FROM fb f JOIN trips t USING (trip_id, business_unit)""")


SECTIONS = {}


def section(name):
    def deco(fn):
        SECTIONS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------- 1. zero semantics
@section("zero")
def s_zero():
    show("1.1 Row counts + parse integrity", """
      SELECT count(*) n_rows,
             count(trip_id) trip_id_ok,
             count(stwid) stwid_ok,
             sum(CASE WHEN stwid=0 THEN 1 ELSE 0 END) stwid_zero,
             count(trip_ts) trip_ts_ok,
             count(created_ts) created_ts_ok,
             count(DISTINCT trip_id) distinct_trips,
             count(DISTINCT stwid) distinct_stwid
      FROM fb""")

    show("1.2 Marginal distribution of each rating (raw, 0 included)", """
      SELECT v AS rating,
        sum(CASE WHEN route_rating=v   THEN 1 ELSE 0 END) route,
        sum(CASE WHEN driver_rating=v  THEN 1 ELSE 0 END) driver,
        sum(CASE WHEN cab_rating=v     THEN 1 ELSE 0 END) cab,
        sum(CASE WHEN safety_rating=v  THEN 1 ELSE 0 END) safety,
        sum(CASE WHEN marshal_rating=v THEN 1 ELSE 0 END) marshal
      FROM fb, (SELECT unnest([0,1,2,3,4,5]) AS v) g
      GROUP BY v ORDER BY v""")

    show("1.3 JOINT distribution: how many zeros per row (n_zero out of 5)", """
      SELECT (CASE WHEN route_rating=0 THEN 1 ELSE 0 END)
            +(CASE WHEN driver_rating=0 THEN 1 ELSE 0 END)
            +(CASE WHEN cab_rating=0 THEN 1 ELSE 0 END)
            +(CASE WHEN safety_rating=0 THEN 1 ELSE 0 END)
            +(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END) AS n_zero,
        count(*) n_rows, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("1.4 Which dimensions are zero together (top 15 zero-patterns)", """
      SELECT concat(
          CASE WHEN route_rating=0   THEN 'R' ELSE '.' END,
          CASE WHEN driver_rating=0  THEN 'D' ELSE '.' END,
          CASE WHEN cab_rating=0     THEN 'C' ELSE '.' END,
          CASE WHEN safety_rating=0  THEN 'S' ELSE '.' END,
          CASE WHEN marshal_rating=0 THEN 'M' ELSE '.' END) AS zero_pattern,
        count(*) n_rows, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
      FROM fb GROUP BY 1 ORDER BY n_rows DESC LIMIT 15""")

    show("1.5 KEY TEST: on rows where marshal=0, what are the OTHER ratings? "
         "(if 0 were genuine, the others would be low too)", """
      SELECT CASE WHEN marshal_rating=0 THEN 'marshal=0' ELSE 'marshal>=1' END AS grp,
        count(*) n,
        round(avg(route_rating),3)  avg_route_raw,
        round(avg(driver_rating),3) avg_driver_raw,
        round(avg(cab_rating),3)    avg_cab_raw,
        round(avg(safety_rating),3) avg_safety_raw,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),3) avg_route_ex0
      FROM fb WHERE route_rating IS NOT NULL GROUP BY 1""")

    show("1.6 Same test for safety=0 rows", """
      SELECT CASE WHEN safety_rating=0 THEN 'safety=0' ELSE 'safety>=1' END AS grp,
        count(*) n,
        round(avg(CASE WHEN route_rating>0  THEN route_rating  END),3) avg_route_ex0,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),3) avg_driver_ex0,
        round(avg(CASE WHEN cab_rating>0    THEN cab_rating    END),3) avg_cab_ex0,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),3) avg_marshal_ex0
      FROM fb GROUP BY 1""")

    show("1.7 ALL-ZERO rows: are they real 'unrated' submissions?", """
      SELECT count(*) all_zero_rows,
        round(100.0*count(*)/(SELECT count(*) FROM fb),2) pct_of_all,
        count(DISTINCT trip_id) trips, count(DISTINCT stwid) employees
      FROM fb
      WHERE route_rating=0 AND driver_rating=0 AND cab_rating=0
        AND safety_rating=0 AND marshal_rating=0""")

    show("1.8 IMPACT: avg rating with vs without 0s (metric definition matters)", """
      SELECT 'route' dim, round(avg(route_rating),3) incl_zero,
             round(avg(CASE WHEN route_rating>0 THEN route_rating END),3) excl_zero,
             sum(CASE WHEN route_rating=0 THEN 1 ELSE 0 END) n_zero, count(*) n
      FROM fb UNION ALL
      SELECT 'driver', round(avg(driver_rating),3),
             round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),3),
             sum(CASE WHEN driver_rating=0 THEN 1 ELSE 0 END), count(*) FROM fb UNION ALL
      SELECT 'cab', round(avg(cab_rating),3),
             round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),3),
             sum(CASE WHEN cab_rating=0 THEN 1 ELSE 0 END), count(*) FROM fb UNION ALL
      SELECT 'safety', round(avg(safety_rating),3),
             round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),3),
             sum(CASE WHEN safety_rating=0 THEN 1 ELSE 0 END), count(*) FROM fb UNION ALL
      SELECT 'marshal', round(avg(marshal_rating),3),
             round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),3),
             sum(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END), count(*) FROM fb""")

    show("1.9 ARTIFACT CHECK: does marshal=0 line up with escort/marshal actually "
         "being present on the trip? (join ride_data.actual_escort)", """
      SELECT t.actual_escort, count(*) n,
        sum(CASE WHEN f.marshal_rating=0 THEN 1 ELSE 0 END) marshal_zero,
        round(100.0*sum(CASE WHEN f.marshal_rating=0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_zero,
        round(avg(CASE WHEN f.marshal_rating>0 THEN f.marshal_rating END),3) avg_marshal_ex0
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY n DESC""")

    show("1.10 ARTIFACT CHECK: is marshal=0 vs >0 a NIGHT-shift thing?", """
      SELECT t.trip_nodal, count(*) n,
        round(100.0*sum(CASE WHEN f.marshal_rating=0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_zero
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      GROUP BY 1 HAVING count(*)>=500 ORDER BY n DESC""")

    show("1.11 JOIN-KEY INTEGRITY: trip_id is NOT unique in ride_data; "
         "(trip_id,business_unit) is. Naive join inflates feedback by 3%", """
      SELECT 'ride rows'                AS metric, count(*) v FROM trips
      UNION ALL SELECT 'distinct trip_id',            count(DISTINCT trip_id) FROM trips
      UNION ALL SELECT 'distinct (trip_id,BU)',
                       count(DISTINCT (trip_id::VARCHAR||'|'||business_unit)) FROM trips
      UNION ALL SELECT 'trip_ids appearing 2x',
                       (SELECT count(*) FROM (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1))
      UNION ALL SELECT 'fb rows',                     count(*) FROM fb
      UNION ALL SELECT 'fb JOIN ON trip_id only',
                       (SELECT count(*) FROM fb f JOIN trips t USING (trip_id))
      UNION ALL SELECT 'fb JOIN ON trip_id+BU',
                       (SELECT count(*) FROM fb f JOIN trips t USING (trip_id,business_unit))
      UNION ALL SELECT 'fb rows on colliding trip_ids',
                       (SELECT count(*) FROM fb WHERE trip_id IN
                         (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1))""")


# ---------------------------------------------------------------- 2. response rate
@section("resp")
def s_resp():
    show("2.1 Feedback rows / trips / response rate by month", """
      WITH t AS (SELECT month, count(*) trips, count(DISTINCT trip_id) dtrips FROM trips GROUP BY 1),
           f AS (SELECT month, count(*) fb_rows, count(DISTINCT trip_id) rated_trips FROM fb GROUP BY 1)
      SELECT t.month, t.trips, t.dtrips, f.fb_rows, f.rated_trips,
        round(100.0*f.rated_trips/t.dtrips,2) pct_trips_rated,
        round(1.0*f.fb_rows/f.rated_trips,3) responses_per_rated_trip
      FROM t JOIN f USING (month) ORDER BY 1""")

    show("2.2 Trip-level rated coverage via LEFT JOIN (guards against month mismatch)", """
      SELECT t.month, count(*) trips,
        sum(CASE WHEN r.trip_id IS NOT NULL THEN 1 ELSE 0 END) rated,
        round(100.0*sum(CASE WHEN r.trip_id IS NOT NULL THEN 1 ELSE 0 END)/count(*),2) pct_rated
      FROM (SELECT DISTINCT trip_id, business_unit, month FROM trips) t
      LEFT JOIN (SELECT DISTINCT trip_id, business_unit FROM fb) r USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY 1""")

    show("2.3 Response rate by BU x month (trip-level)", """
      SELECT t.business_unit, count(*) trips,
        round(100.0*sum(CASE WHEN t.month='2026-05-01' AND r.trip_id IS NOT NULL THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN t.month='2026-05-01' THEN 1 ELSE 0 END),0),2) may,
        round(100.0*sum(CASE WHEN t.month='2026-06-01' AND r.trip_id IS NOT NULL THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN t.month='2026-06-01' THEN 1 ELSE 0 END),0),2) jun,
        round(100.0*sum(CASE WHEN t.month='2026-07-01' AND r.trip_id IS NOT NULL THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN t.month='2026-07-01' THEN 1 ELSE 0 END),0),2) jul
      FROM (SELECT DISTINCT trip_id, month, business_unit FROM trips) t
      LEFT JOIN (SELECT DISTINCT trip_id, business_unit FROM fb) r USING (trip_id, business_unit)
      GROUP BY 1 HAVING count(*)>=500 ORDER BY trips DESC""")

    show("2.4 ARTIFACT CHECK: do fb trip_ids even exist in ride_data?", """
      SELECT count(*) fb_rows,
        sum(CASE WHEN t.trip_id IS NOT NULL THEN 1 ELSE 0 END) n_matched,
        round(100.0*sum(CASE WHEN t.trip_id IS NOT NULL THEN 1 ELSE 0 END)/count(*),3) pct_matched
      FROM fb f LEFT JOIN (SELECT DISTINCT trip_id, business_unit FROM trips) t
        USING (trip_id, business_unit)""")

    show("2.5 Feedback lag: creation_time - trip_date (hours)", """
      SELECT round(median(date_diff('minute',trip_ts,created_ts))/60.0,2) median_h,
        round(avg(date_diff('minute',trip_ts,created_ts))/60.0,2) mean_h,
        sum(CASE WHEN created_ts<trip_ts THEN 1 ELSE 0 END) submitted_BEFORE_trip,
        round(100.0*sum(CASE WHEN created_ts<trip_ts THEN 1 ELSE 0 END)/count(*),2) pct_before,
        count(*) n
      FROM fb WHERE trip_ts IS NOT NULL AND created_ts IS NOT NULL""")


# ---------------------------------------------------------------- 3. trend by month
@section("trend")
def s_trend():
    show("3.1 Mean rating by month, EXCLUDING 0 per-dimension (n shown)", """
      SELECT month,
        count(*) fb_rows,
        round(avg(CASE WHEN route_rating>0   THEN route_rating   END),4) route,
        round(avg(CASE WHEN driver_rating>0  THEN driver_rating  END),4) driver,
        round(avg(CASE WHEN cab_rating>0     THEN cab_rating     END),4) cab,
        round(avg(CASE WHEN safety_rating>0  THEN safety_rating  END),4) safety,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal,
        sum(CASE WHEN marshal_rating>0 THEN 1 ELSE 0 END) n_marshal
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("3.2 Same, but INCLUDING 0 (the naive metric) -- shows how much definition matters", """
      SELECT month, count(*) n,
        round(avg(route_rating),4) route, round(avg(driver_rating),4) driver,
        round(avg(cab_rating),4) cab, round(avg(safety_rating),4) safety,
        round(avg(marshal_rating),4) marshal
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("3.3 Detractor rate (rating 1-2) by month, per dimension", """
      SELECT month,
        round(100.0*sum(CASE WHEN route_rating  BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN route_rating>0 THEN 1 ELSE 0 END),0),3) route_det,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) driver_det,
        round(100.0*sum(CASE WHEN cab_rating    BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN cab_rating>0 THEN 1 ELSE 0 END),0),3) cab_det,
        round(100.0*sum(CASE WHEN safety_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN safety_rating>0 THEN 1 ELSE 0 END),0),3) safety_det,
        round(100.0*sum(CASE WHEN marshal_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN marshal_rating>0 THEN 1 ELSE 0 END),0),3) marshal_det,
        count(*) n
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("3.4 Marshal coverage by month -- is the marshal=0 share itself moving?", """
      SELECT month, count(*) n,
        sum(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END) marshal_zero,
        round(100.0*sum(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_zero
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("3.5 Weekly trend on the dimension that moved most (all dims, weekly)", """
      SELECT date_trunc('week',trip_ts)::DATE wk, count(*) n,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal
      FROM fb WHERE trip_ts IS NOT NULL GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")


# ---------------------------------------------------------------- 4. cuts
@section("cuts")
def s_cuts():
    mkfbt()

    show("4.1 By VENDOR (n>=500) -- mean + dispersion", """
      SELECT vendor_id, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(stddev_samp(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver_sd,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) driver_det_pct
      FROM fbt GROUP BY 1 HAVING count(*)>=500 ORDER BY driver ASC""")

    show("4.2 By OFFICE (n>=500)", """
      SELECT office, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal
      FROM fbt GROUP BY 1 HAVING count(*)>=500 ORDER BY driver ASC LIMIT 25""")

    show("4.3 By PRODUCT_TYPE", """
      SELECT product_type, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route
      FROM fbt GROUP BY 1 HAVING count(*)>=500 ORDER BY n DESC""")

    show("4.4 By SHIFT_TYPE band (top 30 by n)", """
      SELECT shift_type, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal
      FROM fbt GROUP BY 1 HAVING count(*)>=500 ORDER BY n DESC LIMIT 30""")

    show("4.5 By hour-of-day of the trip (night vs day)", """
      SELECT hour(trip_ts) hr, count(*) n,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(100.0*sum(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_zero
      FROM fbt WHERE trip_ts IS NOT NULL GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")

    show("4.6 SAFETY vs MARSHAL on night trips (trip_nodal / escort split, n>=500)", """
      SELECT CASE WHEN hour(trip_ts) BETWEEN 22 AND 23 OR hour(trip_ts) BETWEEN 0 AND 5
                  THEN 'NIGHT(22-05)' ELSE 'DAY' END AS band,
        actual_escort, count(*) n,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END)
             -avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) safety_minus_marshal,
        round(100.0*sum(CASE WHEN marshal_rating=0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_zero
      FROM fbt WHERE trip_ts IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")

    show("4.7 ARTIFACT CHECK: is marshal_rating>0 only present when escort=true?", """
      SELECT actual_escort, count(*) n,
        sum(CASE WHEN marshal_rating>0 THEN 1 ELSE 0 END) marshal_rated,
        round(100.0*sum(CASE WHEN marshal_rating>0 THEN 1 ELSE 0 END)/count(*),2) pct_marshal_rated
      FROM fbt GROUP BY 1 ORDER BY n DESC""")


# ---------------------------------------------------------------- 5. delay linkage
@section("delay")
def s_delay():
    mkfbt()
    show("5.1 On-time (<=5min) vs delayed", """
      SELECT CASE WHEN on_time=1 THEN 'ON_TIME(<=5)' ELSE 'DELAYED(>5)' END grp, count(*) n,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) driver_det_pct
      FROM fbt WHERE delay_minutes IS NOT NULL GROUP BY 1""")

    show("5.2 Rating by delay bucket", """
      SELECT CASE WHEN delay_minutes<=0 THEN 'a <=0'
                  WHEN delay_minutes<=5 THEN 'b 1-5'
                  WHEN delay_minutes<=15 THEN 'c 6-15'
                  WHEN delay_minutes<=30 THEN 'd 16-30'
                  WHEN delay_minutes<=60 THEN 'e 31-60'
                  ELSE 'f >60' END bucket, count(*) n,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety
      FROM fbt WHERE delay_minutes IS NOT NULL GROUP BY 1 ORDER BY 1""")

    show("5.3 By DELAY_REASON (n>=500) -- 'a DRIVER delay costs X pts vs TRAFFIC'", """
      SELECT coalesce(delay_reason,'<NULL>') reason, count(*) n,
        round(avg(delay_minutes),2) avg_delay_min,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) driver_det_pct
      FROM fbt GROUP BY 1 HAVING count(*)>=500 ORDER BY driver ASC""")

    show("5.4 CONFOUND CHECK: hold delay magnitude constant, compare reasons "
         "(only delayed >15 min, n>=500)", """
      SELECT coalesce(delay_reason,'<NULL>') reason, count(*) n,
        round(avg(delay_minutes),1) avg_delay_min,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route
      FROM fbt WHERE delay_minutes>15 GROUP BY 1 HAVING count(*)>=500 ORDER BY driver ASC""")

    show("5.5 Non-compliance flags (is_driver_nc / is_cab_nc) vs rating", """
      SELECT is_driver_nc, is_cab_nc, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety
      FROM fbt GROUP BY 1,2 HAVING count(*)>=500 ORDER BY n DESC""")

    show("5.6 Correlation matrix between dimensions (excl 0 rows on both sides)", """
      SELECT round(corr(route_rating,driver_rating),4) route_driver,
             round(corr(route_rating,cab_rating),4) route_cab,
             round(corr(driver_rating,cab_rating),4) driver_cab,
             round(corr(driver_rating,safety_rating),4) driver_safety,
             round(corr(cab_rating,safety_rating),4) cab_safety,
             count(*) n
      FROM fb WHERE route_rating>0 AND driver_rating>0 AND cab_rating>0 AND safety_rating>0""")

    show("5.7 corr(delay_minutes, rating) -- is delay even predictive?", """
      SELECT round(corr(delay_minutes, driver_rating),5) driver,
             round(corr(delay_minutes, route_rating),5) route,
             round(corr(delay_minutes, cab_rating),5) cab, count(*) n
      FROM fbt WHERE delay_minutes IS NOT NULL AND delay_minutes BETWEEN -60 AND 240
        AND driver_rating>0 AND route_rating>0 AND cab_rating>0""")


# ---------------------------------------------------------------- 6. alerts
@section("alerts")
def s_alerts():
    mkfbt()
    show("6.1 Alerts join coverage", """
      SELECT count(*) alert_rows, count(DISTINCT trip_id) alert_trips,
        count(DISTINCT event_type) event_types
      FROM alerts""")

    show("6.2 Feedback on trips WITH vs WITHOUT any alert", """
      WITH a AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE trip_id IS NOT NULL)
      SELECT CASE WHEN a.trip_id IS NOT NULL THEN 'HAS_ALERT' ELSE 'no_alert' END grp,
        count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(avg(CASE WHEN safety_rating>0 THEN safety_rating END),4) safety,
        round(avg(CASE WHEN cab_rating>0 THEN cab_rating END),4) cab,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(100.0*sum(CASE WHEN safety_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN safety_rating>0 THEN 1 ELSE 0 END),0),3) safety_det_pct
      FROM fb f LEFT JOIN a USING (trip_id, business_unit) GROUP BY 1""")

    show("6.3 By alert EVENT_TYPE (n>=500)", """
      SELECT a.event_type, count(*) n, count(DISTINCT f.trip_id) trips,
        round(avg(CASE WHEN f.driver_rating>0 THEN f.driver_rating END),4) driver,
        round(avg(CASE WHEN f.safety_rating>0 THEN f.safety_rating END),4) safety,
        round(avg(CASE WHEN f.route_rating>0 THEN f.route_rating END),4) route,
        round(avg(CASE WHEN f.cab_rating>0 THEN f.cab_rating END),4) cab
      FROM fb f JOIN (SELECT DISTINCT trip_id, business_unit, event_type FROM alerts) a
        USING (trip_id, business_unit)
      GROUP BY 1 HAVING count(*)>=500 ORDER BY safety ASC""")

    show("6.4 By alert SEVERITY (note the stray 'False')", """
      SELECT a.severity, count(*) n,
        round(avg(CASE WHEN f.driver_rating>0 THEN f.driver_rating END),4) driver,
        round(avg(CASE WHEN f.safety_rating>0 THEN f.safety_rating END),4) safety
      FROM fb f JOIN (SELECT DISTINCT trip_id, business_unit, severity FROM alerts) a
        USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY n DESC""")

    show("6.5 PERSONAL alerts: alert on the SAME employee+trip vs alert elsewhere on trip", """
      WITH pa AS (SELECT DISTINCT trip_id, business_unit, stwid FROM alerts
                  WHERE stwid IS NOT NULL AND stwid<>0),
           ta AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE trip_id IS NOT NULL)
      SELECT CASE WHEN pa.trip_id IS NOT NULL THEN 'alert_ON_THIS_EMPLOYEE'
                  WHEN ta.trip_id IS NOT NULL THEN 'alert_on_trip_other_emp'
                  ELSE 'no_alert' END grp,
        count(*) n,
        round(avg(CASE WHEN f.safety_rating>0 THEN f.safety_rating END),4) safety,
        round(avg(CASE WHEN f.driver_rating>0 THEN f.driver_rating END),4) driver
      FROM fb f
      LEFT JOIN pa ON pa.trip_id=f.trip_id AND pa.business_unit=f.business_unit AND pa.stwid=f.stwid
      LEFT JOIN ta ON ta.trip_id=f.trip_id AND ta.business_unit=f.business_unit
      WHERE f.stwid IS NOT NULL AND f.stwid<>0
      GROUP BY 1 ORDER BY n DESC""")

    show("6.6 CONFOUND: alert trips are also more delayed? control for on_time", """
      WITH a AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE trip_id IS NOT NULL)
      SELECT t.on_time, CASE WHEN a.trip_id IS NOT NULL THEN 'HAS_ALERT' ELSE 'no_alert' END grp,
        count(*) n, round(avg(t.delay_minutes),2) avg_delay,
        round(avg(CASE WHEN f.safety_rating>0 THEN f.safety_rating END),4) safety,
        round(avg(CASE WHEN f.driver_rating>0 THEN f.driver_rating END),4) driver
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      LEFT JOIN a ON a.trip_id=f.trip_id AND a.business_unit=f.business_unit
      GROUP BY 1,2 ORDER BY 1,2""")


# ---------------------------------------------------------------- 7. raters
@section("raters")
def s_raters():
    mkfbt()
    show("7.1 Rater activity distribution (stwid<>0)", """
      WITH r AS (SELECT stwid, count(*) n FROM fb WHERE stwid IS NOT NULL AND stwid<>0 GROUP BY 1)
      SELECT count(*) raters, round(avg(n),2) avg_reviews, median(n) median_reviews,
        max(n) max_reviews, sum(n) total_rows FROM r""")

    show("7.2 Repeat low-raters vs one-off complaints "
         "(low = driver_rating 1-2, denominator = rated driver rows)", """
      WITH r AS (
        SELECT stwid, count(*) n,
               sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END) lows,
               round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),3) avg_driver
        FROM fb WHERE stwid IS NOT NULL AND stwid<>0 AND driver_rating>0 GROUP BY 1)
      SELECT CASE WHEN lows=0 THEN 'a never_low'
                  WHEN lows=1 THEN 'b one_off (1 low)'
                  WHEN lows BETWEEN 2 AND 4 THEN 'c repeat (2-4)'
                  ELSE 'd chronic (5+)' END grp,
        count(*) raters, sum(n) reviews, sum(lows) low_ratings,
        round(100.0*sum(lows)/sum(sum(lows)) OVER (),2) pct_of_all_lows,
        round(avg(n),2) avg_reviews_per_rater
      FROM r GROUP BY 1 ORDER BY 1""")

    show("7.3 CONCENTRATION: what share of all low driver ratings come from the "
         "top 1% most-prolific low-raters?", """
      WITH r AS (
        SELECT stwid, sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END) lows
        FROM fb WHERE stwid IS NOT NULL AND stwid<>0 AND driver_rating>0 GROUP BY 1),
      ranked AS (SELECT *, ntile(100) OVER (ORDER BY lows DESC) pct FROM r WHERE lows>0)
      SELECT CASE WHEN pct<=1 THEN 'top 1%' WHEN pct<=5 THEN 'top 5%'
                  WHEN pct<=10 THEN 'top 10%' ELSE 'rest' END b,
        count(*) raters, sum(lows) lows,
        round(100.0*sum(lows)/sum(sum(lows)) OVER (),2) pct_of_lows
      FROM ranked GROUP BY 1 ORDER BY lows DESC""")

    show("7.4 ARTIFACT CHECK: are chronic low-raters riding objectively worse trips?", """
      WITH r AS (
        SELECT stwid, sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END) lows,
               count(*) n
        FROM fb WHERE stwid IS NOT NULL AND stwid<>0 AND driver_rating>0 GROUP BY 1)
      SELECT CASE WHEN r.lows=0 THEN 'a never_low' WHEN r.lows=1 THEN 'b one_off'
                  WHEN r.lows<=4 THEN 'c repeat' ELSE 'd chronic 5+' END grp,
        count(*) fb_rows,
        round(avg(t.delay_minutes),2) avg_delay_min,
        round(100.0*avg(t.on_time),2) pct_on_time,
        round(avg(t.traveled_km),2) avg_km
      FROM fb f JOIN r USING (stwid) JOIN trips t USING (trip_id, business_unit)
      WHERE f.driver_rating>0 GROUP BY 1 ORDER BY 1""")

    show("7.5 Duplicate submissions: same stwid+trip rated more than once?", """
      WITH d AS (SELECT trip_id, stwid, count(*) c FROM fb
                 WHERE stwid IS NOT NULL AND stwid<>0 GROUP BY 1,2)
      SELECT c AS submissions_per_emp_trip, count(*) pairs
      FROM d GROUP BY 1 ORDER BY 1 LIMIT 10""")


# ---------------------------------------------------------------- 8. confounds
@section("confound")
def s_confound():
    mkfbt()

    show("8.1 KILLER: response rate vs rating by BU -- the BUs that rate least "
         "are the BUs that rate worst. Company avg is a coverage artifact.", """
      WITH t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           f AS (SELECT business_unit, count(*) fb_rows,
                   count(DISTINCT trip_id) rated_trips,
                   avg(CASE WHEN driver_rating>0 THEN driver_rating END) driver,
                   100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
                     /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0) det
                 FROM fb GROUP BY 1)
      SELECT t.business_unit, t.trips, f.fb_rows,
        round(100.0*f.rated_trips/t.trips,2) response_rate_pct,
        round(100.0*t.trips/sum(t.trips) OVER (),2) pct_of_TRIPS,
        round(100.0*f.fb_rows/sum(f.fb_rows) OVER (),2) pct_of_FEEDBACK,
        round(f.driver,4) driver, round(f.det,3) driver_det_pct
      FROM t JOIN f USING (business_unit) ORDER BY response_rate_pct DESC""")

    show("8.2 Company score: feedback-weighted (what the dashboard shows) vs "
         "trip-weighted (what employees actually experience)", """
      WITH t AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1),
           f AS (SELECT business_unit,
                   avg(CASE WHEN driver_rating>0 THEN driver_rating END) driver,
                   avg(CASE WHEN route_rating>0 THEN route_rating END) route,
                   100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
                     /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0) det,
                   count(*) n FROM fb GROUP BY 1)
      SELECT round(sum(f.driver*f.n)/sum(f.n),4)      driver_feedback_wtd,
             round(sum(f.driver*t.trips)/sum(t.trips),4) driver_trip_wtd,
             round(sum(f.route*f.n)/sum(f.n),4)       route_feedback_wtd,
             round(sum(f.route*t.trips)/sum(t.trips),4)  route_trip_wtd,
             round(sum(f.det*f.n)/sum(f.n),4)         det_feedback_wtd,
             round(sum(f.det*t.trips)/sum(t.trips),4)    det_trip_wtd
      FROM f JOIN t USING (business_unit)""")

    show("8.3 CONFOUND: are the worst vendors just the low-response BUs? "
         "vendor x BU footprint for the 4 worst vendors", """
      SELECT vendor_id, business_unit, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver
      FROM fbt
      WHERE vendor_id IN ('Meera Pavlov Travel','Priya Mikhailov Travel',
                          'Isha Mikhailov Travel','Sneha Mikhailov Travel',
                          'Rahul Orlov Travel','Divya Kozlov Travel')
      GROUP BY 1,2 ORDER BY vendor_id, n DESC""")

    show("8.4 Vendor spread WITHIN a single BU (removes BU confound), n>=500", """
      SELECT business_unit, vendor_id, count(*) n,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(stddev_samp(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver_sd,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) det_pct
      FROM fbt WHERE business_unit='pinnacle-Slc'
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY det_pct DESC""")

    show("8.5 STRATIFIED delay-reason: compare reasons INSIDE each delay bucket "
         "(isolates reason from magnitude), n>=500", """
      SELECT CASE WHEN delay_minutes<=15 THEN 'c 6-15'
                  WHEN delay_minutes<=30 THEN 'd 16-30'
                  ELSE 'e 31+' END bucket,
        delay_reason, count(*) n, round(avg(delay_minutes),1) avg_min,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route,
        round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver
      FROM fbt WHERE delay_minutes>5 AND delay_reason IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1, route ASC""")

    show("8.6 CEILING EFFECT: mean barely moves, detractor rate moves a lot. "
         "Relative swing of each metric May->June (route)", """
      SELECT month, count(*) n,
        round(avg(CASE WHEN route_rating>0 THEN route_rating END),4) route_mean,
        round(100.0*sum(CASE WHEN route_rating=5 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN route_rating>0 THEN 1 ELSE 0 END),0),3) pct_5star,
        round(100.0*sum(CASE WHEN route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN route_rating>0 THEN 1 ELSE 0 END),0),3) det_pct,
        sum(CASE WHEN route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END) n_detractors
      FROM fb GROUP BY 1 ORDER BY 1""")

    show("8.7 Is the June route-detractor spike concentrated where the OTA dip was? "
         "(LOGIN vs LOGOUT, BUS vs CAB)", """
      SELECT trip_direction, product_type,
        count(*) n,
        round(100.0*sum(CASE WHEN month='2026-05-01' AND route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN month='2026-05-01' AND route_rating>0 THEN 1 ELSE 0 END),0),3) may_det,
        round(100.0*sum(CASE WHEN month='2026-06-01' AND route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN month='2026-06-01' AND route_rating>0 THEN 1 ELSE 0 END),0),3) jun_det,
        round(100.0*sum(CASE WHEN month='2026-07-01' AND route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN month='2026-07-01' AND route_rating>0 THEN 1 ELSE 0 END),0),3) jul_det
      FROM fbt WHERE product_type IN ('CAB','BUS')
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")

    show("8.8 SMALL-N GUARD: the marshal=5.0 cells in the hour cut are noise", """
      SELECT hour(trip_ts) hr, count(*) n_total,
        sum(CASE WHEN marshal_rating>0 THEN 1 ELSE 0 END) n_marshal_rated,
        round(avg(CASE WHEN marshal_rating>0 THEN marshal_rating END),4) marshal
      FROM fbt WHERE trip_ts IS NOT NULL AND hour(trip_ts) IN (8,9,10,15,16,17)
      GROUP BY 1 ORDER BY 1""")

    show("8.9 OVER_SPEEDING sanity: does an overspeeding alert lower SAFETY rating?", """
      WITH a AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE event_type='OVER_SPEEDING')
      SELECT CASE WHEN a.trip_id IS NOT NULL THEN 'OVERSPEED_ALERT' ELSE 'none' END grp,
        count(*) n,
        round(avg(CASE WHEN f.safety_rating>0 THEN f.safety_rating END),4) safety,
        round(100.0*sum(CASE WHEN f.safety_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN f.safety_rating>0 THEN 1 ELSE 0 END),0),3) safety_det_pct
      FROM fb f LEFT JOIN a USING (trip_id, business_unit) GROUP BY 1""")


# ---------------------------------------------------------------- 9. response bias
@section("bias")
def s_bias():
    show("9.1 SELF-SELECTION TEST: within each BU, are RATED trips objectively "
         "different from UNRATED trips?", """
      WITH r AS (SELECT DISTINCT trip_id, business_unit FROM fb)
      SELECT t.business_unit,
        CASE WHEN r.trip_id IS NOT NULL THEN 'rated' ELSE 'UNRATED' END grp,
        count(*) trips, round(100.0*avg(t.on_time),2) pct_on_time,
        round(avg(t.delay_minutes),2) avg_delay_min,
        round(100.0*sum(CASE WHEN t.delay_minutes>60 THEN 1 ELSE 0 END)/count(*),2) pct_gt60
      FROM trips t LEFT JOIN r USING (trip_id, business_unit)
      GROUP BY 1,2 ORDER BY 1,2""")

    show("9.2 SIMPSON'S PARADOX: pooled, unrated trips look BETTER; "
         "inside pinnacle-Slc they are far worse", """
      WITH r AS (SELECT DISTINCT trip_id, business_unit FROM fb)
      SELECT 'ALL BUs pooled' AS scope_name,
        CASE WHEN r.trip_id IS NOT NULL THEN 'rated' ELSE 'UNRATED' END grp,
        count(*) trips, round(100.0*avg(t.on_time),2) pct_on_time,
        round(avg(t.delay_minutes),2) avg_delay
      FROM trips t LEFT JOIN r USING (trip_id, business_unit) GROUP BY 1,2
      UNION ALL
      SELECT 'pinnacle-Slc only',
        CASE WHEN r.trip_id IS NOT NULL THEN 'rated' ELSE 'UNRATED' END,
        count(*), round(100.0*avg(t.on_time),2), round(avg(t.delay_minutes),2)
      FROM trips t LEFT JOIN r USING (trip_id, business_unit)
      WHERE t.business_unit='pinnacle-Slc' GROUP BY 1,2
      ORDER BY 1,2""")

    show("9.3 DECOUPLING: objective OTA vs perceived detractor rate, by BU", """
      WITH t AS (SELECT business_unit, count(*) trips, 100.0*avg(on_time) ota FROM trips GROUP BY 1),
           f AS (SELECT business_unit, count(*) n,
                  100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
                    /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0) det,
                  100.0*sum(CASE WHEN route_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
                    /nullif(sum(CASE WHEN route_rating>0 THEN 1 ELSE 0 END),0) rdet
                 FROM fb GROUP BY 1)
      SELECT t.business_unit, t.trips, round(t.ota,2) objective_OTA_pct, f.n fb_rows,
        round(f.det,3) driver_det_pct, round(f.rdet,3) route_det_pct
      FROM t JOIN f USING (business_unit) ORDER BY t.ota DESC""")

    show("9.4 Submission lag is bimodal by BU (two different capture mechanisms)", """
      SELECT business_unit, count(*) n,
        round(median(date_diff('minute',trip_ts,created_ts))/60.0,2) median_lag_h,
        sum(CASE WHEN created_ts<trip_ts THEN 1 ELSE 0 END) before_trip,
        round(100.0*sum(CASE WHEN created_ts<trip_ts THEN 1 ELSE 0 END)/count(*),2) pct_before
      FROM fb GROUP BY 1 ORDER BY median_lag_h DESC""")

    show("9.5 Does lag explain the BU gap? compare BUs INSIDE the same lag band", """
      SELECT business_unit,
        CASE WHEN date_diff('minute',trip_ts,created_ts)<0 THEN 'a before_trip'
             WHEN date_diff('minute',trip_ts,created_ts)<60 THEN 'b <1h'
             WHEN date_diff('minute',trip_ts,created_ts)<360 THEN 'c 1-6h'
             ELSE 'd 6h+' END lag_band,
        count(*) n, round(avg(CASE WHEN driver_rating>0 THEN driver_rating END),4) driver,
        round(100.0*sum(CASE WHEN driver_rating BETWEEN 1 AND 2 THEN 1 ELSE 0 END)
              /nullif(sum(CASE WHEN driver_rating>0 THEN 1 ELSE 0 END),0),3) det_pct
      FROM fb GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 2,1""")

    show("9.6 Distinct raters vs feedback volume by BU", """
      SELECT business_unit, count(DISTINCT stwid) raters, count(*) fb_rows,
        round(1.0*count(*)/count(DISTINCT stwid),2) rows_per_rater
      FROM fb WHERE stwid<>0 GROUP BY 1 ORDER BY raters DESC""")


if __name__ == "__main__":
    want = sys.argv[1:] or list(SECTIONS)
    for k in want:
        SECTIONS[k]()
