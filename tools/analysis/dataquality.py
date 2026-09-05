#!/usr/bin/env python
"""
DATA QUALITY & INTEGRITY -- exhaustive profile of the MoveInSync assessment dataset.
Every number printed here comes from a query actually executed against DuckDB.

Run:  .venv/bin/python tools/analysis/dataquality.py [stage]
Stages: profile, refint, dupes, impossible, dates, drift, categorical, whitespace, impact, all
"""
import sys, os, textwrap
import duckdb

RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw"
con = duckdb.connect()
con.sql("SET preserve_insertion_order=false")

RIDE_GLOB = f"{RAW}/Ride_data*.csv"

def hdr(t):
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)

def show(sql, title=None, maxw=200, rows=200):
    if title:
        print(f"\n--- {title} ---")
    r = con.sql(sql)
    r.show(max_width=maxw, max_rows=rows)
    return r

# ----------------------------------------------------------------------------------
# RAW (all-varchar) views -- nothing is cast, so we can measure cast failure honestly
# ----------------------------------------------------------------------------------
con.sql(f"""
CREATE OR REPLACE VIEW ride_raw AS
SELECT *, regexp_extract(filename, '(may|June|July)_2026', 1) AS src_month
FROM read_csv('{RIDE_GLOB}', header=true, union_by_name=true, null_padding=true,
              ignore_errors=true, all_varchar=true, sample_size=-1, filename=true)
""")
con.sql(f"""
CREATE OR REPLACE VIEW alerts_raw AS
SELECT * FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true, sample_size=-1)
""")
con.sql(f"""
CREATE OR REPLACE VIEW bill_raw AS
SELECT * FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true, sample_size=-1)
""")
con.sql(f"""
CREATE OR REPLACE VIEW emp_raw AS
SELECT * FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true, sample_size=-1)
""")
con.sql(f"""
CREATE OR REPLACE VIEW fb_raw AS
SELECT * FROM read_csv('{RAW}/trip_feedback.csv', header=true, all_varchar=true, sample_size=-1)
""")

# ----------------------------------------------------------------------------------
# Typed views
# ----------------------------------------------------------------------------------
con.sql("""
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  business_unit, office, product_type, vendor_id, trip_direction, shift_type,
  coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, actual_cab_fuel_type, route_source,
  planned_cab_registration, actual_cab_registration,
  strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
  date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
  src_month,
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
  TRY_CAST(replace(planned_end_epoch,',','')   AS BIGINT) AS planned_end_epoch,
  TRY_CAST(replace(actual_start_epoch,',','')  AS BIGINT) AS actual_start_epoch,
  TRY_CAST(replace(actual_end_epoch,',','')    AS BIGINT) AS actual_end_epoch,
  CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
FROM ride_raw
""")

con.sql("""
CREATE OR REPLACE VIEW bill AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  trip_id AS trip_id_raw,
  business_unit, office, vendor, contract, slab_name,
  TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS total_trip_km,
  TRY_CAST(replace(trip_cost,',','') AS DOUBLE) AS trip_cost,
  TRY_CAST(strptime(cycle_start,'%B %d, %Y, %I:%M %p') AS TIMESTAMP) AS cycle_start,
  TRY_CAST(strptime(cycle_end,'%B %d, %Y, %I:%M %p')   AS TIMESTAMP) AS cycle_end
FROM bill_raw
""")

con.sql("""
CREATE OR REPLACE VIEW emp AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  business_unit, office, product_type, shift_type, signintype, gender, emp_role,
  boarding_status, not_boarding_reason,
  TRY_CAST(is_no_show AS BOOLEAN) AS is_no_show,
  TRY_CAST(trip_date AS DATE) AS trip_date,
  TRY_CAST(planned_km AS DOUBLE) AS planned_km,
  TRY_CAST(traveled_km AS DOUBLE) AS traveled_km,
  TRY_CAST(planned_pickup_epoch AS DOUBLE) AS planned_pickup_epoch,
  TRY_CAST(planned_drop_epoch   AS DOUBLE) AS planned_drop_epoch,
  TRY_CAST(actual_pickup_epoch  AS DOUBLE) AS actual_pickup_epoch,
  TRY_CAST(actual_drop_epoch    AS DOUBLE) AS actual_drop_epoch
FROM emp_raw
""")

con.sql("""
CREATE OR REPLACE VIEW fb AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  business_unit, trip_type,
  TRY_CAST(strptime(trip_date,'%B %d, %Y, %I:%M %p') AS TIMESTAMP) AS trip_ts,
  TRY_CAST(strptime(creation_time,'%B %d, %Y, %I:%M %p') AS TIMESTAMP) AS creation_ts,
  TRY_CAST(route_rating AS INT) AS route_rating,
  TRY_CAST(driver_rating AS INT) AS driver_rating,
  TRY_CAST(cab_rating AS INT) AS cab_rating,
  TRY_CAST(safety_rating AS INT) AS safety_rating,
  TRY_CAST(marshal_rating AS INT) AS marshal_rating
FROM fb_raw
""")

con.sql("""
CREATE OR REPLACE VIEW alerts AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
  TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
  business_unit, event_id, event_type, state_text, severity, source,
  TRY_CAST(strptime(start_time,'%B %d, %Y, %I:%M %p') AS TIMESTAMP) AS start_ts,
  TRY_CAST(strptime(acknowledge_time,'%B %d, %Y, %I:%M %p') AS TIMESTAMP) AS ack_ts
FROM alerts_raw
""")


# ==================================================================================
# STAGE 1 : FULL COLUMN PROFILE PER FILE
# ==================================================================================
NUMERIC_HINT = {
 'ride': {'actual_cab_capacity':'INT','planned_km':'DOUBLE','traveled_km':'DOUBLE',
          'planned_start_epoch':'BIGINT_C','planned_end_epoch':'BIGINT_C',
          'actual_start_epoch':'BIGINT_C','actual_end_epoch':'BIGINT_C',
          'delay_minutes':'DOUBLE_C','plannedemployee_cnt':'INT','actualemployee_cnt':'INT',
          'noshow_cnt':'INT','trip_id':'BIGINT_C','actual_escort':'BOOLEAN',
          'is_driver_nc':'BOOLEAN','is_cab_nc':'BOOLEAN','trip_date':'DATE_B'},
 'alerts': {'trip_id':'BIGINT_C','stwid':'BIGINT_C','start_time':'TS_BM','acknowledge_time':'TS_BM'},
 'bill': {'trip_id':'BIGINT_C','total_trip_km':'DOUBLE_C','trip_cost':'DOUBLE_C',
          'cycle_start':'TS_BM','cycle_end':'TS_BM'},
 'emp': {'trip_id':'BIGINT_C','stwid':'BIGINT_C','planned_km':'DOUBLE','traveled_km':'DOUBLE',
         'planned_pickup_epoch':'DOUBLE','planned_drop_epoch':'DOUBLE',
         'actual_pickup_epoch':'DOUBLE','actual_drop_epoch':'DOUBLE',
         'is_no_show':'BOOLEAN','trip_date':'DATE_ISO'},
 'fb': {'trip_id':'BIGINT_C','stwid':'BIGINT_C','route_rating':'INT','driver_rating':'INT',
        'cab_rating':'INT','safety_rating':'INT','marshal_rating':'INT',
        'trip_date':'TS_BM','creation_time':'TS_BM'},
}

CAST_EXPR = {
 'INT':       "TRY_CAST({c} AS INT)",
 'BIGINT':    "TRY_CAST({c} AS BIGINT)",
 'BIGINT_C':  "TRY_CAST(replace({c},',','') AS BIGINT)",
 'DOUBLE':    "TRY_CAST({c} AS DOUBLE)",
 'DOUBLE_C':  "TRY_CAST(replace({c},',','') AS DOUBLE)",
 'BOOLEAN':   "TRY_CAST({c} AS BOOLEAN)",
 'DATE_B':    "TRY_CAST(strptime({c},'%B %d, %Y') AS DATE)",
 'DATE_ISO':  "TRY_CAST({c} AS DATE)",
 'TS_BM':     "TRY_CAST(strptime({c},'%B %d, %Y, %I:%M %p') AS TIMESTAMP)",
}

def profile(view, label, hint_key):
    cols = [r[0] for r in con.sql(f"DESCRIBE {view}").fetchall()]
    hints = NUMERIC_HINT.get(hint_key, {})
    total = con.sql(f"SELECT count(*) FROM {view}").fetchone()[0]
    print(f"\n### FILE PROFILE: {label}   (rows = {total:,})")
    rows = []
    for c in cols:
        if c in ('filename','src_month'):
            continue
        q = f'"{c}"'
        h = hints.get(c)
        if h:
            ce = CAST_EXPR[h].format(c=q)
            castfail = f"sum(CASE WHEN {q} IS NOT NULL AND {ce} IS NULL THEN 1 ELSE 0 END)"
            mn = f"min({ce})::VARCHAR"; mx = f"max({ce})::VARCHAR"
        else:
            castfail = "0"; mn = f"min({q})"; mx = f"max({q})"
        sql = f"""
        SELECT '{c}' AS col,
               '{h or "VARCHAR"}' AS target_type,
               count(*) - count({q}) AS nulls,
               round(100.0*(count(*)-count({q}))/count(*),3) AS null_pct,
               count(DISTINCT {q}) AS n_distinct,
               sum(CASE WHEN {q}='' THEN 1 ELSE 0 END) AS empty_str,
               sum(CASE WHEN {q} <> trim({q}) THEN 1 ELSE 0 END) AS ws_pad,
               {castfail} AS cast_fail,
               {mn} AS min_v, {mx} AS max_v
        FROM {view}"""
        rows.append(con.sql(sql).fetchone())
    tbl = "\n".join(
        f"{r[0]:<26} {r[1]:<10} nulls={r[2]:>9,} ({r[3]:>7}%) distinct={r[4]:>9,} "
        f"empty={r[5]:>7,} ws={r[6]:>7,} castfail={r[7]:>8,}  min={str(r[8])[:34]:<34} max={str(r[9])[:34]}"
        for r in rows)
    print(tbl)
    return rows


def stage_profile():
    hdr("STAGE 1 -- FULL COLUMN PROFILE (null rate, distinct, min/max, cast failures, whitespace)")
    profile("ride_raw", "Ride_data*.csv (May+June+July merged)", "ride")
    profile("alerts_raw", "alerts_data.csv", "alerts")
    profile("bill_raw", "bill_data.csv", "bill")
    profile("emp_raw", "emp_Data.csv", "emp")
    profile("fb_raw", "trip_feedback.csv", "fb")

    hdr("STAGE 1b -- WHAT EXACTLY FAILS TO CAST (the actual offending values)")
    show("""SELECT trip_id AS bad_trip_id, count(*) n, count(DISTINCT contract) contracts,
                   sum(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)) total_cost
            FROM bill_raw
            WHERE TRY_CAST(replace(trip_id,',','') AS BIGINT) IS NULL
            GROUP BY 1 ORDER BY n DESC""",
         "bill_data.trip_id values that are NOT numeric")
    show("""SELECT business_unit, office, vendor, contract, slab_name, total_trip_km,
                   count(*) n, sum(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)) AS amt
            FROM bill_raw WHERE trip_id='OverHead'
            GROUP BY 1,2,3,4,5,6 ORDER BY amt DESC LIMIT 25""",
         "'OverHead' rows: what are they")
    show("""SELECT contract, count(*) n, round(sum(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)),2) AS amt,
                   round(min(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)),2) mn,
                   round(max(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)),2) mx
            FROM bill_raw WHERE trip_id='OverHead' GROUP BY 1 ORDER BY amt DESC""",
         "'OverHead' by contract")
    show("""SELECT cycle_start, business_unit, count(*) n,
                   round(sum(TRY_CAST(replace(trip_cost,',','') AS DOUBLE)),2) AS amt
            FROM bill_raw WHERE trip_id='OverHead' GROUP BY 1,2 ORDER BY 1,2""",
         "'OverHead' by cycle and BU -- is it a per-cycle adjustment line?")

    hdr("STAGE 1c -- NEGATIVE MONEY IN bill_data (credit notes / reversals)")
    show("""SELECT count(*) n_neg_rows,
                   round(sum(trip_cost),2) neg_total,
                   round(min(trip_cost),2) most_negative,
                   count(DISTINCT trip_id_raw) d_ids,
                   round(100.0*count(*)/(SELECT count(*) FROM bill),4) pct_rows
            FROM bill WHERE trip_cost<0""", "negative trip_cost overall")
    show("""SELECT trip_id_raw, business_unit, vendor, contract, slab_name, total_trip_km,
                   trip_cost, cycle_start
            FROM bill WHERE trip_cost<0 ORDER BY trip_cost LIMIT 20""",
         "the negative-cost rows themselves")
    show("""SELECT round(sum(trip_cost),2) gross_positive FROM bill WHERE trip_cost>0""",
         "gross positive spend (denominator for the credit)")
    show("""SELECT round(sum(trip_cost),2) net_total FROM bill""", "NET spend after credits")

    hdr("STAGE 1d -- bill.slab_name: literal 'null' / '0' strings")
    show("""SELECT slab_name, count(*) n, round(sum(trip_cost),0) amt,
                   round(avg(total_trip_km),2) avg_km
            FROM bill GROUP BY 1 ORDER BY n DESC LIMIT 40""", "slab_name full vocabulary")
    show("""SELECT count(*) FROM bill_raw WHERE slab_name IN ('null','NULL','0','')""",
         "rows whose slab_name is a STRING sentinel rather than SQL NULL")

    hdr("STAGE 1e -- the single ride.planned_km that will not cast")
    show("""SELECT src_month, business_unit, office, trip_id, trip_date, planned_km, traveled_km,
                   delay_minutes, plannedemployee_cnt, actualemployee_cnt
            FROM ride_raw WHERE TRY_CAST(planned_km AS DOUBLE) IS NULL AND planned_km IS NOT NULL""",
         "the offending row(s)")
    show("""SELECT src_month, business_unit, trip_id, trip_date, planned_cab_registration,
                   actual_cab_registration, is_driver_nc, is_cab_nc, trip_nodal
            FROM ride_raw WHERE is_driver_nc IS NULL OR is_cab_nc IS NULL
               OR planned_cab_registration IS NULL LIMIT 20""",
         "the handful of NULL boolean / NULL cab-registration rows")
    show("""SELECT src_month, count(*) n,
                   count(*) FILTER (WHERE planned_cab_registration IS NULL) null_pcab,
                   count(*) FILTER (WHERE is_driver_nc IS NULL) null_dnc
            FROM ride_raw GROUP BY 1 ORDER BY 1""",
         "are the ride NULLs concentrated in one month file?")

    hdr("STAGE 1f -- ride.shift_type has 100 values incl. a non-time literal")
    show("""SELECT shift_type, count(*) n FROM ride_raw
            WHERE shift_type !~ '^[0-9]{2}:[0-9]{2}$' GROUP BY 1 ORDER BY n DESC""",
         "shift_type values that are NOT HH:MM")
    show("""SELECT src_month, count(*) n FROM ride_raw WHERE shift_type='Non Shift'
            GROUP BY 1 ORDER BY 1""", "'Non Shift' by month")
    show("""SELECT product_type, trip_direction, count(*) n FROM ride_raw
            WHERE shift_type='Non Shift' GROUP BY 1,2 ORDER BY n DESC""",
         "what kind of trips are 'Non Shift'")
    show("""SELECT severity, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),3) pct
            FROM alerts_raw GROUP BY 1 ORDER BY n DESC""",
         "alerts_data.severity distinct values (incl. the stray 'False')")
    show("""SELECT state_text, count(*) n FROM alerts_raw GROUP BY 1 ORDER BY n DESC""",
         "alerts_data.state_text")
    show("""SELECT source, count(*) n FROM alerts_raw GROUP BY 1 ORDER BY n DESC""",
         "alerts_data.source")
    for c in ['route_rating','driver_rating','cab_rating','safety_rating','marshal_rating']:
        show(f"""SELECT '{c}' col, {c} AS val, count(*) n,
                        round(100.0*count(*)/sum(count(*)) OVER (),3) pct
                 FROM fb_raw GROUP BY 2 ORDER BY val""", f"trip_feedback.{c} value distribution")


