#!/usr/bin/env python
"""
synthesis2.py — independent re-verification of headline numbers claimed in
docs/findings/{timeliness,cost,safety,employees,feedback,dataquality,crosstable}.md
before they are promoted into docs/FINDINGS.md.

Nothing here is copied from another agent's write-up: every number is re-derived
from the raw CSVs. Sections that adjudicate a CONFLICT between two agents are
marked  # CONFLICT.

Run:  .venv/bin/python tools/analysis/synthesis2.py [section ...]
      sections: base ota reason shift spot dow load ids bill over slab fb fbcov
                marshal emp esc esc2 rider vendor alerts misc
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
      route_source, actual_cab_registration, planned_cab_registration,
      strptime(trip_date,'%B %d, %Y')::DATE                           AS trip_date,
      date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE      AS month,
      dayname(strptime(trip_date,'%B %d, %Y'))                        AS dow,
      TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)               AS delay_minutes,
      TRY_CAST(replace(traveled_km,',','') AS DOUBLE)                 AS traveled_km,
      TRY_CAST(replace(planned_km,',','')  AS DOUBLE)                 AS planned_km,
      TRY_CAST(actual_escort AS BOOLEAN)                              AS actual_escort,
      TRY_CAST(is_driver_nc AS BOOLEAN)                               AS is_driver_nc,
      TRY_CAST(actual_cab_capacity AS INT)                            AS cab_capacity,
      TRY_CAST(plannedemployee_cnt AS INT)                            AS emp_planned,
      TRY_CAST(actualemployee_cnt AS INT)                             AS emp_actual,
      TRY_CAST(noshow_cnt AS INT)                                     AS noshow,
      TRY_CAST(replace(planned_start_epoch,',','') AS BIGINT)         AS pse,
      TRY_CAST(replace(planned_end_epoch,',','')   AS BIGINT)         AS pee,
      TRY_CAST(replace(actual_start_epoch,',','')  AS BIGINT)         AS ase,
      TRY_CAST(replace(actual_end_epoch,',','')    AS BIGINT)         AS aee,
      CASE WHEN shift_type LIKE '%:%'
           THEN TRY_CAST(split_part(shift_type,':',1) AS INT) END     AS shift_hour,
      CASE WHEN shift_type LIKE '%:%'
           THEN split_part(shift_type,':',2) END                      AS shift_min,
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
      TRY_CAST(replace(trip_cost,',','')     AS DOUBLE)               AS trip_cost,
      TRY_CAST(replace(total_trip_km,',','') AS DOUBLE)               AS km
    FROM read_csv('{RAW}/bill_data.csv', header=true, all_varchar=true,
                  sample_size=-1, ignore_errors=true)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW emp AS SELECT
      TRY_CAST(replace(CAST(trip_id AS VARCHAR),',','') AS BIGINT)    AS trip_id,
      business_unit, office, CAST(stwid AS VARCHAR) AS stwid, gender, emp_role,
      boarding_status, is_no_show, not_boarding_reason, signintype,
      TRY_CAST(trip_date AS DATE)                                     AS trip_date,
      date_trunc('month', TRY_CAST(trip_date AS DATE))::DATE          AS month,
      TRY_CAST(replace(CAST(planned_pickup_epoch AS VARCHAR),',','') AS BIGINT) AS ppe,
      TRY_CAST(replace(CAST(actual_pickup_epoch  AS VARCHAR),',','') AS BIGINT) AS ape,
      TRY_CAST(replace(CAST(planned_drop_epoch   AS VARCHAR),',','') AS BIGINT) AS pde,
      TRY_CAST(replace(CAST(actual_drop_epoch    AS VARCHAR),',','') AS BIGINT) AS ade,
      TRY_CAST(replace(CAST(traveled_km AS VARCHAR),',','') AS DOUBLE) AS traveled_km
    FROM read_csv('{RAW}/emp_Data.csv', header=true, all_varchar=true,
                  sample_size=-1, ignore_errors=true)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW fb AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, trip_type, CAST(stwid AS VARCHAR) AS stwid,
      strptime(creation_time,'%B %d, %Y, %I:%M %p')                   AS created_ts,
      TRY_CAST(route_rating AS INT)   AS route_rating,
      TRY_CAST(driver_rating AS INT)  AS driver_rating,
      TRY_CAST(cab_rating AS INT)     AS cab_rating,
      TRY_CAST(safety_rating AS INT)  AS safety_rating,
      TRY_CAST(marshal_rating AS INT) AS marshal_rating
    FROM read_csv('{RAW}/trip_feedback.csv', header=true, all_varchar=true,
                  sample_size=-1, ignore_errors=true)
    """)
    con.sql(f"""
    CREATE OR REPLACE VIEW alerts AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT)                     AS trip_id,
      business_unit, event_type, severity, state_text, source,
      CAST(stwid AS VARCHAR) AS stwid,
      strptime(start_time,'%B %d, %Y, %I:%M %p')                      AS start_ts,
      strptime(acknowledge_time,'%B %d, %Y, %I:%M %p')                AS ack_ts
    FROM read_csv('{RAW}/alerts_data.csv', header=true, all_varchar=true,
                  sample_size=-1, ignore_errors=true)
    """)


# ---------------------------------------------------------------- base
def s_base():
    show("row counts in every file", """
      SELECT 'trips' t, count(*) n, count(DISTINCT trip_id) d_id FROM trips
      UNION ALL SELECT 'bill',   count(*), count(DISTINCT trip_id) FROM bill
      UNION ALL SELECT 'emp',    count(*), count(DISTINCT trip_id) FROM emp
      UNION ALL SELECT 'fb',     count(*), count(DISTINCT trip_id) FROM fb
      UNION ALL SELECT 'alerts', count(*), count(DISTINCT trip_id) FROM alerts
    """)
    show("trip_id parse failures / date range", """
      SELECT count(*) n, count(*) FILTER (WHERE trip_id IS NULL) bad_id,
             min(trip_date) mn, max(trip_date) mx,
             count(DISTINCT trip_date) n_days
      FROM trips
    """)
    show("planned_km comma-drift row (dataquality MEDIUM-10)", """
      SELECT count(*) n_rows_with_comma FROM read_csv('""" + RAW + """/Ride_data*.csv',
        header=true, union_by_name=true, null_padding=true, ignore_errors=true,
        all_varchar=true, sample_size=-1) WHERE planned_km LIKE '%,%'
    """)


# ---------------------------------------------------------------- ota
def s_ota():
    show("headline OTA + epoch OTA by month (timeliness/dataquality/crosstable)", """
      SELECT month, count(*) n,
             round(100.0*avg(on_time),2)                                      ota_delay_col,
             round(100.0*avg(CASE WHEN aee-pee<=300 THEN 1 ELSE 0 END),2)     ota_end_epoch,
             round(100.0*avg(CASE WHEN ase-pse<=300 THEN 1 ELSE 0 END),2)     ota_start_epoch,
             round(median((aee-pee)/60.0),2)                                  med_end_late_min
      FROM trips GROUP BY 1 ORDER BY 1
    """)
    show("whole-period OTA three ways (dataquality HIGH-2: 94.12 / 44.59 / 74.79)", """
      SELECT round(100.0*avg(on_time),2) ota_delay_col,
             round(100.0*avg(CASE WHEN aee<=pee THEN 1 ELSE 0 END),2) ota_end_epoch_strict,
             round(100.0*avg(CASE WHEN ase<=pse THEN 1 ELSE 0 END),2) ota_start_epoch_strict
      FROM trips
    """)