# ==================================================================================
# STAGE 2 : REFERENTIAL INTEGRITY
# ==================================================================================
def stage_refint():
    hdr("STAGE 2 -- REFERENTIAL INTEGRITY vs ride_data (the trip master)")
    con.sql("CREATE OR REPLACE TEMP TABLE trip_keys AS SELECT DISTINCT trip_id FROM trips WHERE trip_id IS NOT NULL")
    n_trips = con.sql("SELECT count(*) FROM trip_keys").fetchone()[0]
    print(f"distinct trip_id in ride_data = {n_trips:,}")

    for name, view in [('bill','bill'), ('emp','emp'), ('fb','fb'), ('alerts','alerts')]:
        show(f"""
        WITH s AS (SELECT trip_id FROM {view})
        SELECT '{name}' AS file,
               count(*) AS rows,
               sum(CASE WHEN trip_id IS NULL THEN 1 ELSE 0 END) AS unparseable_id,
               sum(CASE WHEN trip_id IS NOT NULL AND t.trip_id IS NULL THEN 1 ELSE 0 END) AS orphan_rows,
               round(100.0*sum(CASE WHEN trip_id IS NOT NULL AND t.trip_id IS NULL THEN 1 ELSE 0 END)/count(*),3) AS orphan_pct,
               count(DISTINCT CASE WHEN t.trip_id IS NULL THEN s.trip_id END) AS orphan_distinct_ids,
               count(DISTINCT s.trip_id) AS distinct_ids
        FROM s LEFT JOIN trip_keys t USING (trip_id)""", f"{name} -> ride_data")

    show("""
    SELECT 'ride trips with NO bill row' AS metric, count(*) n,
           round(100.0*count(*)/(SELECT count(*) FROM trip_keys),3) pct
    FROM trip_keys k WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=k.trip_id)
    UNION ALL SELECT 'ride trips with NO emp row', count(*),
           round(100.0*count(*)/(SELECT count(*) FROM trip_keys),3)
    FROM trip_keys k WHERE NOT EXISTS (SELECT 1 FROM emp e WHERE e.trip_id=k.trip_id)
    UNION ALL SELECT 'ride trips with NO feedback', count(*),
           round(100.0*count(*)/(SELECT count(*) FROM trip_keys),3)
    FROM trip_keys k WHERE NOT EXISTS (SELECT 1 FROM fb f WHERE f.trip_id=k.trip_id)
    UNION ALL SELECT 'ride trips with NO alert', count(*),
           round(100.0*count(*)/(SELECT count(*) FROM trip_keys),3)
    FROM trip_keys k WHERE NOT EXISTS (SELECT 1 FROM alerts a WHERE a.trip_id=k.trip_id)
    """, "REVERSE direction: ride trips missing from each child file")

    # Is the orphan population random or structured?
    show("""
    WITH o AS (SELECT b.* FROM bill b LEFT JOIN trip_keys t USING(trip_id)
               WHERE b.trip_id IS NOT NULL AND t.trip_id IS NULL)
    SELECT business_unit, count(*) n, round(sum(trip_cost),0) amt_cost,
           count(DISTINCT contract) contracts, min(trip_id) min_id, max(trip_id) max_id
    FROM o GROUP BY 1 ORDER BY n DESC""", "bill orphans by BU -- structured or random?")
    show("""
    WITH o AS (SELECT e.* FROM emp e LEFT JOIN trip_keys t USING(trip_id)
               WHERE e.trip_id IS NOT NULL AND t.trip_id IS NULL)
    SELECT business_unit, count(*) n, count(DISTINCT trip_id) trips,
           min(trip_date) mn, max(trip_date) mx
    FROM o GROUP BY 1 ORDER BY n DESC""", "emp orphans by BU")
    show("""
    WITH o AS (SELECT e.* FROM emp e LEFT JOIN trip_keys t USING(trip_id)
               WHERE e.trip_id IS NOT NULL AND t.trip_id IS NULL)
    SELECT date_trunc('month', trip_date) m, count(*) n, count(DISTINCT trip_id) trips
    FROM o GROUP BY 1 ORDER BY 1""", "emp orphans by month -- is it a month boundary artifact?")
    show("""
    SELECT date_trunc('month', trip_date) m, count(*) n, count(DISTINCT trip_id) trips
    FROM emp GROUP BY 1 ORDER BY 1""", "emp rows by month (baseline for above)")
    # ID range overlap check
    show("""SELECT 'ride' src, min(trip_id) mn, max(trip_id) mx, count(DISTINCT trip_id) d FROM trips
            UNION ALL SELECT 'bill', min(trip_id), max(trip_id), count(DISTINCT trip_id) FROM bill
            UNION ALL SELECT 'emp',  min(trip_id), max(trip_id), count(DISTINCT trip_id) FROM emp
            UNION ALL SELECT 'fb',   min(trip_id), max(trip_id), count(DISTINCT trip_id) FROM fb
            UNION ALL SELECT 'alerts',min(trip_id),max(trip_id), count(DISTINCT trip_id) FROM alerts""",
         "trip_id ranges per file")
    # BU-level: are whole BUs missing from ride?
    show("""SELECT business_unit,
               count(*) FILTER (WHERE src='ride') ride_rows,
               count(*) FILTER (WHERE src='emp')  emp_rows,
               count(*) FILTER (WHERE src='bill') bill_rows,
               count(*) FILTER (WHERE src='fb')   fb_rows,
               count(*) FILTER (WHERE src='alerts') alert_rows
        FROM (SELECT business_unit,'ride' src FROM trips
              UNION ALL SELECT business_unit,'emp' FROM emp
              UNION ALL SELECT business_unit,'bill' FROM bill
              UNION ALL SELECT business_unit,'fb' FROM fb
              UNION ALL SELECT business_unit,'alerts' FROM alerts)
        GROUP BY 1 ORDER BY 1""", "business_unit presence across all 5 files")


# ==================================================================================
# STAGE 3 : DUPLICATES
# ==================================================================================
def stage_dupes():
    hdr("STAGE 3 -- DUPLICATE DETECTION")
    show("""SELECT count(*) total_rows, count(DISTINCT trip_id) distinct_ids,
                   count(*)-count(DISTINCT trip_id) AS excess,
                   sum(CASE WHEN trip_id IS NULL THEN 1 ELSE 0 END) null_ids
            FROM trips""", "ride_data: trip_id uniqueness")
    show("""SELECT n_copies, count(*) n_trip_ids, n_copies*count(*) rows_involved
            FROM (SELECT trip_id, count(*) n_copies FROM trips WHERE trip_id IS NOT NULL GROUP BY 1)
            WHERE n_copies>1 GROUP BY 1 ORDER BY 1""", "ride_data: duplicate trip_id multiplicity")
    show("""SELECT trip_id, count(*) n, count(DISTINCT src_month) n_months,
                   string_agg(DISTINCT src_month) mons,
                   count(DISTINCT trip_date) dates, count(DISTINCT office) offices,
                   count(DISTINCT vendor_id) vendors, count(DISTINCT delay_minutes) delays
            FROM trips WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1
            ORDER BY n DESC LIMIT 15""", "ride_data: sample duplicate trip_ids -- same or different content?")
    show("""SELECT count(*) FROM (SELECT * FROM ride_raw EXCEPT SELECT * FROM ride_raw)""",
         "sanity")
    show("""WITH d AS (SELECT trip_id FROM trips WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1)
            SELECT src_month, count(*) dup_rows FROM trips WHERE trip_id IN (SELECT trip_id FROM d)
            GROUP BY 1 ORDER BY 1""", "which month files carry the duplicate trip_ids")
    show("""WITH x AS (SELECT trip_id, count(*) n_rows,
                   count(DISTINCT (business_unit,office,product_type,trip_date,shift_type,
                                   trip_direction,vendor_id,delay_minutes,traveled_km)) n_variants
                FROM trips WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1)
            SELECT n_variants, count(*) n_trip_ids FROM x GROUP BY 1 ORDER BY 1""",
         "duplicate trip_ids: exact-copy (n_variants=1) vs genuinely conflicting rows")

    show("""SELECT count(*) n_rows, count(DISTINCT event_id) distinct_event_ids,
                   count(*)-count(DISTINCT event_id) excess
            FROM alerts_raw""", "alerts: event_id uniqueness")
    show("""SELECT count(*) n_rows,
                   count(DISTINCT (trip_id,stwid)) distinct_pairs,
                   count(*)-count(DISTINCT (trip_id,stwid)) excess
            FROM emp""", "emp_data: (trip_id, stwid) uniqueness")
    show("""SELECT n, count(*) pairs FROM
            (SELECT trip_id,stwid,count(*) n FROM emp GROUP BY 1,2 HAVING count(*)>1)
            GROUP BY 1 ORDER BY 1 LIMIT 20""", "emp_data: multiplicity of duplicated (trip_id,stwid)")
    show("""WITH d AS (SELECT trip_id,stwid FROM emp GROUP BY 1,2 HAVING count(*)>1)
            SELECT e.trip_id, e.stwid, count(*) n,
                   count(DISTINCT e.trip_date) dates, count(DISTINCT e.boarding_status) statuses,
                   count(DISTINCT e.actual_pickup_epoch) pickups
            FROM emp e JOIN d USING (trip_id,stwid) GROUP BY 1,2 ORDER BY n DESC LIMIT 10""",
         "emp_data: are duplicate (trip_id,stwid) identical rows or conflicting?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id,stwid)) distinct_pairs,
                   count(*)-count(DISTINCT (trip_id,stwid)) excess
            FROM fb""", "feedback: (trip_id, stwid) uniqueness")
    show("""SELECT n, count(*) pairs FROM
            (SELECT trip_id,stwid,count(*) n FROM fb GROUP BY 1,2 HAVING count(*)>1)
            GROUP BY 1 ORDER BY 1 LIMIT 20""", "feedback: multiplicity")
    show("""WITH d AS (SELECT trip_id,stwid FROM fb GROUP BY 1,2 HAVING count(*)>1)
            SELECT f.trip_id, f.stwid, count(*) n, count(DISTINCT f.creation_ts) times,
                   count(DISTINCT (f.route_rating,f.driver_rating,f.cab_rating,f.safety_rating)) rating_variants
            FROM fb f JOIN d USING(trip_id,stwid) GROUP BY 1,2 ORDER BY n DESC LIMIT 10""",
         "feedback: same employee rating same trip multiple times?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id,contract,slab_name,total_trip_km,trip_cost)) dv,
                   count(DISTINCT trip_id) d_trip
            FROM bill WHERE trip_id IS NOT NULL""", "bill: duplicate trip_id")
    show("""SELECT n, count(*) trip_ids, sum(c2) total_cost FROM
            (SELECT trip_id,count(*) n, sum(trip_cost) c2 FROM bill WHERE trip_id IS NOT NULL
             GROUP BY 1 HAVING count(*)>1) GROUP BY 1 ORDER BY 1 LIMIT 20""",
         "bill: multiplicity of duplicated trip_id + money involved")
    show("""WITH d AS (SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1)
            SELECT b.trip_id, count(*) n, count(DISTINCT b.vendor) vendors,
                   count(DISTINCT b.contract) contracts, count(DISTINCT b.cycle_start) cycles,
                   sum(b.trip_cost) amt_cost
            FROM bill b JOIN d USING(trip_id) GROUP BY 1 ORDER BY amt_cost DESC LIMIT 10""",
         "bill: duplicate trip_id detail -- double billing?")


# ==================================================================================
# STAGE 4 : IMPOSSIBLE / OUT-OF-RANGE VALUES
# ==================================================================================
def stage_impossible():
    hdr("STAGE 4 -- IMPOSSIBLE VALUES")
    N = con.sql("SELECT count(*) FROM trips").fetchone()[0]
    show(f"""SELECT 'ride: traveled_km < 0' chk, count(*) n, round(100.0*count(*)/{N},4) pct FROM trips WHERE traveled_km<0
        UNION ALL SELECT 'ride: planned_km < 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE planned_km<0
        UNION ALL SELECT 'ride: traveled_km = 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE traveled_km=0
        UNION ALL SELECT 'ride: planned_km = 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE planned_km=0
        UNION ALL SELECT 'ride: delay_minutes < 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE delay_minutes<0
        UNION ALL SELECT 'ride: actual_end <= actual_start', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE actual_end_epoch<=actual_start_epoch
        UNION ALL SELECT 'ride: planned_end <= planned_start', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE planned_end_epoch<=planned_start_epoch
        UNION ALL SELECT 'ride: emp_actual > cab_capacity', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE emp_actual>cab_capacity
        UNION ALL SELECT 'ride: emp_actual > emp_planned', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE emp_actual>emp_planned
        UNION ALL SELECT 'ride: noshow > emp_planned', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE noshow>emp_planned
        UNION ALL SELECT 'ride: emp_planned = 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE emp_planned=0
        UNION ALL SELECT 'ride: emp_actual = 0', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE emp_actual=0
        UNION ALL SELECT 'ride: cab_capacity = 0 or null', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE cab_capacity IS NULL OR cab_capacity=0
        UNION ALL SELECT 'ride: planned_cab <> actual_cab', count(*), round(100.0*count(*)/{N},4) FROM trips WHERE planned_cab_registration IS DISTINCT FROM actual_cab_registration
        ORDER BY n DESC""", "ride_data impossible-value scan")

    show("""SELECT approx_quantile(delay_minutes,[0.5,0.9,0.99,0.999,0.9999]) q,
                   max(delay_minutes) mx, min(delay_minutes) mn,
                   count(*) FILTER (WHERE delay_minutes>240) gt4h,
                   count(*) FILTER (WHERE delay_minutes>1440) gt24h
            FROM trips""", "delay_minutes distribution / outliers")
    show("""SELECT delay_reason, count(*) n, round(avg(delay_minutes),1) avg_delay, max(delay_minutes) mx
            FROM trips WHERE delay_minutes>1440 GROUP BY 1 ORDER BY n DESC""",
         "who are the >24h delays -- artifact or real?")
    show("""SELECT trip_id, trip_date, office, delay_minutes,
                   planned_end_epoch, actual_end_epoch,
                   (actual_end_epoch-planned_end_epoch)/60.0 AS epoch_delay_min,
                   round(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0,2) AS mismatch
            FROM trips WHERE delay_minutes>1440 ORDER BY delay_minutes DESC LIMIT 10""",
         "do the big delays agree with the epoch arithmetic?")
    show("""SELECT count(*) n_with_both,
              count(*) FILTER (WHERE abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<=1) agree_1min,
              round(100.0*count(*) FILTER (WHERE abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<=1)/count(*),3) pct_agree,
              count(*) FILTER (WHERE delay_minutes=0 AND actual_end_epoch<planned_end_epoch) zero_but_early
            FROM trips WHERE delay_minutes IS NOT NULL AND actual_end_epoch IS NOT NULL AND planned_end_epoch IS NOT NULL""",
         "delay_minutes vs epoch-derived delay: internal consistency")

    show("""SELECT count(*) n,
              count(*) FILTER (WHERE delay_minutes=0 AND actual_end_epoch>planned_end_epoch+300) clamped
            FROM trips""", "is delay_minutes clamped at 0 for early arrivals (floor at 0)?")

    Ne = con.sql("SELECT count(*) FROM emp").fetchone()[0]
    show(f"""SELECT 'emp: planned_km < 0' chk, count(*) n, round(100.0*count(*)/{Ne},4) pct FROM emp WHERE planned_km<0
        UNION ALL SELECT 'emp: traveled_km < 0', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE traveled_km<0
        UNION ALL SELECT 'emp: traveled_km = 0', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE traveled_km=0
        UNION ALL SELECT 'emp: stwid = 0', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE stwid=0
        UNION ALL SELECT 'emp: actual_drop <= actual_pickup', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE actual_drop_epoch<=actual_pickup_epoch
        UNION ALL SELECT 'emp: planned_drop <= planned_pickup', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE planned_drop_epoch<=planned_pickup_epoch
        UNION ALL SELECT 'emp: is_no_show TRUE but Boarded', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE is_no_show AND boarding_status='Boarded'
        UNION ALL SELECT 'emp: is_no_show FALSE but Not Boarded', count(*), round(100.0*count(*)/{Ne},4) FROM emp WHERE NOT is_no_show AND boarding_status<>'Boarded'
        ORDER BY n DESC""", "emp_data impossible-value scan")
    show("""SELECT min(planned_km) mn_p, max(planned_km) mx_p, min(traveled_km) mn_t, max(traveled_km) mx_t,
                   count(*) FILTER (WHERE planned_km<0) neg_p, count(*) FILTER (WHERE traveled_km<0) neg_t
            FROM emp""", "emp km extremes")
    show("""SELECT boarding_status, count(*) n, count(*) FILTER (WHERE planned_km<0) neg_planned,
                   count(*) FILTER (WHERE traveled_km<0) neg_travel,
                   round(100.0*count(*) FILTER (WHERE planned_km<0)/count(*),3) pct_neg
            FROM emp GROUP BY 1 ORDER BY n DESC""", "negative km by boarding_status -- signal or artifact?")
    show("""SELECT signintype, count(*) n, count(*) FILTER (WHERE planned_km<0) neg_planned,
                   round(100.0*count(*) FILTER (WHERE planned_km<0)/count(*),3) pct_neg
            FROM emp GROUP BY 1 ORDER BY n DESC""", "negative km by signintype")
    show("""SELECT count(*) n, min(planned_km) mn, max(planned_km) mx, avg(traveled_km) avg_t,
                   count(DISTINCT trip_id) trips, count(DISTINCT stwid) emps
            FROM emp WHERE planned_km<0""", "the negative-km population")
    show("""SELECT round(planned_km,2) pk, count(*) n FROM emp WHERE planned_km<0
            GROUP BY 1 ORDER BY n DESC LIMIT 15""", "negative planned_km actual values")

    show("""SELECT 'fb: rating outside 0-5' chk, count(*) n FROM fb
              WHERE route_rating NOT BETWEEN 0 AND 5 OR driver_rating NOT BETWEEN 0 AND 5
                 OR cab_rating NOT BETWEEN 0 AND 5 OR safety_rating NOT BETWEEN 0 AND 5
                 OR marshal_rating NOT BETWEEN 0 AND 5
            UNION ALL SELECT 'fb: all-zero rating row', count(*) FROM fb
              WHERE route_rating=0 AND driver_rating=0 AND cab_rating=0 AND safety_rating=0 AND marshal_rating=0
            UNION ALL SELECT 'fb: marshal_rating=0', count(*) FROM fb WHERE marshal_rating=0
            UNION ALL SELECT 'fb: creation_ts BEFORE trip_ts', count(*) FROM fb WHERE creation_ts<trip_ts
            UNION ALL SELECT 'fb: stwid=0', count(*) FROM fb WHERE stwid=0""",
         "feedback impossible-value scan")
    show("""SELECT count(*) n, round(100.0*count(*)/(SELECT count(*) FROM fb),3) pct,
              round(avg(date_diff('minute', trip_ts, creation_ts)),1) avg_lag_min,
              min(date_diff('minute', trip_ts, creation_ts)) min_lag,
              max(date_diff('minute', trip_ts, creation_ts)) max_lag
            FROM fb WHERE creation_ts<trip_ts""", "feedback submitted BEFORE the trip: how early?")
    show("""SELECT approx_quantile(date_diff('minute',trip_ts,creation_ts),[0.01,0.25,0.5,0.75,0.99]) q
            FROM fb""", "feedback lag distribution (min)")

    show("""SELECT 'alerts: ack BEFORE start' chk, count(*) n FROM alerts WHERE ack_ts<start_ts
            UNION ALL SELECT 'alerts: ack IS NULL', count(*) FROM alerts WHERE ack_ts IS NULL
            UNION ALL SELECT 'alerts: stwid=0', count(*) FROM alerts WHERE stwid=0
            UNION ALL SELECT 'alerts: trip_id NULL/unparseable', count(*) FROM alerts WHERE trip_id IS NULL""",
         "alerts impossible-value scan")
    show("""SELECT state_text, count(*) n, count(*) FILTER (WHERE ack_ts IS NULL) null_ack,
                   round(100.0*count(*) FILTER (WHERE ack_ts IS NULL)/count(*),2) pct_null_ack
            FROM alerts GROUP BY 1 ORDER BY n DESC""", "null acknowledge_time by state -- meaningful?")

    show("""SELECT 'bill: trip_cost < 0' chk, count(*) n, round(sum(trip_cost),0) amt FROM bill WHERE trip_cost<0
            UNION ALL SELECT 'bill: trip_cost = 0', count(*), 0 FROM bill WHERE trip_cost=0
            UNION ALL SELECT 'bill: total_trip_km < 0', count(*), round(sum(trip_cost),0) FROM bill WHERE total_trip_km<0
            UNION ALL SELECT 'bill: total_trip_km = 0', count(*), round(sum(trip_cost),0) FROM bill WHERE total_trip_km=0
            UNION ALL SELECT 'bill: trip_cost NULL', count(*), 0 FROM bill WHERE trip_cost IS NULL
            UNION ALL SELECT 'bill: cycle_end < cycle_start', count(*), 0 FROM bill WHERE cycle_end<cycle_start""",
         "bill impossible-value scan")
    show("""SELECT contract, count(*) n, sum(CASE WHEN total_trip_km=0 THEN 1 ELSE 0 END) zero_km,
                   round(100.0*sum(CASE WHEN total_trip_km=0 THEN 1 ELSE 0 END)/count(*),2) pct_zero,
                   round(sum(trip_cost),0) amt_cost
            FROM bill GROUP BY 1 ORDER BY n DESC""", "zero-km by contract (the fixed-rate confirmation)")

    # Cross-file value contradictions
    hdr("STAGE 4b -- CROSS-FILE CONTRADICTIONS (same fact, two files, different answers)")
    show("""SELECT count(*) n_matched,
              count(*) FILTER (WHERE t.business_unit<>b.business_unit) bu_mismatch,
              count(*) FILTER (WHERE t.office<>b.office) office_mismatch,
              count(*) FILTER (WHERE t.vendor_id<>b.vendor) vendor_mismatch,
              round(100.0*count(*) FILTER (WHERE t.vendor_id<>b.vendor)/count(*),3) pct_vendor_mismatch
            FROM trips t JOIN bill b USING (trip_id)""",
         "ride vs bill: do BU/office/vendor agree on the same trip_id?")
    show("""SELECT count(*) n_matched,
              count(*) FILTER (WHERE abs(t.traveled_km-b.total_trip_km)>1) km_gap_gt1,
              round(100.0*count(*) FILTER (WHERE abs(t.traveled_km-b.total_trip_km)>1)/count(*),3) pct
            FROM trips t JOIN bill b USING(trip_id) WHERE b.total_trip_km>0""",
         "ride.traveled_km vs bill.total_trip_km on km-billed contracts")
    show("""SELECT approx_quantile(b.total_trip_km-t.traveled_km,[0.05,0.5,0.95]) q,
                   avg(b.total_trip_km-t.traveled_km) mean_gap, count(*) n
            FROM trips t JOIN bill b USING(trip_id) WHERE b.total_trip_km>0""",
         "signed km gap (bill minus ride)")
    show("""SELECT count(*) trips_compared,
              count(*) FILTER (WHERE t.emp_actual<>e.n_emp) mismatch,
              round(100.0*count(*) FILTER (WHERE t.emp_actual<>e.n_emp)/count(*),2) pct_mismatch
            FROM trips t JOIN (SELECT trip_id,count(*) n_emp FROM emp GROUP BY 1) e USING(trip_id)""",
         "ride.actualemployee_cnt vs COUNT(*) of emp_Data rows for that trip")
    show("""SELECT t.emp_actual, e.n_emp, count(*) n FROM trips t
            JOIN (SELECT trip_id,count(*) n_emp FROM emp GROUP BY 1) e USING(trip_id)
            WHERE t.emp_actual<>e.n_emp GROUP BY 1,2 ORDER BY n DESC LIMIT 15""",
         "shape of the emp-count disagreement")
    show("""SELECT count(*) trips,
              count(*) FILTER (WHERE t.noshow<>e.n_ns) mismatch,
              round(100.0*count(*) FILTER (WHERE t.noshow<>e.n_ns)/count(*),2) pct
            FROM trips t JOIN (SELECT trip_id, count(*) FILTER (WHERE is_no_show) n_ns FROM emp GROUP BY 1) e
            USING (trip_id)""", "ride.noshow_cnt vs emp_Data no-show count")
    show("""SELECT count(*) n_rows, count(*) FILTER (WHERE t.business_unit<>e.business_unit) bu_mm,
                   count(*) FILTER (WHERE t.office<>e.office) office_mm,
                   count(*) FILTER (WHERE t.trip_date<>e.trip_date) date_mm,
                   count(*) FILTER (WHERE t.shift_type<>e.shift_type) shift_mm,
                   count(*) FILTER (WHERE t.product_type<>e.product_type) prod_mm
            FROM trips t JOIN emp e USING(trip_id)""",
         "ride vs emp: do the shared descriptive columns agree?")
    show("""SELECT count(*) n_rows, count(*) FILTER (WHERE t.business_unit<>f.business_unit) bu_mm,
                   count(*) FILTER (WHERE t.trip_direction<>f.trip_type) dir_mm,
                   count(*) FILTER (WHERE t.trip_date<>CAST(f.trip_ts AS DATE)) date_mm
            FROM trips t JOIN fb f USING(trip_id)""", "ride vs feedback consistency")
    show("""SELECT count(*) n_rows, count(*) FILTER (WHERE t.business_unit<>a.business_unit) bu_mm
            FROM trips t JOIN alerts a USING(trip_id)""", "ride vs alerts BU consistency")