# ---------------------------------------------------------------- reason
def s_reason():
    show("delay_minutes is reason-gated (dataquality HIGH-2 / crosstable F1)", """
      SELECT delay_reason, count(*) n,
             round(100.0*avg(CASE WHEN delay_minutes=0 THEN 1 ELSE 0 END),3) pct_zero,
             round(avg(delay_minutes),2) avg_delay,
             round(avg((aee-pee)/60.0),2) avg_epoch_end_late
      FROM trips GROUP BY 1 ORDER BY 2 DESC
    """)
    show("contradictions in both directions", """
      SELECT count(*) n,
             count(*) FILTER (WHERE delay_reason='NODELAY' AND delay_minutes>0) nodelay_but_positive,
             count(*) FILTER (WHERE delay_reason<>'NODELAY' AND delay_minutes=0) reason_but_zero
      FROM trips
    """)
    show("# CONFLICT: 'delay_minutes matches epochs on 4.847%' — which definition?", """
      SELECT count(*) n,
             round(100.0*avg(CASE WHEN abs(delay_minutes-(aee-pee)/60.0)<=1
                             THEN 1 ELSE 0 END),3) a_raw_signed_diff,
             round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(aee-pee)/60.0))<=1
                             THEN 1 ELSE 0 END),3) b_clipped_diff,
             round(100.0*avg(CASE WHEN delay_minutes>0 AND
                             abs(delay_minutes-(aee-pee)/60.0)<=1 THEN 1 ELSE 0 END),3) c_nonzero_only,
             round(100.0*avg(CASE WHEN delay_minutes=0 AND aee>pee THEN 1 ELSE 0 END),2) zero_but_late
      FROM trips
    """)
    show("delay_minutes clipping (employees QD4)", """
      SELECT min(delay_minutes) mn, median(delay_minutes) med,
             quantile_cont(delay_minutes,0.9) p90, max(delay_minutes) mx,
             count(*) FILTER (WHERE delay_minutes<0) n_negative, count(*) n
      FROM trips
    """)


# ---------------------------------------------------------------- shift
def s_shift():
    show("OTA by shift-type minute suffix (timeliness F2)", """
      SELECT coalesce(shift_min, shift_type) suffix, count(DISTINCT shift_type) d_shifts,
             count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay, max(delay_minutes) max_delay
      FROM trips GROUP BY 1 ORDER BY 3 DESC
    """)
    show("headline OTA with / without :15 and :16 codes (timeliness F2)", """
      SELECT month,
             count(*) FILTER (WHERE shift_min IN ('15','16')) n_1516,
             round(100.0*avg(CASE WHEN shift_min IN ('15','16') THEN 1 ELSE 0 END),2) pct_1516,
             round(100.0*avg(on_time),2) headline_ota,
             round(100.0*avg(on_time) FILTER (WHERE shift_min NOT IN ('15','16')
                   OR shift_min IS NULL),2) ota_excl_1516
      FROM trips GROUP BY 1 ORDER BY 1
    """)
    show(":15/:16 direction mix — are they 100% LOGOUT?", """
      SELECT shift_min, trip_direction, product_type, count(*) n,
             round(100.0*avg(on_time),2) ota,
             round(avg((aee-pee)/60.0),2) mean_end_dev,
             round(avg((ase-pse)/60.0),2) mean_start_dev
      FROM trips WHERE shift_min IN ('15','16')
      GROUP BY 1,2,3 ORDER BY 4 DESC
    """)


# ---------------------------------------------------------------- spot
def s_spot():
    show("SPOT_2.0 share of delay minutes (timeliness F4)", """
      SELECT product_type, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay, round(sum(delay_minutes),0) delay_min,
             round(100.0*sum(delay_minutes)/(SELECT sum(delay_minutes) FROM trips),2) pct_all_delay
      FROM trips GROUP BY 1 ORDER BY 5 DESC
    """)
    show("delay concentration WITH and WITHOUT SPOT_2.0 (timeliness F4)", """
      WITH r AS (
        SELECT product_type, delay_minutes,
               ntile(100) OVER (ORDER BY delay_minutes DESC) pct_all
        FROM trips WHERE delay_minutes>0),
      r2 AS (
        SELECT delay_minutes, ntile(100) OVER (ORDER BY delay_minutes DESC) pct_ex
        FROM trips WHERE delay_minutes>0 AND product_type<>'SPOT_2.0')
      SELECT 'ALL' pop, count(*) n, round(sum(delay_minutes),0) tot,
             round(100.0*sum(delay_minutes) FILTER (WHERE pct_all=1)/sum(delay_minutes),2) pct_worst1,
             round(100.0*sum(delay_minutes) FILTER (WHERE pct_all<=5)/sum(delay_minutes),2) pct_worst5
      FROM r
      UNION ALL
      SELECT 'EXCL SPOT_2.0', count(*), round(sum(delay_minutes),0),
             round(100.0*sum(delay_minutes) FILTER (WHERE pct_ex=1)/sum(delay_minutes),2),
             round(100.0*sum(delay_minutes) FILTER (WHERE pct_ex<=5)/sum(delay_minutes),2)
      FROM r2
    """)
    show("SLA minutes per trip, all vs ex-SPOT (timeliness F4 sign flip)", """
      SELECT month, round(sum(delay_minutes)/count(*),2) min_per_trip_ALL,
             round(sum(delay_minutes) FILTER (WHERE product_type<>'SPOT_2.0')
                   /count(*) FILTER (WHERE product_type<>'SPOT_2.0'),2) min_per_trip_exSPOT
      FROM trips GROUP BY 1 ORDER BY 1
    """)


# ---------------------------------------------------------------- dow
def s_dow():
    show("day-of-week OTA, weekdays (timeliness F5)", """
      SELECT dow, count(*) n, round(count(*)/count(DISTINCT trip_date),0) trips_per_day,
             round(sum(emp_planned)/count(DISTINCT trip_date),0) seats_per_day,
             round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow NOT IN ('Saturday','Sunday')
      GROUP BY 1 ORDER BY 3 DESC
    """)
    show("Tue vs Fri gap holds per office (n>=500)", """
      SELECT office,
             round(100.0*avg(on_time) FILTER (WHERE dow='Tuesday'),2) tue,
             round(100.0*avg(on_time) FILTER (WHERE dow='Friday'),2) fri,
             count(*) FILTER (WHERE dow='Tuesday') n_tue,
             count(*) FILTER (WHERE dow='Friday') n_fri
      FROM trips GROUP BY 1
      HAVING count(*) FILTER (WHERE dow='Tuesday')>=500
         AND count(*) FILTER (WHERE dow='Friday')>=500
      ORDER BY 2
    """)
    show("Tue/Fri gap by month — is it a June effect?", """
      SELECT month,
             round(100.0*avg(on_time) FILTER (WHERE dow='Tuesday'),2) tue,
             round(100.0*avg(on_time) FILTER (WHERE dow='Friday'),2) fri
      FROM trips GROUP BY 1 ORDER BY 1
    """)


# ---------------------------------------------------------------- load
def s_load():
    show("within-office load quintile vs OTA (timeliness F5)", """
      WITH d AS (SELECT office, trip_date, count(*) n, avg(on_time) ota
                 FROM trips WHERE dow NOT IN ('Saturday','Sunday')
                 GROUP BY 1,2),
      q AS (SELECT *, ntile(5) OVER (PARTITION BY office ORDER BY n) quint FROM d)
      SELECT quint, count(*) office_days, round(avg(n),0) mean_trips_day,
             round(100.0*sum(n*ota)/sum(n),2) ota
      FROM q GROUP BY 1 ORDER BY 1
    """)