# ==================================================================================
# STAGE 5 : DATE COVERAGE
# ==================================================================================
def stage_dates():
    hdr("STAGE 5 -- DATE COVERAGE (May 1 - Jul 31 2026 = 92 days)")
    show("""SELECT 'ride' f, min(trip_date) mn, max(trip_date) mx, count(DISTINCT trip_date) n_days FROM trips
            UNION ALL SELECT 'emp', min(trip_date), max(trip_date), count(DISTINCT trip_date) FROM emp
            UNION ALL SELECT 'fb', min(CAST(trip_ts AS DATE)), max(CAST(trip_ts AS DATE)), count(DISTINCT CAST(trip_ts AS DATE)) FROM fb
            UNION ALL SELECT 'fb_creation', min(CAST(creation_ts AS DATE)), max(CAST(creation_ts AS DATE)), count(DISTINCT CAST(creation_ts AS DATE)) FROM fb
            UNION ALL SELECT 'alerts', min(CAST(start_ts AS DATE)), max(CAST(start_ts AS DATE)), count(DISTINCT CAST(start_ts AS DATE)) FROM alerts
            UNION ALL SELECT 'bill_cycle_start', min(CAST(cycle_start AS DATE)), max(CAST(cycle_start AS DATE)), count(DISTINCT CAST(cycle_start AS DATE)) FROM bill""",
         "date range + distinct days per file")
    show("""WITH cal AS (SELECT unnest(generate_series(DATE '2026-05-01', DATE '2026-07-31', INTERVAL 1 DAY))::DATE d)
            SELECT d, dayname(d) dow,
                   (SELECT count(*) FROM trips t WHERE t.trip_date=cal.d) ride,
                   (SELECT count(*) FROM emp e WHERE e.trip_date=cal.d) emp,
                   (SELECT count(*) FROM fb f WHERE CAST(f.trip_ts AS DATE)=cal.d) fb,
                   (SELECT count(*) FROM alerts a WHERE CAST(a.start_ts AS DATE)=cal.d) alerts
            FROM cal ORDER BY d""", "per-day row counts across the 92-day window", rows=100)
    show("""WITH cal AS (SELECT unnest(generate_series(DATE '2026-05-01', DATE '2026-07-31', INTERVAL 1 DAY))::DATE d)
            SELECT d, dayname(d) dow FROM cal
            WHERE NOT EXISTS (SELECT 1 FROM trips t WHERE t.trip_date=cal.d)""",
         "days with ZERO ride rows")
    show("""SELECT count(*) FROM trips WHERE trip_date < DATE '2026-05-01' OR trip_date > DATE '2026-07-31'""",
         "ride trips outside May-Jul")
    show("""SELECT trip_date, count(*) n FROM emp
            WHERE trip_date < DATE '2026-05-01' OR trip_date > DATE '2026-07-31'
            GROUP BY 1 ORDER BY 1""", "emp rows outside May-Jul")
    show("""SELECT CAST(start_ts AS DATE) d, count(*) n FROM alerts
            WHERE start_ts < TIMESTAMP '2026-05-01' OR start_ts >= TIMESTAMP '2026-08-01'
            GROUP BY 1 ORDER BY 1""", "alerts outside May-Jul")
    show("""SELECT CAST(creation_ts AS DATE) d, count(*) n FROM fb
            WHERE creation_ts >= TIMESTAMP '2026-08-01' GROUP BY 1 ORDER BY 1 LIMIT 20""",
         "feedback created after Jul 31 (late submissions)")
    show("""SELECT src_month, min(trip_date) mn, max(trip_date) mx, count(*) n,
                   count(*) FILTER (WHERE date_trunc('month',trip_date)<>
                     CASE src_month WHEN 'may' THEN DATE '2026-05-01' WHEN 'June' THEN DATE '2026-06-01'
                     ELSE DATE '2026-07-01' END) wrong_month
            FROM trips GROUP BY 1 ORDER BY 1""", "does each month FILE only contain that month's trips?")
    show("""SELECT to_timestamp(min(actual_start_epoch)) mn_start, to_timestamp(max(actual_start_epoch)) mx_start,
                   to_timestamp(min(actual_end_epoch)) mn_end, to_timestamp(max(actual_end_epoch)) mx_end,
                   to_timestamp(min(planned_start_epoch)) mn_ps, to_timestamp(max(planned_end_epoch)) mx_pe
            FROM trips""", "epoch range sanity in ride_data")
    show("""SELECT count(*) FILTER (WHERE to_timestamp(actual_start_epoch) < TIMESTAMP '2026-04-30') too_early,
                   count(*) FILTER (WHERE to_timestamp(actual_start_epoch) >= TIMESTAMP '2026-08-02') too_late,
                   count(*) FILTER (WHERE abs(date_diff('day', trip_date, CAST(to_timestamp(actual_start_epoch) AS DATE)))>1) date_epoch_gap
            FROM trips""", "epochs outside window / disagreeing with trip_date")
    show("""SELECT to_timestamp(min(planned_pickup_epoch)) mn, to_timestamp(max(planned_drop_epoch)) mx,
                   count(*) FILTER (WHERE actual_pickup_epoch<1.7e9) low, count(*) FILTER (WHERE actual_pickup_epoch=0) zero
            FROM emp""", "emp epoch range")


# ==================================================================================
# STAGE 6 : SCHEMA DRIFT ACROSS MONTH FILES
# ==================================================================================
def stage_drift():
    hdr("STAGE 6 -- MAY/JUNE/JULY SCHEMA DRIFT (proved per column)")
    for m in ['may','June','July']:
        f = f"{RAW}/Ride_data _trip-{m}_2026.csv"
        r = con.sql(f"""SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM
                        read_csv('{f}', header=true, sample_size=-1))""").fetchall()
        print(f"\n-- inferred dtypes, {m} file (n_cols={len(r)}):")
        print("   " + ", ".join(f"{a}:{b}" for a, b in r))

    print("\n-- column-set differences between files:")
    sets = {}
    for m in ['may','June','July']:
        f = f"{RAW}/Ride_data _trip-{m}_2026.csv"
        sets[m] = [x[0] for x in con.sql(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv('{f}', header=true, all_varchar=true, sample_size=-1))").fetchall()]
    print(f"   may  == June : {sets['may']==sets['June']}")
    print(f"   June == July : {sets['June']==sets['July']}")
    print(f"   set diffs    : may-June={set(sets['may'])-set(sets['June'])}, June-may={set(sets['June'])-set(sets['may'])}, "
          f"July-June={set(sets['July'])-set(sets['June'])}, June-July={set(sets['June'])-set(sets['July'])}")

    print("\n-- per-column DTYPE MATRIX (DuckDB inference, full-file sample):")
    types = {}
    for m in ['may','June','July']:
        f = f"{RAW}/Ride_data _trip-{m}_2026.csv"
        types[m] = dict(con.sql(f"""SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM
                        read_csv('{f}', header=true, sample_size=-1))""").fetchall())
    allc = sets['may']
    print(f"   {'column':<28}{'may':<14}{'June':<14}{'July':<14} DRIFT")
    for c in allc:
        a, b, cc = types['may'].get(c), types['June'].get(c), types['July'].get(c)
        drift = "  <<< DRIFT" if len({a, b, cc}) > 1 else ""
        print(f"   {c:<28}{str(a):<14}{str(b):<14}{str(cc):<14}{drift}")

    print("\n-- per-column NULL RATE by source month (all_varchar, so drift shows as nulls not errors):")
    cols = [c for c in allc]
    parts = ",\n".join(
        f"round(100.0*(count(*)-count(\"{c}\"))/count(*),3) AS \"{c}\"" for c in cols)
    show(f"SELECT src_month, count(*) n, {parts} FROM ride_raw GROUP BY 1 ORDER BY 1", maxw=400)

    print("\n-- per-column CAST-FAILURE rate by source month:")
    checks = []
    for c, h in NUMERIC_HINT['ride'].items():
        ce = CAST_EXPR[h].format(c=f'"{c}"')
        checks.append(f'sum(CASE WHEN "{c}" IS NOT NULL AND {ce} IS NULL THEN 1 ELSE 0 END) AS "{c}"')
    show(f"SELECT src_month, count(*) n, {', '.join(checks)} FROM ride_raw GROUP BY 1 ORDER BY 1", maxw=400)

    print("\n-- FORMATTING drift: is the comma-separator convention stable across months?")
    show("""SELECT src_month,
              sum(CASE WHEN trip_id LIKE '%,%' THEN 1 ELSE 0 END) tripid_comma,
              sum(CASE WHEN delay_minutes LIKE '%,%' THEN 1 ELSE 0 END) delay_comma,
              sum(CASE WHEN actual_end_epoch LIKE '%,%' THEN 1 ELSE 0 END) epoch_comma,
              sum(CASE WHEN planned_km LIKE '%,%' THEN 1 ELSE 0 END) pkm_comma,
              count(*) n
            FROM ride_raw GROUP BY 1 ORDER BY 1""")
    show("""SELECT src_month, actual_escort, count(*) n FROM ride_raw GROUP BY 1,2 ORDER BY 1,2""",
         "boolean literal casing drift: actual_escort")
    show("""SELECT src_month, is_driver_nc, count(*) n FROM ride_raw GROUP BY 1,2 ORDER BY 1,2""",
         "boolean literal casing drift: is_driver_nc")
    show("""SELECT src_month, route_source, count(*) n FROM ride_raw GROUP BY 1,2 ORDER BY 1,2""",
         "route_source values by month")
    show("""SELECT src_month, trip_nodal, count(*) n,
                   round(100.0*count(*)/sum(count(*)) OVER (PARTITION BY src_month),2) pct
            FROM ride_raw GROUP BY 1,2 ORDER BY 1,3 DESC""", "trip_nodal by month (incl NULL)")
    show("""SELECT src_month, actual_cab_fuel_type, count(*) n FROM ride_raw GROUP BY 1,2 ORDER BY 1,3 DESC""",
         "fuel type by month")
    show("""SELECT src_month, count(DISTINCT shift_type) shifts, min(shift_type) mn, max(shift_type) mx
            FROM ride_raw GROUP BY 1 ORDER BY 1""", "shift_type cardinality by month")


# ==================================================================================
# STAGE 7 : CATEGORICAL DRIFT (new / disappearing values)
# ==================================================================================
def stage_categorical():
    hdr("STAGE 7 -- CATEGORICAL DRIFT: new / disappearing vendors, offices, BUs, contracts")
    for col in ['business_unit','office','vendor_id','product_type','trip_direction',
                'delay_reason','route_source','actual_cab_fuel_type','trip_nodal']:
        show(f"""
        WITH m AS (SELECT month, {col} v, count(*) n FROM trips WHERE {col} IS NOT NULL GROUP BY 1,2)
        SELECT v,
          coalesce(max(n) FILTER (WHERE month=DATE '2026-05-01'),0) may,
          coalesce(max(n) FILTER (WHERE month=DATE '2026-06-01'),0) jun,
          coalesce(max(n) FILTER (WHERE month=DATE '2026-07-01'),0) jul,
          CASE WHEN coalesce(max(n) FILTER (WHERE month=DATE '2026-05-01'),0)=0 THEN 'NEW after May'
               WHEN coalesce(max(n) FILTER (WHERE month=DATE '2026-07-01'),0)=0 THEN 'GONE by July'
               ELSE '' END flag
        FROM m GROUP BY 1 ORDER BY (may+jun+jul) DESC""", f"ride.{col} by month", rows=120)

    show("""WITH m AS (SELECT date_trunc('month',cycle_start) mo, contract v, count(*) n,
                              sum(trip_cost) c FROM bill GROUP BY 1,2)
            SELECT v, coalesce(max(n) FILTER (WHERE mo=DATE '2026-05-01'),0) may,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-06-01'),0) jun,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-07-01'),0) jul,
                      round(sum(c),0) total_cost
            FROM m GROUP BY 1 ORDER BY total_cost DESC""", "bill.contract by cycle month", rows=120)
    show("""WITH m AS (SELECT date_trunc('month',cycle_start) mo, vendor v, count(*) n FROM bill GROUP BY 1,2)
            SELECT v, coalesce(max(n) FILTER (WHERE mo=DATE '2026-05-01'),0) may,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-06-01'),0) jun,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-07-01'),0) jul
            FROM m GROUP BY 1 ORDER BY (may+jun+jul) DESC""", "bill.vendor by cycle month", rows=120)
    show("""SELECT slab_name, count(*) n, round(sum(trip_cost),0) amt_cost,
                   round(min(total_trip_km),2) mn_km, round(max(total_trip_km),2) mx_km,
                   round(avg(total_trip_km),2) avg_km
            FROM bill GROUP BY 1 ORDER BY n DESC""", "bill.slab_name: do slabs match their km ranges?")
    show("""SELECT slab_name, count(*) n,
                   count(*) FILTER (WHERE total_trip_km=0) zero_km,
                   round(100.0*count(*) FILTER (WHERE total_trip_km=0)/count(*),2) pct_zero
            FROM bill GROUP BY 1 ORDER BY n DESC""", "slab vs zero-km")
    show("""WITH m AS (SELECT date_trunc('month',start_ts) mo, event_type v, count(*) n FROM alerts GROUP BY 1,2)
            SELECT v, coalesce(max(n) FILTER (WHERE mo=DATE '2026-05-01'),0) may,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-06-01'),0) jun,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-07-01'),0) jul
            FROM m GROUP BY 1 ORDER BY (may+jun+jul) DESC""", "alerts.event_type by month")
    show("""WITH m AS (SELECT date_trunc('month',start_ts) mo, severity v, count(*) n FROM alerts GROUP BY 1,2)
            SELECT v, coalesce(max(n) FILTER (WHERE mo=DATE '2026-05-01'),0) may,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-06-01'),0) jun,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-07-01'),0) jul
            FROM m GROUP BY 1 ORDER BY (may+jun+jul) DESC""", "alerts.severity by month -- when does 'False' appear?")
    show("""WITH m AS (SELECT date_trunc('month',trip_date) mo, boarding_status v, count(*) n FROM emp GROUP BY 1,2)
            SELECT v, coalesce(max(n) FILTER (WHERE mo=DATE '2026-05-01'),0) may,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-06-01'),0) jun,
                      coalesce(max(n) FILTER (WHERE mo=DATE '2026-07-01'),0) jul
            FROM m GROUP BY 1 ORDER BY (may+jun+jul) DESC""", "emp.boarding_status by month")
    show("""SELECT not_boarding_reason, count(*) n FROM emp GROUP BY 1 ORDER BY n DESC LIMIT 25""",
         "emp.not_boarding_reason vocabulary")
    show("""SELECT boarding_status, count(*) n,
                   count(*) FILTER (WHERE not_boarding_reason IS NULL) null_reason,
                   round(100.0*count(*) FILTER (WHERE not_boarding_reason IS NULL)/count(*),2) pct
            FROM emp GROUP BY 1 ORDER BY n DESC""", "is not_boarding_reason populated when it should be?")
    show("""SELECT gender, count(*) n FROM emp GROUP BY 1 ORDER BY n DESC""", "emp.gender vocabulary")
    show("""SELECT emp_role, count(*) n FROM emp GROUP BY 1 ORDER BY n DESC""", "emp.emp_role vocabulary")
    show("""SELECT signintype, count(*) n FROM emp GROUP BY 1 ORDER BY n DESC""", "emp.signintype vocabulary")
    show("""SELECT trip_type, count(*) n FROM fb GROUP BY 1 ORDER BY n DESC""", "fb.trip_type vocabulary")
    show("""SELECT business_unit, count(DISTINCT office) offices, string_agg(DISTINCT office) list
            FROM trips GROUP BY 1 ORDER BY 1""", "BU -> office mapping (is it 1:1?)")
    show("""SELECT office, count(DISTINCT business_unit) bus, string_agg(DISTINCT business_unit) list
            FROM trips GROUP BY 1 HAVING count(DISTINCT business_unit)>1 ORDER BY bus DESC""",
         "offices shared by >1 BU (join hazard)")
    show("""SELECT vendor_id, count(DISTINCT business_unit) n_bu, count(*) n
            FROM trips GROUP BY 1 ORDER BY n_bu DESC, n DESC LIMIT 20""",
         "vendor names shared across BUs -- is vendor_id globally unique?")


# ==================================================================================
# STAGE 8 : WHITESPACE / ENCODING / KEY HYGIENE
# ==================================================================================
def stage_whitespace():
    hdr("STAGE 8 -- WHITESPACE / CASE / ENCODING HAZARDS ON JOIN & GROUP BY KEYS")
    checks = [
        ("ride_raw", ["business_unit","office","product_type","shift_type","trip_direction","vendor_id",
                      "delay_reason","route_source","actual_cab_fuel_type","trip_nodal",
                      "planned_cab_registration","actual_cab_registration","trip_id","trip_date"]),
        ("bill_raw", ["business_unit","office","vendor","contract","slab_name","trip_id"]),
        ("emp_raw",  ["business_unit","office","product_type","shift_type","signintype","gender",
                      "emp_role","boarding_status","not_boarding_reason","trip_id","stwid"]),
        ("fb_raw",   ["business_unit","trip_type","trip_id","stwid"]),
        ("alerts_raw",["business_unit","event_type","state_text","severity","source","trip_id","stwid"]),
    ]
    for view, cols in checks:
        parts = []
        for c in cols:
            parts.append(f"""SELECT '{view}' src, '{c}' col,
              sum(CASE WHEN "{c}" <> trim("{c}") THEN 1 ELSE 0 END) lead_trail_ws,
              sum(CASE WHEN "{c}" LIKE '%  %' THEN 1 ELSE 0 END) double_space,
              sum(CASE WHEN "{c}" ~ '[^\\x20-\\x7E]' THEN 1 ELSE 0 END) non_ascii,
              sum(CASE WHEN "{c}"='' THEN 1 ELSE 0 END) empty_str,
              count(DISTINCT "{c}") d_raw, count(DISTINCT trim("{c}")) d_trim,
              count(DISTINCT lower(trim("{c}"))) d_lower
              FROM {view}""")
        show(" UNION ALL ".join(parts), f"{view} key hygiene", rows=40)
    show("""SELECT count(DISTINCT vendor_id) ride_vendors, (SELECT count(DISTINCT vendor) FROM bill_raw) bill_vendors,
              (SELECT count(*) FROM (SELECT DISTINCT vendor_id v FROM ride_raw
                EXCEPT SELECT DISTINCT vendor FROM bill_raw)) in_ride_not_bill,
              (SELECT count(*) FROM (SELECT DISTINCT vendor v FROM bill_raw
                EXCEPT SELECT DISTINCT vendor_id FROM ride_raw)) in_bill_not_ride
            FROM ride_raw""", "vendor vocabulary alignment ride vs bill (join-by-name viability)")
    show("""SELECT v, src FROM (SELECT DISTINCT vendor_id v, 'ride_only' src FROM ride_raw
              EXCEPT SELECT DISTINCT vendor, 'ride_only' FROM bill_raw) LIMIT 30""",
         "vendors present in ride but absent in bill")
    show("""SELECT v FROM (SELECT DISTINCT vendor v FROM bill_raw
              EXCEPT SELECT DISTINCT vendor_id FROM ride_raw) LIMIT 30""",
         "vendors present in bill but absent in ride")
    show("""SELECT count(*) FROM (SELECT DISTINCT office o FROM ride_raw EXCEPT SELECT DISTINCT office FROM bill_raw)""",
         "offices in ride not in bill")
    show("""SELECT o FROM (SELECT DISTINCT office o FROM emp_raw EXCEPT SELECT DISTINCT office FROM ride_raw)""",
         "offices in emp not in ride")
    show("""SELECT count(*) n_cab_regs, count(DISTINCT actual_cab_registration) d,
                   count(DISTINCT upper(replace(actual_cab_registration,' ',''))) d_norm
            FROM ride_raw""", "cab registration normalisation (space/case collapse)")


# ==================================================================================
# STAGE 9 : BUSINESS IMPACT QUANTIFICATION
# ==================================================================================
def stage_impact():
    hdr("STAGE 9 -- BUSINESS IMPACT OF EACH QUALITY ISSUE")
    show("""SELECT round(sum(trip_cost),0) total_billed, count(*) bill_rows FROM bill""",
         "total billed money in the dataset")
    show("""SELECT
              round(sum(trip_cost) FILTER (WHERE trip_id IS NULL),0) unlinkable_cost,
              round(100.0*sum(trip_cost) FILTER (WHERE trip_id IS NULL)/sum(trip_cost),3) pct_unlinkable,
              count(*) FILTER (WHERE trip_id IS NULL) n_rows
            FROM bill""", "money on bill rows whose trip_id will not cast (OverHead)")
    con.sql("CREATE OR REPLACE TEMP TABLE tk AS SELECT DISTINCT trip_id FROM trips WHERE trip_id IS NOT NULL")
    show("""SELECT
              round(sum(b.trip_cost) FILTER (WHERE b.trip_id IS NOT NULL AND t.trip_id IS NULL),0) orphan_cost,
              round(100.0*sum(b.trip_cost) FILTER (WHERE b.trip_id IS NOT NULL AND t.trip_id IS NULL)/sum(b.trip_cost),3) pct,
              count(*) FILTER (WHERE b.trip_id IS NOT NULL AND t.trip_id IS NULL) n_rows
            FROM bill b LEFT JOIN tk t USING (trip_id)""",
         "money on bill rows with a valid id that matches NO ride trip -- unattributable to an operation")
    show("""SELECT
              round(sum(b.trip_cost),0) cost_attributable,
              round(100.0*sum(b.trip_cost)/(SELECT sum(trip_cost) FROM bill),3) pct
            FROM bill b JOIN tk t USING (trip_id)""", "money that IS attributable to a ride trip")
    show("""SELECT
              round(sum(trip_cost) FILTER (WHERE total_trip_km=0),0) fixed_rate_cost,
              round(100.0*sum(trip_cost) FILTER (WHERE total_trip_km=0)/sum(trip_cost),2) pct_of_spend,
              count(*) FILTER (WHERE total_trip_km=0) n_rows,
              round(100.0*count(*) FILTER (WHERE total_trip_km=0)/count(*),2) pct_rows
            FROM bill""", "spend that cannot yield a cost/km (zero-km fixed-rate)")
    show("""SELECT count(*) trips, round(100.0*count(*)/(SELECT count(*) FROM trips),3) pct
            FROM trips t WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)""",
         "ride trips with NO cost at all -- cannot be costed")
    show("""SELECT month, count(*) trips,
              count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)) uncosted,
              round(100.0*count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id))/count(*),2) pct
            FROM trips t GROUP BY 1 ORDER BY 1""", "uncosted trips by month -- is it a cycle-boundary artifact?")
    show("""SELECT business_unit, count(*) trips,
              count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id)) uncosted,
              round(100.0*count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bill b WHERE b.trip_id=t.trip_id))/count(*),2) pct
            FROM trips t GROUP BY 1 ORDER BY pct DESC""", "uncosted trips by BU")
    show("""SELECT count(*) trips, round(100.0*count(*)/(SELECT count(*) FROM trips),3) pct
            FROM trips t WHERE NOT EXISTS (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id)""",
         "trips with no feedback -- CSAT coverage gap")
    show("""SELECT month,
              count(*) trips,
              count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id)) with_fb,
              round(100.0*count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id))/count(*),2) coverage_pct
            FROM trips t GROUP BY 1 ORDER BY 1""", "feedback coverage by month")
    show("""SELECT t.business_unit, count(*) trips,
              round(100.0*count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id))/count(*),2) coverage_pct
            FROM trips t GROUP BY 1 ORDER BY coverage_pct""", "feedback coverage by BU")
    show("""SELECT round(100.0*count(*) FILTER (WHERE delay_minutes IS NULL)/count(*),4) pct_null_delay,
                   count(*) FILTER (WHERE delay_minutes IS NULL) n
            FROM trips""", "trips where OTA cannot be computed")
    show("""SELECT count(*) n, round(100.0*count(*)/(SELECT count(*) FROM emp),3) pct
            FROM emp WHERE stwid=0 OR stwid IS NULL""", "emp rows not attributable to a person")
    show("""SELECT count(*) n, round(100.0*count(*)/(SELECT count(*) FROM alerts),3) pct
            FROM alerts WHERE stwid=0 OR stwid IS NULL""", "alerts not attributable to a person")
    show("""SELECT event_type, count(*) n, count(*) FILTER (WHERE stwid=0) stw0,
                   round(100.0*count(*) FILTER (WHERE stwid=0)/count(*),2) pct
            FROM alerts GROUP BY 1 ORDER BY n DESC""", "stwid=0 by alert type -- is it type-specific (i.e. legit)?")
    show("""SELECT count(*) n, round(100.0*count(*)/(SELECT count(*) FROM fb),3) pct FROM fb WHERE stwid=0 OR stwid IS NULL""",
         "feedback not attributable to a person")
    show("""SELECT count(DISTINCT stwid) employees FROM emp WHERE stwid IS NOT NULL AND stwid<>0""",
         "distinct real employees")
    show("""SELECT count(*) FROM (SELECT DISTINCT stwid FROM fb WHERE stwid IS NOT NULL AND stwid<>0
              EXCEPT SELECT DISTINCT stwid FROM emp WHERE stwid IS NOT NULL AND stwid<>0)""",
         "feedback stwids that never appear in emp_Data (unknown employees)")
    show("""SELECT count(*) FROM (SELECT DISTINCT stwid FROM alerts WHERE stwid IS NOT NULL AND stwid<>0
              EXCEPT SELECT DISTINCT stwid FROM emp WHERE stwid IS NOT NULL AND stwid<>0)""",
         "alert stwids that never appear in emp_Data")
    show("""WITH pair AS (SELECT DISTINCT trip_id, stwid FROM fb WHERE stwid<>0)
            SELECT count(*) fb_pairs,
              count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM emp e WHERE e.trip_id=p.trip_id AND e.stwid=p.stwid)) not_on_trip,
              round(100.0*count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM emp e WHERE e.trip_id=p.trip_id AND e.stwid=p.stwid))/count(*),2) pct
            FROM pair p""", "feedback from employees NOT rostered on that trip (per emp_Data)")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    fns = {'profile':stage_profile,'refint':stage_refint,'dupes':stage_dupes,
           'impossible':stage_impossible,'dates':stage_dates,'drift':stage_drift,
           'categorical':stage_categorical,'whitespace':stage_whitespace,'impact':stage_impact,'collision':stage_collision,'semantics':stage_semantics,'outage':stage_outage,'final':stage_final}
    if stage == 'all':
        for f in fns.values():
            f()
    else:
        for s in stage.split(','):
            fns[s]()



# ==================================================================================
# STAGE 10 : DEEP DIVE ON THE trip_id COLLISION (the headline integrity defect)
# ==================================================================================
def stage_collision():
    hdr("STAGE 10 -- trip_id IS NOT A PRIMARY KEY: cross-month collision deep dive")
    con.sql("""CREATE OR REPLACE TEMP TABLE dup_ride AS
               SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1""")
    show("""SELECT count(*) n_colliding_ids FROM dup_ride""")
    show("""SELECT t.business_unit, count(DISTINCT t.trip_id) colliding_ids,
                   count(*) rows_affected,
                   (SELECT count(*) FROM trips x WHERE x.business_unit=t.business_unit) bu_rows,
                   round(100.0*count(*)/(SELECT count(*) FROM trips x WHERE x.business_unit=t.business_unit),3) pct_of_bu
            FROM trips t JOIN dup_ride d USING(trip_id) GROUP BY 1 ORDER BY colliding_ids DESC""",
         "which BUs suffer the collision")
    show("""SELECT t.office, count(DISTINCT t.trip_id) colliding_ids, count(*) rows_affected
            FROM trips t JOIN dup_ride d USING(trip_id) GROUP BY 1 ORDER BY colliding_ids DESC""",
         "which offices")
    show("""SELECT min(trip_id) mn, max(trip_id) mx, count(*) n FROM dup_ride""",
         "trip_id range of the colliding ids")
    show("""SELECT src_month, min(trip_date) mn, max(trip_date) mx, count(*) n
            FROM trips t JOIN dup_ride d USING(trip_id) GROUP BY 1 ORDER BY 1""",
         "when do the two copies occur")
    show("""SELECT t.trip_id, t.src_month, t.trip_date, t.business_unit, t.office,
                   t.vendor_id, t.trip_direction, t.shift_type, t.traveled_km, t.delay_minutes,
                   t.emp_actual
            FROM trips t JOIN dup_ride d USING(trip_id)
            WHERE t.trip_id IN (SELECT trip_id FROM dup_ride ORDER BY trip_id LIMIT 3)
            ORDER BY t.trip_id, t.trip_date""",
         "side-by-side: 3 colliding trip_ids, both rows -- clearly DIFFERENT real trips?")
    show("""SELECT count(*) FROM (
              SELECT trip_id FROM trips JOIN dup_ride USING(trip_id)
              GROUP BY trip_id HAVING count(DISTINCT trip_date)=1)""",
         "colliding ids where both rows share the SAME date (would mean true dup, not recycle)")
    show("""SELECT count(*) FROM (
              SELECT trip_id FROM trips JOIN dup_ride USING(trip_id)
              GROUP BY trip_id HAVING max(trip_date)-min(trip_date) > 30)""",
         "colliding ids where the two rows are >30 days apart (recycle, not dup)")
    show("""SELECT approx_quantile(gap,[0.0,0.5,1.0]) q, min(gap) mn, max(gap) mx FROM (
              SELECT trip_id, max(trip_date)-min(trip_date) gap
              FROM trips JOIN dup_ride USING(trip_id) GROUP BY 1)""",
         "day-gap between the two copies")

    hdr("STAGE 10b -- does the collision propagate into emp / bill / feedback?")
    show("""SELECT count(*) emp_rows_on_colliding_ids,
                   round(100.0*count(*)/(SELECT count(*) FROM emp),3) pct_of_emp,
                   count(DISTINCT trip_id) ids
            FROM emp e WHERE trip_id IN (SELECT trip_id FROM dup_ride)""",
         "emp rows sitting on a colliding trip_id (their trip context is ambiguous)")
    show("""SELECT dates_per_id, count(*) ids FROM (
              SELECT trip_id, count(DISTINCT trip_date) dates_per_id FROM emp
              WHERE trip_id IN (SELECT trip_id FROM dup_ride) GROUP BY 1)
            GROUP BY 1 ORDER BY 1""", "emp rows per colliding id: how many distinct dates")
    show("""SELECT count(*) ids_with_2_dates FROM (
              SELECT trip_id FROM emp WHERE trip_id IN (SELECT trip_id FROM dup_ride)
              GROUP BY 1 HAVING count(DISTINCT trip_date)>1)""",
         "colliding ids whose emp rows ALSO span 2 dates -> emp carries the recycle too")
    con.sql("""CREATE OR REPLACE TEMP TABLE dup_bill AS
               SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1""")
    show("""SELECT (SELECT count(*) FROM dup_bill) bill_dup_ids,
                   (SELECT count(*) FROM dup_ride) ride_dup_ids,
                   (SELECT count(*) FROM dup_bill JOIN dup_ride USING(trip_id)) in_both,
                   (SELECT count(*) FROM (SELECT trip_id FROM dup_bill EXCEPT SELECT trip_id FROM dup_ride)) bill_only,
                   (SELECT count(*) FROM (SELECT trip_id FROM dup_ride EXCEPT SELECT trip_id FROM dup_bill)) ride_only""",
         "do bill duplicates == ride collisions? (if yes -> recycle, if no -> double-billing)")
    show("""SELECT b.trip_id, b.cycle_start, b.vendor, b.contract, b.total_trip_km, b.trip_cost
            FROM bill b JOIN dup_bill d USING(trip_id)
            WHERE b.trip_id IN (SELECT trip_id FROM dup_bill ORDER BY trip_id LIMIT 3)
            ORDER BY b.trip_id, b.cycle_start""",
         "side-by-side: 3 duplicated bill trip_ids")
    show("""SELECT round(sum(trip_cost),2) money_on_ambiguous_ids,
                   round(100.0*sum(trip_cost)/(SELECT sum(trip_cost) FROM bill),3) pct_of_spend,
                   count(*) n_rows
            FROM bill b WHERE trip_id IN (SELECT trip_id FROM dup_bill)""",
         "IMPACT: money that cannot be attributed to ONE unique trip")
    show("""SELECT count(*) fanout_rows FROM trips t JOIN bill b USING(trip_id)""",
         "rows produced by a naive trips-JOIN-bill on trip_id")
    show("""SELECT (SELECT count(*) FROM trips) ride_rows,
                   (SELECT count(*) FROM bill WHERE trip_id IS NOT NULL) bill_rows,
                   (SELECT count(*) FROM trips t JOIN bill b USING(trip_id)) join_rows,
                   (SELECT count(*) FROM trips t JOIN bill b USING(trip_id))
                     - (SELECT count(*) FROM bill WHERE trip_id IS NOT NULL) inflation""",
         "FAN-OUT: naive join inflates row count by this much")
    show("""SELECT round(sum(b.trip_cost),2) inflated_total,
                   (SELECT round(sum(trip_cost),2) FROM bill) true_total,
                   round(sum(b.trip_cost) - (SELECT sum(trip_cost) FROM bill),2) overstatement
            FROM trips t JOIN bill b USING(trip_id)""",
         "IMPACT: naive join OVERSTATES total spend by this rupee amount")

    hdr("STAGE 10c -- the safe composite key")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, trip_date)) d_pairs,
                   count(*)-count(DISTINCT (trip_id, trip_date)) still_dup
            FROM trips""", "is (trip_id, trip_date) unique in ride_data?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, business_unit)) d, count(*)-count(DISTINCT (trip_id,business_unit)) still_dup
            FROM trips""", "is (trip_id, business_unit) unique?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, src_month)) d, count(*)-count(DISTINCT (trip_id,src_month)) still_dup
            FROM trips""", "is (trip_id, source month file) unique?")
    show("""SELECT count(*) n_rows,
                   count(DISTINCT (trip_id, business_unit, trip_date)) d,
                   count(*)-count(DISTINCT (trip_id, business_unit, trip_date)) still_dup
            FROM trips""", "is (trip_id, business_unit, trip_date) unique?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, trip_date)) d,
                   count(*)-count(DISTINCT (trip_id, trip_date)) still_dup
            FROM emp""", "does (trip_id, trip_date, stwid) fix emp?")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, trip_date, stwid)) d,
                   count(*)-count(DISTINCT (trip_id, trip_date, stwid)) still_dup,
                   count(*) FILTER (WHERE stwid=0) stw0_rows
            FROM emp""", "emp: (trip_id, trip_date, stwid) uniqueness")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, stwid)) d,
                   count(*)-count(DISTINCT (trip_id,stwid)) excess
            FROM emp WHERE stwid<>0""", "emp: (trip_id, stwid) uniqueness EXCLUDING the stwid=0 placeholder")
    show("""SELECT count(*) n_rows, count(DISTINCT (trip_id, trip_date, stwid)) d,
                   count(*)-count(DISTINCT (trip_id,trip_date,stwid)) excess
            FROM emp WHERE stwid<>0""", "emp: (trip_id, trip_date, stwid) EXCLUDING stwid=0")
    show("""SELECT count(*) FROM emp WHERE stwid=0""", "how many emp rows are the stwid=0 placeholder")
    show("""SELECT business_unit, product_type, boarding_status, count(*) n
            FROM emp WHERE stwid=0 GROUP BY 1,2,3 ORDER BY n DESC LIMIT 20""",
         "what ARE the stwid=0 emp rows -- real signal or padding?")
    show("""SELECT count(DISTINCT trip_id) trips_with_stw0,
                   round(100.0*count(DISTINCT trip_id)/(SELECT count(DISTINCT trip_id) FROM emp),2) pct_trips
            FROM emp WHERE stwid=0""", "how many trips carry at least one stwid=0 row")