# ---------------------------------------------------------------- ids
def s_ids():
    show("trip_id collisions (dataquality HIGH-1 / crosstable F7)", """
      SELECT count(*) n_rows, count(DISTINCT trip_id) d_id,
             count(DISTINCT (trip_id, business_unit)) d_id_bu
      FROM trips
    """)
    show("which BUs collide, and do the pairs ever share a date", """
      WITH c AS (SELECT trip_id FROM trips GROUP BY 1 HAVING count(*)>1)
      SELECT business_unit, count(*) rows_affected
      FROM trips WHERE trip_id IN (SELECT trip_id FROM c) GROUP BY 1 ORDER BY 2 DESC
    """)
    show("join fan-out damage on spend (crosstable F7)", """
      SELECT 'join on trip_id ONLY' j, count(*) n, round(sum(b.trip_cost),2) tot
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id
      UNION ALL
      SELECT 'join on (trip_id,BU)', count(*), round(sum(b.trip_cost),2)
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
    """)


# ---------------------------------------------------------------- bill
def s_bill():
    show("the headline is three numbers (cost)", """
      SELECT round(sum(trip_cost),2) net_billed,
             round(sum(trip_cost) FILTER (WHERE trip_cost>0),2) gross_charges,
             round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credit_notes,
             round(sum(trip_cost) FILTER (WHERE trip_id_raw='OverHead'),2) overhead_lines,
             count(*) FILTER (WHERE trip_id_raw<>'OverHead') trip_rows, count(*) n
      FROM bill
    """)
    show("credits by month + owner (cost F3 / dataquality MEDIUM-6)", """
      SELECT cycle_month, count(*) n, round(sum(trip_cost),2) credit_value
      FROM bill WHERE trip_cost<0 GROUP BY 1 ORDER BY 1
    """)
    show("credit concentration", """
      SELECT business_unit, vendor, contract, count(*) n, round(sum(trip_cost),2) amt,
             round(min(trip_cost),2) most_negative
      FROM bill WHERE trip_cost<0 GROUP BY 1,2,3 ORDER BY 5
    """)
    show("Pinecrest Office nets negative (cost F3)", """
      SELECT office, count(*) n, round(sum(trip_cost),2) net,
             round(sum(trip_cost) FILTER (WHERE trip_cost>0),2) gross,
             round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credits
      FROM bill WHERE office='Pinecrest Office' GROUP BY 1
    """)
    show("zero-km share of rows and spend (dataquality quirk 16)", """
      SELECT count(*) n, count(*) FILTER (WHERE km=0) n_zero_km,
             round(100.0*count(*) FILTER (WHERE km=0)/count(*),2) pct_rows,
             round(100.0*sum(trip_cost) FILTER (WHERE km=0)/sum(trip_cost),2) pct_spend
      FROM bill
    """)
    show("blended vs distance-only CPK (cost / known finding C)", """
      SELECT round(sum(trip_cost)/sum(km) FILTER (WHERE km>0),2) blended_cpk_wrong,
             round(sum(trip_cost) FILTER (WHERE km>0)/sum(km) FILTER (WHERE km>0),2) distance_only_cpk
      FROM bill WHERE trip_cost>0
    """)
    show("zero-km by contract — fixed-rate proof + the mixed one (LOW-14)", """
      SELECT contract, count(*) n, count(*) FILTER (WHERE km=0) zero_km,
             round(100.0*count(*) FILTER (WHERE km=0)/count(*),2) pct_zero
      FROM bill WHERE trip_id_raw<>'OverHead'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 4 DESC
    """)


# ---------------------------------------------------------------- over
def s_over():
    show("OverHead scale (cost F2)", """
      SELECT count(*) n, round(sum(trip_cost),2) spend, round(avg(trip_cost),2) avg_cost,
             round(min(trip_cost),2) mn, round(max(trip_cost),2) mx,
             round(100.0*sum(trip_cost)/(SELECT sum(trip_cost) FROM bill),3) pct_of_total,
             round(avg(km),2) avg_km, count(DISTINCT vendor) d_vendor
      FROM bill WHERE trip_id_raw='OverHead'
    """)
    show("plain CAST crashes on OverHead — demonstrate", """
      SELECT count(*) n_would_crash FROM bill WHERE trip_id_raw='OverHead'
    """)
    show("Amit Mikhailov / DV_Package with and without OverHead (cost F2)", """
      SELECT round(avg(trip_cost) FILTER (WHERE trip_id_raw<>'OverHead'),2) avg_real_trip,
             round(avg(trip_cost) FILTER (WHERE trip_id_raw='OverHead'),2) avg_overhead_line,
             round(avg(trip_cost),2) avg_if_not_separated,
             count(*) n, count(*) FILTER (WHERE trip_id_raw='OverHead') n_overhead
      FROM bill WHERE vendor='Amit Mikhailov Travel' AND contract='DV_Package'
    """)
    show("Maple Grove Office is 100% OverHead", """
      SELECT office, count(*) n, count(*) FILTER (WHERE trip_id_raw='OverHead') n_oh,
             round(sum(trip_cost),2) net
      FROM bill GROUP BY 1 HAVING count(*) FILTER (WHERE trip_id_raw='OverHead')>0 ORDER BY 2
    """)


# ---------------------------------------------------------------- slab
def s_slab():
    show("slab_name string sentinels + label variants (dataquality HIGH-5)", """
      SELECT slab_name, count(*) n, round(sum(trip_cost),0) amt
      FROM bill GROUP BY 1 ORDER BY 2 DESC LIMIT 32
    """)
    show("raw vs normalised slab labels", """
      WITH s AS (SELECT CASE WHEN slab_name IN ('null','NA','0') THEN 'UNLABELLED'
                   ELSE upper(regexp_replace(regexp_replace(slab_name,'^[Ss]lab[- ]?',''),'[ _-]','','g')) END nrm,
                   slab_name, trip_cost FROM bill)
      SELECT count(DISTINCT slab_name) raw_labels, count(DISTINCT nrm) normalised_labels FROM s
    """)
    show("money sitting in split buckets", """
      WITH s AS (SELECT CASE WHEN slab_name IN ('null','NA','0') THEN 'UNLABELLED'
                   ELSE upper(regexp_replace(regexp_replace(slab_name,'^[Ss]lab[- ]?',''),'[ _-]','','g')) END nrm,
                   slab_name, trip_cost FROM bill),
      m AS (SELECT nrm, count(DISTINCT slab_name) v, count(*) n, sum(trip_cost) amt
            FROM s GROUP BY 1)
      SELECT round(sum(amt) FILTER (WHERE v>1),0) money_in_split_buckets,
             round(100.0*sum(amt) FILTER (WHERE v>1)/sum(amt),2) pct_of_spend,
             sum(n) FILTER (WHERE v>1) n_rows
      FROM m
    """)
    show("707 trips billed zero because slab missing (cost F5)", """
      WITH c AS (SELECT contract,
                   count(*) n,
                   count(*) FILTER (WHERE slab_name IN ('null','NA')) n_null
                 FROM bill WHERE trip_id_raw<>'OverHead' GROUP BY 1),
      pat AS (SELECT contract, CASE WHEN n_null=n THEN 'NEVER has slab'
                                    WHEN n_null=0 THEN 'ALWAYS has slab'
                                    ELSE 'SOMETIMES missing' END p FROM c)
      SELECT p, count(DISTINCT b.contract) n_contracts, count(*) n_trips,
             round(sum(b.trip_cost),2) spend,
             round(sum(b.trip_cost) FILTER (WHERE b.slab_name IN ('null','NA')),2) null_slab_spend
      FROM bill b JOIN pat ON pat.contract=b.contract
      WHERE b.trip_id_raw<>'OverHead' GROUP BY 1 ORDER BY 3 DESC
    """)
    show("genuinely-missing slab -> zero invoice", """
      WITH c AS (SELECT contract, count(*) n, count(*) FILTER (WHERE slab_name IN ('null','NA')) n_null
                 FROM bill WHERE trip_id_raw<>'OverHead' GROUP BY 1),
      sometimes AS (SELECT contract FROM c WHERE n_null>0 AND n_null<n)
      SELECT count(*) genuinely_missing_slab_rows,
             count(*) FILTER (WHERE trip_cost=0) of_which_billed_zero
      FROM bill WHERE contract IN (SELECT contract FROM sometimes)
        AND slab_name IN ('null','NA') AND trip_id_raw<>'OverHead'
    """)
    show("zero-cost rows overall", """
      SELECT count(*) zero_cost_rows,
             count(*) FILTER (WHERE slab_name IN ('null','NA')) with_null_slab
      FROM bill WHERE trip_cost=0
    """)


# ---------------------------------------------------------------- fb / fbcov  # CONFLICT
def s_fbcov():
    print("\n### CONFLICT ADJUDICATION: feedback coverage for vanta-Aus")
    print("### feedback.md says 3.85%  |  dataquality.md says 12.43%")
    show("A. coverage joining on trip_id ONLY (the naive join)", """
      SELECT t.business_unit, count(*) trips,
             round(100.0*count(*) FILTER (WHERE f.trip_id IS NOT NULL)/count(*),2) coverage_pct
      FROM trips t
      LEFT JOIN (SELECT DISTINCT trip_id FROM fb) f ON t.trip_id=f.trip_id
      GROUP BY 1 ORDER BY 3
    """)
    show("B. coverage joining on (trip_id, business_unit) — the correct key", """
      SELECT t.business_unit, count(*) trips,
             round(100.0*count(*) FILTER (WHERE f.trip_id IS NOT NULL)/count(*),2) coverage_pct
      FROM trips t
      LEFT JOIN (SELECT DISTINCT trip_id, business_unit FROM fb) f
             ON t.trip_id=f.trip_id AND t.business_unit=f.business_unit
      GROUP BY 1 ORDER BY 3
    """)
    show("C. how many vanta-Aus trips gain a PHANTOM feedback match from the naive join", """
      SELECT count(*) phantom_matched_trips
      FROM trips t
      JOIN (SELECT DISTINCT trip_id, business_unit FROM fb) f ON t.trip_id=f.trip_id
      WHERE t.business_unit='vanta-Aus' AND f.business_unit<>'vanta-Aus'
        AND NOT EXISTS (SELECT 1 FROM fb f2 WHERE f2.trip_id=t.trip_id
                          AND f2.business_unit='vanta-Aus')
    """)
    show("D. trips with ANY feedback, both keys (dataquality: 311,073 uncovered = 50.536%)", """
      SELECT
        (SELECT count(*) FROM trips t WHERE NOT EXISTS
           (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id)) uncovered_naive,
        (SELECT count(*) FROM trips t WHERE NOT EXISTS
           (SELECT 1 FROM fb f WHERE f.trip_id=t.trip_id
              AND f.business_unit=t.business_unit)) uncovered_correct,
        (SELECT count(*) FROM trips) n_trips
    """)


def s_fb():
    show("feedback rating distributions (feedback F1 / dataquality HIGH-4)", """
      SELECT 'route' dim, count(*) FILTER (WHERE route_rating=0) n_zero,
             round(avg(route_rating),3) incl_zero,
             round(avg(route_rating) FILTER (WHERE route_rating>0),3) excl_zero FROM fb
      UNION ALL SELECT 'driver', count(*) FILTER (WHERE driver_rating=0),
             round(avg(driver_rating),3), round(avg(driver_rating) FILTER (WHERE driver_rating>0),3) FROM fb
      UNION ALL SELECT 'cab', count(*) FILTER (WHERE cab_rating=0),
             round(avg(cab_rating),3), round(avg(cab_rating) FILTER (WHERE cab_rating>0),3) FROM fb
      UNION ALL SELECT 'safety', count(*) FILTER (WHERE safety_rating=0),
             round(avg(safety_rating),3), round(avg(safety_rating) FILTER (WHERE safety_rating>0),3) FROM fb
      UNION ALL SELECT 'marshal', count(*) FILTER (WHERE marshal_rating=0),
             round(avg(marshal_rating),3), round(avg(marshal_rating) FILTER (WHERE marshal_rating>0),3) FROM fb
    """)
    show("marshal=0 IS 'no marshal': cross-check vs actual_escort (feedback F1)", """
      SELECT t.actual_escort, count(*) n,
             count(*) FILTER (WHERE f.marshal_rating>0) marshal_rated,
             round(100.0*count(*) FILTER (WHERE f.marshal_rating>0)/count(*),2) pct_rated
      FROM fb f JOIN trips t ON f.trip_id=t.trip_id AND f.business_unit=t.business_unit
      GROUP BY 1 ORDER BY 2 DESC
    """)
    show("detractor rate: feedback-weighted vs trip-weighted (feedback F2)", """
      WITH bu AS (
        SELECT f.business_unit, count(*) fb_rows,
               100.0*avg(CASE WHEN f.driver_rating<=2 THEN 1 ELSE 0 END) det
        FROM fb f GROUP BY 1),
      tr AS (SELECT business_unit, count(*) trips FROM trips GROUP BY 1)
      SELECT round(sum(bu.fb_rows*bu.det)/sum(bu.fb_rows),4) det_feedback_weighted,
             round(sum(tr.trips*bu.det)/sum(tr.trips),4)   det_trip_weighted
      FROM bu JOIN tr USING (business_unit)
    """)
    show("response rate vs detractor rate by BU (feedback F2)", """
      WITH cov AS (
        SELECT t.business_unit, count(*) trips,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb f
                 WHERE f.trip_id=t.trip_id AND f.business_unit=t.business_unit)) rated
        FROM trips t GROUP BY 1)
      SELECT c.business_unit, c.trips, c.rated,
             round(100.0*c.rated/c.trips,2) response_rate_pct,
             (SELECT count(*) FROM fb f WHERE f.business_unit=c.business_unit) fb_rows,
             round((SELECT avg(driver_rating) FROM fb f WHERE f.business_unit=c.business_unit),4) driver,
             round((SELECT 100.0*avg(CASE WHEN driver_rating<=2 THEN 1 ELSE 0 END)
                    FROM fb f WHERE f.business_unit=c.business_unit),3) driver_det_pct
      FROM cov c ORDER BY 4 DESC
    """)
    show("mean is dead / detractor moves (feedback F5)", """
      SELECT t.month, count(*) n, round(avg(f.route_rating),4) route_mean,
             round(100.0*avg(CASE WHEN f.route_rating=5 THEN 1 ELSE 0 END),3) pct_5star,
             round(100.0*avg(CASE WHEN f.route_rating<=2 THEN 1 ELSE 0 END),3) det_pct
      FROM fb f JOIN trips t ON f.trip_id=t.trip_id AND f.business_unit=t.business_unit
      GROUP BY 1 ORDER BY 1
    """)
    show("rating dimension inter-correlation (feedback F5: halo)", """
      SELECT round(corr(route_rating,driver_rating),4) route_driver,
             round(corr(driver_rating,cab_rating),4)   driver_cab,
             round(corr(driver_rating,safety_rating),4) driver_safety,
             round(corr(cab_rating,safety_rating),4)   cab_safety
      FROM fb
    """)