# ==================================================================================
# STAGE 11 : SEMANTICS AUDIT -- what does delay_minutes actually measure?
# ==================================================================================
def stage_semantics():
    hdr("STAGE 11 -- delay_minutes SEMANTICS: it does NOT equal actual_end - planned_end")
    show("""SELECT
      count(*) n,
      count(*) FILTER (WHERE abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<=1)   agree_END,
      count(*) FILTER (WHERE abs(delay_minutes-(actual_start_epoch-planned_start_epoch)/60.0)<=1) agree_START,
      count(*) FILTER (WHERE abs(delay_minutes-((actual_end_epoch-actual_start_epoch)-(planned_end_epoch-planned_start_epoch))/60.0)<=1) agree_DURATION,
      count(*) FILTER (WHERE delay_minutes=0) exactly_zero
    FROM trips""", "which definition does delay_minutes match?")
    show("""SELECT trip_direction,
      count(*) n,
      round(100.0*count(*) FILTER (WHERE abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<=1)/count(*),2) pct_END,
      round(100.0*count(*) FILTER (WHERE abs(delay_minutes-(actual_start_epoch-planned_start_epoch)/60.0)<=1)/count(*),2) pct_START,
      round(100.0*count(*) FILTER (WHERE abs(delay_minutes-((actual_end_epoch-actual_start_epoch)-(planned_end_epoch-planned_start_epoch))/60.0)<=1)/count(*),2) pct_DUR
    FROM trips GROUP BY 1""", "split by direction (LOGIN measures arrival, LOGOUT measures departure)")
    show("""SELECT src_month,
      round(100.0*count(*) FILTER (WHERE abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<=1)/count(*),2) pct_END,
      round(100.0*count(*) FILTER (WHERE delay_minutes=0)/count(*),2) pct_zero,
      round(avg(delay_minutes),2) avg_delay,
      round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) avg_epoch_end_delay
    FROM trips GROUP BY 1 ORDER BY 1""", "by month")
    show("""SELECT
      round(100.0*count(*) FILTER (WHERE delay_minutes=0)/count(*),2) pct_delay_zero,
      round(100.0*count(*) FILTER (WHERE delay_minutes=0 AND actual_end_epoch<=planned_end_epoch)/count(*),2) pct_zero_and_early,
      round(100.0*count(*) FILTER (WHERE delay_minutes=0 AND actual_end_epoch>planned_end_epoch)/count(*),2) pct_zero_but_late,
      round(100.0*count(*) FILTER (WHERE delay_minutes>0 AND actual_end_epoch<=planned_end_epoch)/count(*),2) pct_pos_but_early
    FROM trips""", "the zero-delay population dissected")
    show("""SELECT delay_reason, count(*) n,
      round(100.0*count(*) FILTER (WHERE delay_minutes=0)/count(*),2) pct_zero,
      round(avg(delay_minutes),2) avg_delay,
      round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) avg_epoch_delay
    FROM trips GROUP BY 1 ORDER BY n DESC""", "delay_reason vs delay_minutes -- is NODELAY the zero bucket?")
    show("""SELECT count(*) n,
      count(*) FILTER (WHERE delay_reason='NODELAY' AND delay_minutes>0) nodelay_but_positive,
      count(*) FILTER (WHERE delay_reason<>'NODELAY' AND delay_minutes=0) reason_but_zero,
      round(100.0*count(*) FILTER (WHERE delay_reason='NODELAY' AND delay_minutes>0)/count(*),3) pct_a,
      round(100.0*count(*) FILTER (WHERE delay_reason<>'NODELAY' AND delay_minutes=0)/count(*),3) pct_b
    FROM trips""", "delay_reason vs delay_minutes contradiction")
    show("""SELECT
      round(100.0*count(*) FILTER (WHERE delay_minutes<=5)/count(*),2) ota_from_delay_col,
      round(100.0*count(*) FILTER (WHERE (actual_end_epoch-planned_end_epoch)/60.0<=5)/count(*),2) ota_from_end_epoch,
      round(100.0*count(*) FILTER (WHERE (actual_start_epoch-planned_start_epoch)/60.0<=5)/count(*),2) ota_from_start_epoch
    FROM trips""", "IMPACT: OTA computed 3 different ways gives 3 different answers")
    show("""SELECT month,
      round(100.0*count(*) FILTER (WHERE delay_minutes<=5)/count(*),2) ota_delay_col,
      round(100.0*count(*) FILTER (WHERE (actual_end_epoch-planned_end_epoch)/60.0<=5)/count(*),2) ota_end_epoch
    FROM trips GROUP BY 1 ORDER BY 1""", "does the month-over-month STORY change with the definition?")

    hdr("STAGE 11b -- ride.actualemployee_cnt vs emp_Data: the off-by-one")
    show("""WITH e AS (SELECT trip_id, trip_date, count(*) n_all,
                        count(*) FILTER (WHERE boarding_status='Boarded') n_boarded,
                        count(*) FILTER (WHERE NOT is_no_show) n_notnoshow
                 FROM emp GROUP BY 1,2)
            SELECT count(*) trips,
              round(100.0*count(*) FILTER (WHERE t.emp_actual=e.n_all)/count(*),2) match_all,
              round(100.0*count(*) FILTER (WHERE t.emp_actual=e.n_boarded)/count(*),2) match_boarded,
              round(100.0*count(*) FILTER (WHERE t.emp_actual=e.n_notnoshow)/count(*),2) match_notnoshow,
              round(100.0*count(*) FILTER (WHERE t.emp_planned=e.n_all)/count(*),2) planned_match_all
            FROM trips t JOIN e ON t.trip_id=e.trip_id AND t.trip_date=e.trip_date""",
         "which emp_Data aggregate reproduces actualemployee_cnt / plannedemployee_cnt?")
    show("""WITH e AS (SELECT trip_id, trip_date, count(*) n_all,
                        count(*) FILTER (WHERE boarding_status='Boarded') n_boarded FROM emp GROUP BY 1,2)
            SELECT t.emp_actual - e.n_boarded AS diff, count(*) n
            FROM trips t JOIN e ON t.trip_id=e.trip_id AND t.trip_date=e.trip_date
            GROUP BY 1 ORDER BY n DESC LIMIT 12""", "residual distribution vs n_boarded")

    hdr("STAGE 11c -- CROSS-FILE MISMATCH, NET OF THE trip_id COLLISION")
    con.sql("""CREATE OR REPLACE TEMP TABLE dup2 AS SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1""")
    show("""SELECT count(*) n_rows,
              count(*) FILTER (WHERE t.business_unit<>e.business_unit) bu_mm,
              count(*) FILTER (WHERE t.trip_date<>e.trip_date) date_mm,
              count(*) FILTER (WHERE t.office<>e.office) office_mm
            FROM trips t JOIN emp e USING(trip_id)
            WHERE t.trip_id NOT IN (SELECT trip_id FROM dup2)""",
         "ride vs emp mismatches AFTER removing colliding ids")
    show("""SELECT count(*) n_rows,
              count(*) FILTER (WHERE t.business_unit<>b.business_unit) bu_mm,
              count(*) FILTER (WHERE t.vendor_id<>b.vendor) vendor_mm,
              round(100.0*count(*) FILTER (WHERE t.vendor_id<>b.vendor)/count(*),3) pct_vendor_mm
            FROM trips t JOIN bill b USING(trip_id)
            WHERE t.trip_id NOT IN (SELECT trip_id FROM dup2)""",
         "ride vs bill mismatches AFTER removing colliding ids -- residual is REAL")
    show("""SELECT t.vendor_id ride_vendor, b.vendor bill_vendor, count(*) n
            FROM trips t JOIN bill b USING(trip_id)
            WHERE t.trip_id NOT IN (SELECT trip_id FROM dup2) AND t.vendor_id<>b.vendor
            GROUP BY 1,2 ORDER BY n DESC LIMIT 20""",
         "the REAL ride-vs-bill vendor disagreements: which pairs?")
    show("""SELECT count(*) n_rows,
              count(*) FILTER (WHERE t.business_unit<>f.business_unit) bu_mm,
              count(*) FILTER (WHERE t.trip_direction<>f.trip_type) dir_mm
            FROM trips t JOIN fb f USING(trip_id)
            WHERE t.trip_id NOT IN (SELECT trip_id FROM dup2)""",
         "ride vs feedback AFTER removing colliding ids")
    show("""SELECT count(*) n_rows, count(*) FILTER (WHERE t.business_unit<>a.business_unit) bu_mm
            FROM trips t JOIN alerts a USING(trip_id)
            WHERE t.trip_id NOT IN (SELECT trip_id FROM dup2)""",
         "ride vs alerts AFTER removing colliding ids")

    hdr("STAGE 11d -- emp 'Not Boarded' vs is_no_show: two disagreeing no-show definitions")
    show("""SELECT boarding_status, is_no_show, not_boarding_reason, count(*) n,
                   round(100.0*count(*)/sum(count(*)) OVER (),3) pct
            FROM emp GROUP BY 1,2,3 ORDER BY n DESC""",
         "full cross-tab: boarding_status x is_no_show x reason")
    show("""SELECT round(100.0*count(*) FILTER (WHERE boarding_status='Not Boarded')/count(*),3) noshow_rate_by_status,
                   round(100.0*count(*) FILTER (WHERE is_no_show)/count(*),3) noshow_rate_by_flag,
                   count(*) FILTER (WHERE boarding_status='Not Boarded') n_status,
                   count(*) FILTER (WHERE is_no_show) n_flag
            FROM emp""", "IMPACT: the two definitions give different no-show rates")
    show("""SELECT not_boarding_reason, count(*) n, count(*) FILTER (WHERE is_no_show) flagged,
                   round(100.0*count(*) FILTER (WHERE is_no_show)/count(*),2) pct_flagged
            FROM emp WHERE boarding_status='Not Boarded' GROUP BY 1 ORDER BY n DESC""",
         "which non-boarding reasons count as a no-show?")

    hdr("STAGE 11e -- feedback timestamps: trip_date is the SHIFT time, not the trip time")
    show("""SELECT count(*) n,
              count(*) FILTER (WHERE f.creation_ts < f.trip_ts) before_shift,
              count(*) FILTER (WHERE f.creation_ts < to_timestamp(t.actual_start_epoch)) before_actual_start,
              count(*) FILTER (WHERE f.creation_ts < to_timestamp(t.actual_end_epoch)) before_actual_end,
              round(100.0*count(*) FILTER (WHERE f.creation_ts < to_timestamp(t.actual_end_epoch))/count(*),2) pct_before_end
            FROM fb f JOIN trips t ON f.trip_id=t.trip_id AND CAST(f.trip_ts AS DATE)=t.trip_date""",
         "feedback created before the trip even ended?")
    show("""SELECT count(*) n_late, min(creation_ts) mn, max(creation_ts) mx
            FROM fb WHERE creation_ts > TIMESTAMP '2026-07-31 23:59:59'""",
         "feedback arriving AFTER the data window closes")
    show("""SELECT date_trunc('month',creation_ts) mo, count(*) n FROM fb GROUP BY 1 ORDER BY 1""",
         "feedback rows by CREATION month vs trip month")
    show("""SELECT date_trunc('month',trip_ts) trip_mo, date_trunc('month',creation_ts) create_mo, count(*) n
            FROM fb GROUP BY 1,2 ORDER BY 1,2""",
         "trip month x creation month matrix -- August tail")