# ---------------------------------------------------------------- emp
def s_emp():
    show("no-show label vs boarding_status (employees F3 / dataquality MEDIUM-9)", """
      SELECT boarding_status, is_no_show, not_boarding_reason, count(*) n,
             round(100.0*count(*)/(SELECT count(*) FROM emp),3) pct
      FROM emp GROUP BY 1,2,3 ORDER BY 4 DESC
    """)
    show("the two rates", """
      SELECT round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1 ELSE 0 END),3) by_status,
             round(100.0*avg(CASE WHEN is_no_show='true' OR is_no_show='True' THEN 1 ELSE 0 END),3) by_flag
      FROM emp
    """)
    show("taxonomy-neutral not-boarded rate by BU (employees F3 headline)", """
      SELECT business_unit, count(*) n,
             round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1 ELSE 0 END),2) not_boarded_pct,
             round(100.0*avg(CASE WHEN lower(is_no_show)='true' THEN 1 ELSE 0 END),2) noshow_label,
             round(100.0*avg(CASE WHEN not_boarding_reason='TRIP_CANCELLED_FROM_DASHBOARD'
                             THEN 1 ELSE 0 END),2) cancel_label
      FROM emp GROUP BY 1 ORDER BY 3 DESC
    """)
    show("not-boarded rate by month (the real improvement)", """
      SELECT month, count(*) n,
             round(100.0*avg(CASE WHEN boarding_status='Not Boarded' THEN 1 ELSE 0 END),2) not_boarded_pct
      FROM emp GROUP BY 1 ORDER BY 1
    """)
    show("structural equivalences (employees)", """
      SELECT count(*) FILTER (WHERE boarding_status='Not Boarded') n_not_boarded,
             count(*) FILTER (WHERE boarding_status='Not Boarded' AND ape IS NULL) nb_and_null_pickup,
             count(*) FILTER (WHERE boarding_status='Boarded' AND ape IS NULL) boarded_but_null_pickup,
             count(*) FILTER (WHERE signintype IN ('Adhoc','Guest')) n_adhoc_guest,
             count(*) FILTER (WHERE signintype IN ('Adhoc','Guest') AND ppe IS NULL) ag_null_planned
      FROM emp
    """)
    show("Adhoc legs are mostly escorts (employees)", """
      SELECT signintype, count(*) n, count(*) FILTER (WHERE emp_role='escort') n_escort,
             round(100.0*count(*) FILTER (WHERE emp_role='escort')/count(*),2) pct_escort
      FROM emp WHERE signintype IN ('Adhoc','Guest') GROUP BY 1
    """)
    show("stwid=0 placeholder", """
      SELECT count(*) n, count(DISTINCT trip_id) d_trips,
             count(*) FILTER (WHERE emp_role IS NULL) role_null
      FROM emp WHERE stwid IN ('0','0.0')
    """)
    show("negative km (dictionary warns -6.63)", """
      SELECT count(*) FILTER (WHERE traveled_km<0) neg_traveled,
             round(min(traveled_km),3) min_traveled,
             count(*) FILTER (WHERE traveled_km=0) zero_traveled,
             count(*) n FROM emp
    """)
    show("escort/projectmgr occupy seats (dataquality LOW-13)", """
      SELECT emp_role, count(*) n, round(100.0*count(*)/(SELECT count(*) FROM emp),3) pct
      FROM emp GROUP BY 1 ORDER BY 2 DESC LIMIT 8
    """)


# ---------------------------------------------------------------- rider
def s_rider():
    con.sql("""
      CREATE OR REPLACE VIEW legs AS SELECT *,
        (ape-ppe)/60.0 AS pickup_late_min, (ade-pde)/60.0 AS drop_late_min
      FROM emp WHERE ape IS NOT NULL AND ppe IS NOT NULL
    """)
    show("rider pickup OTA vs trip OTA, same legs (employees F2 / crosstable F1)", """
      SELECT l.month, count(*) legs,
             round(100.0*avg(CASE WHEN l.pickup_late_min<=5 THEN 1 ELSE 0 END),2) rider_pickup_ota,
             round(100.0*avg(t.on_time),2) trip_ota_over_same_legs
      FROM legs l JOIN trips t ON l.trip_id=t.trip_id AND l.business_unit=t.business_unit
      GROUP BY 1 ORDER BY 1
    """)
    show("in-cab planned vs actual by direction (employees F1)", """
      SELECT t.trip_direction, l.month, count(*) n,
             round(avg((l.pde-l.ppe)/60.0),2) planned_min,
             round(avg((l.ade-l.ape)/60.0),2) actual_min,
             round(avg((l.ade-l.ape)/60.0)-avg((l.pde-l.ppe)/60.0),2) overrun
      FROM legs l JOIN trips t ON l.trip_id=t.trip_id AND l.business_unit=t.business_unit
      WHERE l.ade IS NOT NULL AND l.pde IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("implied planned vs actual speed by direction (employees F1 mechanism)", """
      SELECT t.trip_direction, count(*) n,
             round(avg(l.traveled_km),2) avg_km,
             round(avg(l.traveled_km)/(avg((l.pde-l.ppe)/60.0)/60.0),1) planned_kmh,
             round(avg(l.traveled_km)/(avg((l.ade-l.ape)/60.0)/60.0),1) actual_kmh
      FROM legs l JOIN trips t ON l.trip_id=t.trip_id AND l.business_unit=t.business_unit
      WHERE l.ade IS NOT NULL AND l.pde IS NOT NULL AND l.traveled_km>0
      GROUP BY 1
    """)
    show("LOGOUT drop lateness >15 min (employees F2)", """
      SELECT t.trip_direction, l.month, count(*) n,
             round(100.0*avg(CASE WHEN l.drop_late_min<=5 THEN 1 ELSE 0 END),2) drop_le5,
             round(100.0*avg(CASE WHEN l.drop_late_min>15 THEN 1 ELSE 0 END),2) drop_gt15
      FROM legs l JOIN trips t ON l.trip_id=t.trip_id AND l.business_unit=t.business_unit
      WHERE l.ade IS NOT NULL AND l.pde IS NOT NULL
      GROUP BY 1,2 ORDER BY 1,2
    """)
    show("rider-pain concentration (employees F4)", """
      WITH r AS (SELECT stwid, count(*) legs,
                        count(*) FILTER (WHERE pickup_late_min>15) late15
                 FROM legs WHERE stwid NOT IN ('0','0.0') GROUP BY 1),
      d AS (SELECT *, ntile(20) OVER (ORDER BY late15 DESC) v20,
                      ntile(10) OVER (ORDER BY late15 DESC) v10 FROM r)
      SELECT count(*) riders, sum(late15) total_late15,
             round(100.0*sum(late15) FILTER (WHERE v20=1)/sum(late15),2) pct_from_top5pct,
             round(100.0*sum(late15) FILTER (WHERE v10=1)/sum(late15),2) pct_from_top_decile,
             count(*) FILTER (WHERE v20=1) n_top5pct_riders
      FROM d
    """)
    show("30% of regular riders never late>15 (employees F4)", """
      WITH r AS (SELECT stwid, count(*) legs, count(*) FILTER (WHERE pickup_late_min>15) late15
                 FROM legs WHERE stwid NOT IN ('0','0.0') GROUP BY 1 HAVING count(*)>=20)
      SELECT count(*) riders_ge20_legs, count(*) FILTER (WHERE late15=0) never_late,
             round(100.0*count(*) FILTER (WHERE late15=0)/count(*),2) pct_never_late
      FROM r
    """)


# ---------------------------------------------------------------- esc  # CONFLICT
def s_esc():
    print("\n### CONFLICT ADJUDICATION: unescorted female-last-drop night trips")
    print("### safety.md   : orbit-Slc 1,891 of 8,123 = 23.28% (LOGOUT CAB, shift_hour 19-05)")
    print("### employees.md: 254 orbit-Slc breaches of 270 platform-wide (night LOGOUT)")
    con.sql("""
      CREATE OR REPLACE VIEW lastdrop AS
      SELECT trip_id, business_unit,
             arg_max(gender, ade) AS last_drop_gender,
             max(ade) AS last_ade
      FROM emp WHERE ade IS NOT NULL AND boarding_status='Boarded'
      GROUP BY 1,2
    """)
    show("A. safety.md definition: LOGOUT CAB, shift_hour>=19 OR <6, female last drop", """
      SELECT t.business_unit, count(*) last_drop_female_night,
             count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*avg(CASE WHEN NOT t.actual_escort THEN 1 ELSE 0 END),2) pct_no_escort
      FROM trips t JOIN lastdrop l ON t.trip_id=l.trip_id AND t.business_unit=l.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB'
        AND (t.shift_hour>=19 OR t.shift_hour<6) AND l.last_drop_gender='FEMALE'
      GROUP BY 1 ORDER BY 4 DESC
    """)
    show("B. employees.md definition: ALL night LOGOUT trips, split by escort", """
      SELECT t.actual_escort, count(*) trips,
             count(*) FILTER (WHERE l.last_drop_gender='FEMALE') last_drop_female,
             round(100.0*avg(CASE WHEN l.last_drop_gender='FEMALE' THEN 1 ELSE 0 END),2) pct
      FROM trips t JOIN lastdrop l ON t.trip_id=l.trip_id AND t.business_unit=l.business_unit
      WHERE t.trip_direction='LOGOUT' AND (t.shift_hour>=19 OR t.shift_hour<6)
      GROUP BY 1
    """)
    show("C. THE DIFFERENCE: does 'last drop' include the escort leg?", """
      SELECT t.business_unit, count(*) n_female_last_drop_night_logout_cab,
             count(*) FILTER (WHERE NOT t.actual_escort) no_escort
      FROM trips t JOIN (
        SELECT trip_id, business_unit, arg_max(gender, ade) last_drop_gender
        FROM emp WHERE ade IS NOT NULL AND boarding_status='Boarded'
          AND (emp_role IS NULL OR emp_role<>'escort')
        GROUP BY 1,2) l ON t.trip_id=l.trip_id AND t.business_unit=l.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB'
        AND (t.shift_hour>=19 OR t.shift_hour<6) AND l.last_drop_gender='FEMALE'
      GROUP BY 1 ORDER BY 3 DESC
    """)
    show("D. escorted trips: is the escort the last leg dropped?", """
      SELECT count(*) escorted_night_logout,
             count(*) FILTER (WHERE incl_escort='FEMALE') female_last_incl_escort,
             count(*) FILTER (WHERE excl_escort='FEMALE') female_last_excl_escort
      FROM (
        SELECT t.trip_id,
          arg_max(e.gender, e.ade) FILTER (WHERE e.boarding_status='Boarded') incl_escort,
          arg_max(e.gender, e.ade) FILTER (WHERE e.boarding_status='Boarded'
            AND (e.emp_role IS NULL OR e.emp_role<>'escort')) excl_escort
        FROM trips t JOIN emp e ON t.trip_id=e.trip_id AND t.business_unit=e.business_unit
        WHERE t.trip_direction='LOGOUT' AND (t.shift_hour>=19 OR t.shift_hour<6)
          AND t.actual_escort AND e.ade IS NOT NULL
        GROUP BY 1) x
    """)
    show("E. monthly trend of UNESCORTED night LOGOUT w/ female last drop (employees F5)", """
      SELECT t.month, count(*) unescorted_night_logout,
             count(*) FILTER (WHERE l.last_drop_gender='FEMALE') last_drop_female,
             round(100.0*avg(CASE WHEN l.last_drop_gender='FEMALE' THEN 1 ELSE 0 END),2) pct
      FROM trips t JOIN lastdrop l ON t.trip_id=l.trip_id AND t.business_unit=l.business_unit
      WHERE t.trip_direction='LOGOUT' AND (t.shift_hour>=19 OR t.shift_hour<6)
        AND NOT t.actual_escort
      GROUP BY 1 ORDER BY 1
    """)


def s_esc2():
    show("escort policy cliff at 19:00 by shift_hour (safety HIGH 3)", """
      SELECT t.shift_hour, count(*) female_last_drop,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct_escort,
             count(*) FILTER (WHERE NOT t.actual_escort) n_unescorted,
             round(median((t.aee-t.ase)/60.0),1) med_dur_min
      FROM trips t JOIN (
        SELECT trip_id, business_unit, arg_max(gender, ade) last_drop_gender
        FROM emp WHERE ade IS NOT NULL GROUP BY 1,2) l
        ON t.trip_id=l.trip_id AND t.business_unit=l.business_unit
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB'
        AND l.last_drop_gender='FEMALE' AND t.shift_hour BETWEEN 16 AND 21
      GROUP BY 1 ORDER BY 1
    """)
    show("actual_escort vs emp_role='escort' agreement (safety ground rule)", """
      SELECT t.actual_escort, e.has_escort_row, count(*) n
      FROM trips t LEFT JOIN (
        SELECT DISTINCT trip_id, business_unit, TRUE has_escort_row
        FROM emp WHERE emp_role='escort') e
        ON t.trip_id=e.trip_id AND t.business_unit=e.business_unit
      GROUP BY 1,2 ORDER BY 3 DESC
    """)
    show("escort composition rule (employees F5)", """
      WITH comp AS (
        SELECT t.trip_id, t.business_unit, t.actual_escort,
               (t.shift_hour>=19 OR t.shift_hour<6) night,
               count(*) FILTER (WHERE e.gender='FEMALE') f,
               count(*) FILTER (WHERE e.gender='MALE') m
        FROM trips t JOIN emp e ON t.trip_id=e.trip_id AND t.business_unit=e.business_unit
        WHERE e.boarding_status='Boarded' AND (e.emp_role IS NULL OR e.emp_role<>'escort')
        GROUP BY 1,2,3,4)
      SELECT CASE WHEN f>0 AND m=0 THEN 'female-only' WHEN m>0 AND f=0 THEN 'male-only'
                  WHEN f>0 AND m>0 THEN 'mixed' ELSE 'none' END rider_comp,
             night, count(*) trips, count(*) FILTER (WHERE actual_escort) escorted,
             round(100.0*avg(CASE WHEN actual_escort THEN 1 ELSE 0 END),2) escort_pct
      FROM comp GROUP BY 1,2 ORDER BY 3 DESC
    """)


# ---------------------------------------------------------------- vendor
def s_vendor():
    show("BUS-ORRNEW-TT: one office, one contract, no slab (cost F1)", """
      SELECT count(*) n, count(*) FILTER (WHERE slab_name NOT IN ('null','NA')) n_with_slab,
             count(DISTINCT office) offices, count(DISTINCT vendor) vendors,
             round(avg(km),2) avg_km
      FROM bill WHERE contract='BUS-ORRNEW-TT' AND trip_id_raw<>'OverHead'
    """)
    show("BUS-ORRNEW-TT cost by office x vendor, n>=500 (cost F1 DECISIVE)", """
      SELECT office, vendor, count(*) n, round(avg(trip_cost),2) avg_cost,
             round(median(trip_cost),2) med_cost, round(sum(trip_cost),2) spend,
             round(avg(km),2) avg_km
      FROM bill WHERE contract='BUS-ORRNEW-TT' AND trip_id_raw<>'OverHead'
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 4 DESC
    """)
    show("Meera Lebedev Travel — the one bad vendor (crosstable F6)", """
      SELECT t.month, count(*) n, round(100.0*avg(t.on_time),2) ota,
             round(avg(t.emp_actual),2) riders, round(avg(t.cab_capacity),2) cap
      FROM trips t WHERE t.vendor_id='Meera Lebedev Travel' GROUP BY 1 ORDER BY 1
    """)
    show("Meera Lebedev vs its own office+month peers (crosstable F6)", """
      WITH peer AS (SELECT office, month, avg(on_time) p_ota FROM trips GROUP BY 1,2)
      SELECT t.vendor_id, count(*) n, round(100.0*avg(t.on_time),2) ota_vendor,
             round(100.0*avg(p.p_ota),2) peer_ota, round(100.0*(avg(t.on_time)-avg(p.p_ota)),2) gap
      FROM trips t JOIN peer p ON t.office=p.office AND t.month=p.month
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY 5 LIMIT 6
    """)
    show("vendor alert rate + feedback coverage confound (crosstable F6)", """
      WITH a AS (SELECT trip_id, business_unit, count(*) n_al FROM alerts GROUP BY 1,2)
      SELECT t.vendor_id, count(*) n_trips,
             round(1000.0*sum(coalesce(a.n_al,0))/count(*),2) alerts_per_1000,
             round(100.0*count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb f
               WHERE f.trip_id=t.trip_id AND f.business_unit=t.business_unit))/count(*),2) fb_cov_pct
      FROM trips t LEFT JOIN a ON t.trip_id=a.trip_id AND t.business_unit=a.business_unit
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY 3 DESC LIMIT 6
    """)


# ---------------------------------------------------------------- alerts
def s_alerts():
    show("severity distribution incl. the literal 'False' (safety MEDIUM 6)", """
      SELECT severity, count(*) n, round(100.0*count(*)/(SELECT count(*) FROM alerts),3) pct
      FROM alerts GROUP BY 1 ORDER BY 2 DESC
    """)
    show("24h auto-close cluster (safety ground rule)", """
      SELECT CASE WHEN ack_ts IS NULL THEN 'never'
                  WHEN date_diff('minute',start_ts,ack_ts)<=5 THEN 'a <=5m'
                  WHEN date_diff('minute',start_ts,ack_ts)<=15 THEN 'b 6-15m'
                  WHEN date_diff('minute',start_ts,ack_ts)<=60 THEN 'c 16-60m'
                  WHEN date_diff('minute',start_ts,ack_ts)<=600 THEN 'd 1-10h'
                  WHEN date_diff('minute',start_ts,ack_ts)<1434 THEN 'e 10-23.9h'
                  WHEN date_diff('minute',start_ts,ack_ts)<=1452 THEN 'f 23.9-24.2h AUTOCLOSE'
                  ELSE 'g >24.2h' END bucket,
             count(*) n, round(100.0*count(*)/(SELECT count(*) FROM alerts),2) pct
      FROM alerts GROUP BY 1 ORDER BY 1
    """)
    show("auto-close by BU (safety HIGH 1)", """
      SELECT business_unit, count(*) n_alerts,
             count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts) BETWEEN 1434 AND 1452) n_auto,
             round(100.0*count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts)
                   BETWEEN 1434 AND 1452)/count(*),2) pct_auto
      FROM alerts GROUP BY 1 ORDER BY 4 DESC
    """)
    show("catalyst-Sac geofence 100% auto-closed vs other BUs (safety HIGH 1)", """
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts) BETWEEN 1434 AND 1452) auto,
             round(100.0*count(*) FILTER (WHERE date_diff('minute',start_ts,ack_ts)
                   BETWEEN 1434 AND 1452)/count(*),2) pct,
             round(median(date_diff('minute',start_ts,ack_ts)),1) med_min
      FROM alerts WHERE event_type='EMPLOYEE_GEOFENCE_VIOLATION' GROUP BY 1 ORDER BY 4 DESC
    """)
    show("SIGN_OFF detector dies on 2026-05-18 (safety HIGH 2 / dataquality MEDIUM-7)", """
      SELECT start_ts::DATE d, count(*) n
      FROM alerts WHERE event_type='EMPLOYEE_SIGN_OFF_TIME_VIOLATION'
        AND start_ts::DATE BETWEEN '2026-05-12' AND '2026-05-22'
      GROUP BY 1 ORDER BY 1
    """)
    show("do other detectors survive the 05-18 boundary? (dataquality MEDIUM-7)", """
      SELECT event_type,
             count(*) FILTER (WHERE start_ts::DATE < '2026-05-18') n_before,
             count(*) FILTER (WHERE start_ts::DATE >= '2026-05-18') n_after, count(*) n
      FROM alerts GROUP BY 1 ORDER BY 4 DESC
    """)
    show("Sev-1/Sev-2 are a catalyst-Sac config artifact (safety MEDIUM 6)", """
      SELECT business_unit, count(*) n,
             count(*) FILTER (WHERE severity='Sev-1') sev1,
             count(*) FILTER (WHERE severity='Sev-2') sev2,
             count(*) FILTER (WHERE severity='Sev-3') sev3,
             count(*) FILTER (WHERE severity='NA') na,
             count(*) FILTER (WHERE severity='False') falsev
      FROM alerts GROUP BY 1 ORDER BY 2 DESC
    """)
    show("alerts stwid=0 is a clean vehicle/employee split (dataquality LOW-12)", """
      SELECT event_type, count(*) n,
             round(100.0*avg(CASE WHEN stwid IN ('0','0.0') THEN 1 ELSE 0 END),2) pct_stwid0
      FROM alerts GROUP BY 1 ORDER BY 2 DESC
    """)
    show("WTA fires on last-drop-female, not solo-female (safety HIGH 4)", """
      WITH wta AS (SELECT DISTINCT trip_id, business_unit FROM alerts
                   WHERE event_type='WOMAN_TRAVELLING_ALONE'),
      ld AS (SELECT trip_id, business_unit, arg_max(gender, ade) g,
                    count(*) FILTER (WHERE gender='FEMALE') f, count(*) c
             FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT count(*) wta_trips,
             round(100.0*avg(CASE WHEN ld.f=1 AND ld.c=1 THEN 1 ELSE 0 END),2) pct_solo_female,
             round(100.0*avg(CASE WHEN ld.g='FEMALE' THEN 1 ELSE 0 END),2) pct_last_drop_female
      FROM wta JOIN ld USING (trip_id, business_unit)
    """)
    show("...vs the base rate on all CAB trips", """
      WITH ld AS (SELECT trip_id, business_unit, arg_max(gender, ade) g,
                    count(*) FILTER (WHERE gender='FEMALE') f, count(*) c
                  FROM emp WHERE ade IS NOT NULL GROUP BY 1,2)
      SELECT count(*) cab_trips,
             round(100.0*avg(CASE WHEN ld.f=1 AND ld.c=1 THEN 1 ELSE 0 END),2) base_solo_female,
             round(100.0*avg(CASE WHEN ld.g='FEMALE' THEN 1 ELSE 0 END),2) base_last_drop_female
      FROM trips t JOIN ld ON t.trip_id=ld.trip_id AND t.business_unit=ld.business_unit
      WHERE t.product_type='CAB'
    """)
    show("WTA detector coverage matrix per 1k trips (safety HIGH 4)", """
      WITH a AS (SELECT business_unit, count(*) n FROM alerts
                 WHERE event_type='WOMAN_TRAVELLING_ALONE' GROUP BY 1),
      t AS (SELECT business_unit, count(*) n FROM trips GROUP BY 1)
      SELECT t.business_unit, t.n trips, coalesce(a.n,0) wta_alerts,
             round(1000.0*coalesce(a.n,0)/t.n,2) per_1k
      FROM t LEFT JOIN a USING (business_unit) ORDER BY 4 DESC
    """)


# ---------------------------------------------------------------- misc
def s_misc():
    show("is_driver_nc / is_cab_nc — dead columns? (timeliness DQ note vs safety MEDIUM 7)", """
      SELECT count(*) n,
             count(*) FILTER (WHERE is_driver_nc) n_driver_nc,
             count(*) FILTER (WHERE is_cab_nc) n_cab_nc,
             count(*) FILTER (WHERE is_driver_nc IS NULL) n_null
      FROM trips
    """)
    show("driver-NC concentration by BU x vendor (safety MEDIUM 7)", """
      SELECT business_unit, vendor_id, count(*) n,
             round(100.0*avg(CASE WHEN is_driver_nc THEN 1 ELSE 0 END),3) drv_nc_pct
      FROM trips GROUP BY 1,2 HAVING count(*)>=5000 ORDER BY 4 DESC LIMIT 6
    """)
    show("route_source SHUTTLE_SERVICE July jump (timeliness DQ note 2)", """
      SELECT route_source, count(*) FILTER (WHERE month='2026-05-01') may,
             count(*) FILTER (WHERE month='2026-06-01') jun,
             count(*) FILTER (WHERE month='2026-07-01') jul
      FROM trips GROUP BY 1 ORDER BY 4 DESC
    """)
    show("emp_planned = emp_actual + noshow? (timeliness DQ note 3)", """
      SELECT count(*) n,
             round(100.0*avg(CASE WHEN emp_planned=emp_actual+noshow THEN 1 ELSE 0 END),2) pct_holds,
             round(100.0*avg(CASE WHEN emp_actual+noshow>emp_planned THEN 1 ELSE 0 END),2) pct_over,
             round(100.0*avg(CASE WHEN emp_actual+noshow<emp_planned THEN 1 ELSE 0 END),2) pct_under
      FROM trips
    """)
    show("no ghost trips (crosstable negative check)", """
      SELECT min(emp_actual) mn, max(emp_actual) mx,
             count(*) FILTER (WHERE emp_actual IS NULL) n_null,
             count(*) FILTER (WHERE emp_actual=0) n_zero FROM trips
    """)
    show("no-show seat value (crosstable F5)", """
      SELECT t.month, count(*) n, sum(t.noshow) seats_noshow,
             round(sum(b.trip_cost),0) spend,
             round(sum(b.trip_cost * t.noshow / nullif(t.emp_planned,0)),0) noshow_seat_value,
             round(100.0*sum(b.trip_cost * t.noshow / nullif(t.emp_planned,0))/sum(b.trip_cost),2) pct
      FROM trips t JOIN bill b ON t.trip_id=b.trip_id AND t.business_unit=b.business_unit
      WHERE b.trip_cost>0 GROUP BY 1 ORDER BY 1
    """)
    show("planned seats never used (crosstable F5)", """
      SELECT sum(emp_planned) planned_seats, sum(noshow) noshow_seats,
             round(100.0*sum(noshow)/sum(emp_planned),2) pct,
             count(*) FILTER (WHERE noshow>0) trips_with_noshow,
             round(100.0*avg(CASE WHEN noshow>0 THEN 1 ELSE 0 END),2) pct_trips
      FROM trips
    """)
    show("2026-05-28 pinnacle outage present in all 4 files (dataquality MEDIUM-8)", """
      SELECT d, ride, emp_legs, fb_rows, alert_rows FROM (
        SELECT trip_date d, count(*) ride FROM trips WHERE business_unit='pinnacle-Slc'
          AND trip_date BETWEEN '2026-05-26' AND '2026-05-30' GROUP BY 1) r
      JOIN (SELECT trip_date d, count(*) emp_legs FROM emp WHERE business_unit='pinnacle-Slc'
          AND trip_date BETWEEN '2026-05-26' AND '2026-05-30' GROUP BY 1) e USING (d)
      JOIN (SELECT t.trip_date d, count(*) fb_rows FROM fb f
            JOIN trips t ON f.trip_id=t.trip_id AND f.business_unit=t.business_unit
            WHERE t.business_unit='pinnacle-Slc'
            AND t.trip_date BETWEEN '2026-05-26' AND '2026-05-30' GROUP BY 1) f USING (d)
      JOIN (SELECT start_ts::DATE d, count(*) alert_rows FROM alerts
            WHERE business_unit='pinnacle-Slc'
            AND start_ts::DATE BETWEEN '2026-05-26' AND '2026-05-30' GROUP BY 1) a USING (d)
      ORDER BY d
    """)
    show("planned solo trips (timeliness M2)", """
      SELECT count(*) n, count(*) FILTER (WHERE emp_planned=1) planned_solo,
             round(100.0*avg(CASE WHEN emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
             count(*) FILTER (WHERE emp_planned>1 AND emp_actual=1) became_solo
      FROM trips
    """)
    show("pinnacle-Slc solo rate by office, same 3-seat fleet (timeliness M2)", """
      SELECT office, count(*) n,
             round(100.0*avg(CASE WHEN cab_capacity=3 THEN 1 ELSE 0 END),2) pct_cap3,
             round(100.0*avg(CASE WHEN emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
             round(avg(emp_planned),2) mean_planned
      FROM trips WHERE business_unit='pinnacle-Slc'
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 4 DESC
    """)


SECTIONS = {
    "base": s_base, "ota": s_ota, "reason": s_reason, "shift": s_shift,
    "spot": s_spot, "dow": s_dow, "load": s_load, "ids": s_ids, "bill": s_bill,
    "over": s_over, "slab": s_slab, "fb": s_fb, "fbcov": s_fbcov, "emp": s_emp,
    "rider": s_rider, "esc": s_esc, "esc2": s_esc2, "vendor": s_vendor,
    "alerts": s_alerts, "misc": s_misc,
}

if __name__ == "__main__":
    build()
    for s in (sys.argv[1:] or list(SECTIONS)):
        print(f"\n{'='*78}\n== {s.upper()}\n{'='*78}")
        SECTIONS[s]()