# ==================================================================================
# STAGE 12 : COLLECTION OUTAGES (days where a FILE stops, not where operations stop)
# ==================================================================================
def stage_outage():
    hdr("STAGE 12 -- FEEDBACK COLLECTION OUTAGE (a data gap that mimics a CSAT collapse)")
    show("""WITH d AS (
      SELECT t.trip_date d, count(DISTINCT t.trip_id) trips,
             count(DISTINCT f.trip_id) trips_with_fb
      FROM trips t LEFT JOIN fb f ON f.trip_id=t.trip_id AND CAST(f.trip_ts AS DATE)=t.trip_date
      GROUP BY 1)
    SELECT d, dayname(d) dow, trips, trips_with_fb,
           round(100.0*trips_with_fb/trips,2) coverage_pct
    FROM d WHERE d BETWEEN DATE '2026-05-22' AND DATE '2026-06-05' ORDER BY d""",
    "feedback coverage around the suspected outage")
    show("""WITH d AS (
      SELECT t.trip_date d, count(DISTINCT t.trip_id) trips, count(DISTINCT f.trip_id) wf
      FROM trips t LEFT JOIN fb f ON f.trip_id=t.trip_id AND CAST(f.trip_ts AS DATE)=t.trip_date
      GROUP BY 1)
    SELECT dayname(d) dow, count(*) n_days, round(avg(100.0*wf/trips),2) avg_coverage_pct,
           round(min(100.0*wf/trips),2) mn, round(max(100.0*wf/trips),2) mx
    FROM d WHERE dayname(d) NOT IN ('Saturday','Sunday') GROUP BY 1 ORDER BY avg_coverage_pct""",
    "weekday feedback coverage baseline (so the outage is measured against something)")
    show("""WITH d AS (
      SELECT t.trip_date d, count(DISTINCT t.trip_id) trips, count(DISTINCT f.trip_id) wf
      FROM trips t LEFT JOIN fb f ON f.trip_id=t.trip_id AND CAST(f.trip_ts AS DATE)=t.trip_date
      GROUP BY 1)
    SELECT d, dayname(d) dow, trips, wf, round(100.0*wf/trips,2) coverage_pct
    FROM d WHERE 100.0*wf/trips < 30 ORDER BY d""",
    "ALL weekdays/days where feedback coverage collapses below 30%")
    show("""SELECT count(*) affected_trips,
                   round(100.0*count(*)/(SELECT count(*) FROM trips),2) pct_of_all_trips
            FROM trips WHERE trip_date BETWEEN DATE '2026-05-28' AND DATE '2026-06-01'""",
    "IMPACT: trips inside the outage window whose CSAT is unmeasurable")

    hdr("STAGE 12b -- ALERTS VOLUME STEP-CHANGE: when exactly, and which event_type")
    show("""SELECT CAST(start_ts AS DATE) d, dayname(start_ts) dow, count(*) n,
              count(*) FILTER (WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION') signoff,
              count(*) FILTER (WHERE event_type<>'EMPLOYEE_SIGN_OFF_TIME_VIOLATION') other
            FROM alerts WHERE start_ts < TIMESTAMP '2026-06-05' GROUP BY 1,2 ORDER BY 1""",
    "daily alert volume through the step-change", rows=60)
    show("""SELECT event_type,
              count(*) FILTER (WHERE start_ts < TIMESTAMP '2026-05-18') n_before,
              count(*) FILTER (WHERE start_ts >= TIMESTAMP '2026-05-18') n_after,
              count(*) n
            FROM alerts GROUP BY 1 ORDER BY n DESC""",
    "which event types stop on May 18")
    show("""SELECT severity, source,
              count(*) FILTER (WHERE start_ts < TIMESTAMP '2026-05-18') n_before,
              count(*) FILTER (WHERE start_ts >= TIMESTAMP '2026-05-18') n_after
            FROM alerts GROUP BY 1,2 ORDER BY n_before DESC""",
    "does the severity='False' / source='NA' sentinel appear only in one era?")
    show("""SELECT event_type, severity, count(*) n FROM alerts GROUP BY 1,2 ORDER BY 1,3 DESC""",
    "severity vocabulary per event_type -- is 'False' a per-type default?", rows=60)

    hdr("STAGE 12c -- OPERATIONAL VOLUME DIP May 28-29 (real, or a ride-file gap?)")
    show("""SELECT t.trip_date d, dayname(t.trip_date) dow, count(*) trips,
              count(DISTINCT t.office) offices, count(DISTINCT t.business_unit) bus,
              count(DISTINCT t.vendor_id) vendors
            FROM trips t WHERE t.trip_date BETWEEN DATE '2026-05-25' AND DATE '2026-06-02'
            GROUP BY 1 ORDER BY 1""", "structure of the May 28-29 dip")
    show("""SELECT business_unit,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-21') thu_may21,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-28') thu_may28,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-22') fri_may22,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-29') fri_may29
            FROM trips GROUP BY 1 ORDER BY 1""",
    "which BU disappears on May 28-29 (like-for-like weekday comparison)")

    hdr("STAGE 12d -- TIMEZONE TRAP: epochs are UTC but shift_type is local")
    show("""SELECT shift_type,
              count(*) n,
              mode(strftime(to_timestamp(planned_start_epoch) AT TIME ZONE 'UTC','%H:%M')) modal_utc_hhmm,
              mode(strftime(to_timestamp(planned_start_epoch) AT TIME ZONE 'Asia/Kolkata','%H:%M')) modal_ist_hhmm
            FROM trips WHERE trip_direction='LOGOUT' AND shift_type ~ '^[0-9]{2}:[0-9]{2}$'
            GROUP BY 1 ORDER BY n DESC LIMIT 12""",
    "does shift_type match the UTC or the IST rendering of planned_start_epoch?")
    show("""SELECT
      round(100.0*count(*) FILTER (WHERE strftime(to_timestamp(planned_start_epoch) AT TIME ZONE 'UTC','%H:%M')=shift_type)/count(*),2) pct_match_utc,
      round(100.0*count(*) FILTER (WHERE strftime(to_timestamp(planned_start_epoch) AT TIME ZONE 'Asia/Kolkata','%H:%M')=shift_type)/count(*),2) pct_match_ist,
      count(*) n
    FROM trips WHERE trip_direction='LOGOUT' AND shift_type ~ '^[0-9]{2}:[0-9]{2}$'""",
    "LOGOUT: planned_start should equal the shift end time")
    show("""SELECT
      round(100.0*count(*) FILTER (WHERE strftime(to_timestamp(planned_end_epoch) AT TIME ZONE 'UTC','%H:%M')=shift_type)/count(*),2) pct_match_utc,
      round(100.0*count(*) FILTER (WHERE strftime(to_timestamp(planned_end_epoch) AT TIME ZONE 'Asia/Kolkata','%H:%M')=shift_type)/count(*),2) pct_match_ist,
      count(*) n
    FROM trips WHERE trip_direction='LOGIN' AND shift_type ~ '^[0-9]{2}:[0-9]{2}$'""",
    "LOGIN: planned_end should equal the shift start time")
    show("""SELECT count(*) n,
      round(100.0*count(*) FILTER (WHERE CAST(to_timestamp(planned_start_epoch) AT TIME ZONE 'UTC' AS DATE)=trip_date)/count(*),2) pct_date_match_utc,
      round(100.0*count(*) FILTER (WHERE CAST(to_timestamp(planned_start_epoch) AT TIME ZONE 'Asia/Kolkata' AS DATE)=trip_date)/count(*),2) pct_date_match_ist
    FROM trips""", "which timezone reproduces trip_date from the epoch?")

    hdr("STAGE 12e -- the 246 bill-only duplicate trip_ids (NOT explained by the collision)")
    con.sql("""CREATE OR REPLACE TEMP TABLE bo AS
      SELECT trip_id FROM bill WHERE trip_id IS NOT NULL GROUP BY 1 HAVING count(*)>1
      EXCEPT SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1""")
    show("""SELECT count(*) n_bill_only_dup_ids FROM bo""")
    show("""SELECT b.business_unit, count(DISTINCT b.trip_id) ids, count(*) n_rows,
                   round(sum(b.trip_cost),2) amt
            FROM bill b JOIN bo USING(trip_id) GROUP BY 1 ORDER BY n_rows DESC""",
    "which BU")
    show("""SELECT b.trip_id, b.cycle_start, b.vendor, b.contract, b.slab_name,
                   b.total_trip_km, b.trip_cost
            FROM bill b JOIN bo USING(trip_id)
            WHERE b.trip_id IN (SELECT trip_id FROM bo ORDER BY trip_id LIMIT 4)
            ORDER BY b.trip_id, b.cycle_start""",
    "examples: same trip billed twice?")
    show("""WITH x AS (SELECT b.trip_id, count(*) n, count(DISTINCT b.cycle_start) cycles,
                              count(DISTINCT b.vendor) vendors, count(DISTINCT b.contract) contracts,
                              count(DISTINCT b.trip_cost) costs, sum(b.trip_cost) amt
                       FROM bill b JOIN bo USING(trip_id) GROUP BY 1)
            SELECT cycles, vendors, contracts, costs, count(*) ids, round(sum(amt),2) total_amt
            FROM x GROUP BY 1,2,3,4 ORDER BY ids DESC""",
    "profile: are the two lines identical (true double-bill) or different cycles?")
    show("""SELECT round(sum(b.trip_cost),2) exposure,
                   round(100.0*sum(b.trip_cost)/(SELECT sum(trip_cost) FROM bill),4) pct_of_spend
            FROM bill b JOIN bo USING(trip_id)""",
    "IMPACT: money on genuinely double-lined trips")




# ==================================================================================
# STAGE 13 : REMAINING QUIRKS
# ==================================================================================
def stage_final():
    hdr("STAGE 13a -- bill.slab_name: 30 raw labels collapse to how many real slabs?")
    con.sql("""CREATE OR REPLACE VIEW bill_slab AS SELECT *,
      CASE
        WHEN slab_name IN ('null','NA','0') THEN 'UNLABELLED'
        ELSE upper(regexp_replace(regexp_replace(replace(slab_name,'kms',''),'^Slab[- ]?',''),'[ _-]+',''))
      END AS slab_norm FROM bill""")
    show("""SELECT slab_norm, count(DISTINCT slab_name) raw_variants,
                   string_agg(DISTINCT slab_name) variants, count(*) n,
                   round(sum(trip_cost),0) amt
            FROM bill_slab GROUP BY 1 HAVING count(DISTINCT slab_name)>1
            ORDER BY n DESC""", "slab labels that are the SAME slab written differently")
    show("""SELECT count(DISTINCT slab_name) raw_labels, count(DISTINCT slab_norm) normalised_labels
            FROM bill_slab""", "cardinality before/after normalisation")
    show("""SELECT round(sum(trip_cost),0) money_in_split_buckets,
                   round(100.0*sum(trip_cost)/(SELECT sum(trip_cost) FROM bill),2) pct_of_spend,
                   count(*) n_rows
            FROM bill_slab WHERE slab_norm IN
              (SELECT slab_norm FROM bill_slab GROUP BY 1 HAVING count(DISTINCT slab_name)>1)""",
         "IMPACT: money mis-bucketed by a naive GROUP BY slab_name")
    show("""SELECT round(sum(trip_cost),0) unlabelled_spend,
                   round(100.0*sum(trip_cost)/(SELECT sum(trip_cost) FROM bill),2) pct,
                   count(*) n_rows
            FROM bill_slab WHERE slab_norm='UNLABELLED'""",
         "IMPACT: spend with no usable slab label at all")

    hdr("STAGE 13b -- the 24th vendor: bills but never operates")
    show("""SELECT vendor, count(*) n_rows, round(sum(trip_cost),2) amt,
                   count(DISTINCT contract) contracts, count(DISTINCT business_unit) bus,
                   min(cycle_start) first_cycle, max(cycle_start) last_cycle,
                   count(*) FILTER (WHERE trip_id_raw='OverHead') overhead_rows
            FROM bill WHERE vendor='Neha Mikhailov Travel' GROUP BY 1""",
         "Neha Mikhailov Travel: appears in bill_data but never in ride_data")
    show("""SELECT count(*) n, count(*) FILTER (WHERE t.trip_id IS NOT NULL) matched_a_ride_trip
            FROM bill b LEFT JOIN (SELECT DISTINCT trip_id FROM trips) t USING(trip_id)
            WHERE b.vendor='Neha Mikhailov Travel'""",
         "do any of its rows join to a real trip?")

    hdr("STAGE 13c -- negative money concentration")
    show("""SELECT business_unit, vendor, contract, count(*) n, round(sum(trip_cost),2) amt
            FROM bill WHERE trip_cost<0 GROUP BY 1,2,3 ORDER BY amt LIMIT 15""",
         "who owns the -15.5M")
    show("""SELECT contract, count(*) n_rows,
                   round(sum(trip_cost) FILTER (WHERE trip_cost>0),2) positive,
                   round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) negative,
                   round(sum(trip_cost),2) net
            FROM bill WHERE contract='6S-PREMIUMNEW' GROUP BY 1""",
         "6S-PREMIUMNEW: a contract whose NET spend is negative")
    show("""SELECT date_trunc('month',cycle_start) mo, count(*) n,
                   round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credits,
                   round(sum(trip_cost),2) net
            FROM bill GROUP BY 1 ORDER BY 1""",
         "credits by cycle month -- all in May?")
    show("""SELECT business_unit,
                   round(sum(trip_cost),2) net_spend,
                   round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credits,
                   round(100.0*abs(coalesce(sum(trip_cost) FILTER (WHERE trip_cost<0),0))/sum(trip_cost) FILTER (WHERE trip_cost>0),3) credit_pct_of_gross
            FROM bill GROUP BY 1 ORDER BY credits""",
         "IMPACT: credit exposure by BU")

    hdr("STAGE 13d -- emp_role: 'escort' and 'projectmgr' inflate occupancy")
    show("""SELECT emp_role, count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),3) pct,
                   count(*) FILTER (WHERE boarding_status='Boarded') boarded
            FROM emp WHERE emp_role IN ('employee','escort','projectmgr','vendormgr')
            GROUP BY 1 ORDER BY n DESC""", "the big role buckets")
    show("""SELECT count(*) trips,
              round(avg(n_all),3) avg_seats_all_roles,
              round(avg(n_emp_only),3) avg_seats_employees_only,
              round(avg(n_all)-avg(n_emp_only),3) inflation_per_trip
            FROM (SELECT trip_id, trip_date,
                    count(*) FILTER (WHERE boarding_status='Boarded') n_all,
                    count(*) FILTER (WHERE boarding_status='Boarded' AND emp_role='employee') n_emp_only
                  FROM emp GROUP BY 1,2)""",
         "IMPACT: occupancy overstated if escorts/managers are counted as riders")
    show("""SELECT round(100.0*sum(n_all)/sum(cap),2) util_all_roles,
                   round(100.0*sum(n_emp)/sum(cap),2) util_employees_only
            FROM (SELECT t.trip_id, t.trip_date, max(t.cab_capacity) cap,
                    count(*) FILTER (WHERE e.boarding_status='Boarded') n_all,
                    count(*) FILTER (WHERE e.boarding_status='Boarded' AND e.emp_role='employee') n_emp
                  FROM trips t JOIN emp e ON t.trip_id=e.trip_id AND t.trip_date=e.trip_date
                  GROUP BY 1,2)""",
         "IMPACT: fleet utilisation, two ways")

    hdr("STAGE 13e -- the pinnacle-Slc May 28 gap: operational or a source-file gap?")
    show("""SELECT d,
              (SELECT count(*) FROM trips t WHERE t.trip_date=x.d AND t.business_unit='pinnacle-Slc') ride,
              (SELECT count(*) FROM emp e WHERE e.trip_date=x.d AND e.business_unit='pinnacle-Slc') emp,
              (SELECT count(*) FROM fb f WHERE CAST(f.trip_ts AS DATE)=x.d AND f.business_unit='pinnacle-Slc') fb,
              (SELECT count(*) FROM alerts a WHERE CAST(a.start_ts AS DATE)=x.d AND a.business_unit='pinnacle-Slc') alerts
            FROM (SELECT unnest(generate_series(DATE '2026-05-25', DATE '2026-06-02', INTERVAL 1 DAY))::DATE d) x
            ORDER BY d""",
         "pinnacle-Slc across ALL FOUR files -- does every file drop together?")
    show("""SELECT b.office, count(*) n_may28_bill
            FROM bill b JOIN trips t USING(trip_id)
            WHERE t.trip_date=DATE '2026-05-28' AND t.business_unit='pinnacle-Slc'
            GROUP BY 1 ORDER BY n_may28_bill DESC""",
         "are the surviving May-28 pinnacle trips billed (i.e. the gap is upstream of billing too)?")
    show("""SELECT office,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-21') thu_21,
              count(*) FILTER (WHERE trip_date=DATE '2026-05-28') thu_28
            FROM trips WHERE business_unit='pinnacle-Slc' GROUP BY 1 ORDER BY thu_21 DESC""",
         "which pinnacle offices vanish on May 28")

    hdr("STAGE 13f -- 'planned' fields that are not plans")
    show("""SELECT count(*) n,
              count(*) FILTER (WHERE planned_km=0) planned_zero,
              count(*) FILTER (WHERE planned_km=0 AND traveled_km>0) planned_zero_but_travelled,
              round(avg(traveled_km) FILTER (WHERE planned_km=0),2) avg_travelled_when_planned_zero
            FROM trips""", "planned_km=0 but the cab moved")
    show("""SELECT product_type, route_source, count(*) n
            FROM trips WHERE planned_km=0 GROUP BY 1,2 ORDER BY n DESC LIMIT 10""",
         "what kind of trip has planned_km=0")
    show("""SELECT count(*) n_over_capacity,
              round(100.0*count(*)/(SELECT count(*) FROM trips),4) pct,
              max(emp_actual-cab_capacity) worst_overload
            FROM trips WHERE emp_actual>cab_capacity""", "occupancy > capacity")
    show("""SELECT product_type, cab_capacity, count(*) n, max(emp_actual) max_seen
            FROM trips WHERE emp_actual>cab_capacity GROUP BY 1,2 ORDER BY n DESC LIMIT 12""",
         "over-capacity by product/capacity -- is it a BUS mis-recorded capacity?")
    show("""SELECT count(*) n, round(100.0*count(*)/(SELECT count(*) FROM trips),4) pct
            FROM trips WHERE planned_end_epoch<=planned_start_epoch""",
         "planned trips that end before they start")
    show("""SELECT trip_direction, product_type, count(*) n
            FROM trips WHERE planned_end_epoch<=planned_start_epoch GROUP BY 1,2 ORDER BY n DESC""",
         "who are they")


if __name__ == '__main__':
    main()
