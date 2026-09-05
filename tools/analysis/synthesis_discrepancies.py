#!/usr/bin/env python
"""
synthesis_discrepancies.py -- resolve the contradictions found between the seven
area findings docs during synthesis verification.

Run: ./.venv/bin/python tools/analysis/synthesis_discrepancies.py [d1 d2 ...]
"""
import sys
sys.path.insert(0, "/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis")
from synthesis_verify import build, show, con  # noqa: E402

D = {}


def d(fn):
    D[fn.__name__] = fn
    return fn


@d
def d1_escort_lastdrop():
    """D1: safety.md says orbit-Slc leaves 23.28% of female-last-drop night trips unescorted.
       employees.md says only 270 breaches platform-wide. The difference is whether the
       escort's own leg is included in arg_max(gender, actual_drop_epoch)."""
    con.sql("""
      CREATE OR REPLACE TEMP VIEW ld AS
      SELECT trip_id, business_unit,
             arg_max(gender, actual_drop_epoch) FILTER (WHERE TRUE)               AS last_incl_escort,
             arg_max(gender, actual_drop_epoch) FILTER (WHERE emp_role<>'escort'
                                                        OR emp_role IS NULL)      AS last_excl_escort
      FROM emp WHERE actual_drop_epoch IS NOT NULL GROUP BY 1,2
    """)
    show("is the escort himself the last leg? (escorted trips only)", """
      SELECT count(*) escorted_trips,
             count(*) FILTER (WHERE l.last_incl_escort='MALE')   last_incl_male,
             count(*) FILTER (WHERE l.last_excl_escort='FEMALE') last_excl_female,
             count(*) FILTER (WHERE l.last_incl_escort<>l.last_excl_escort) flips
      FROM trips t JOIN ld l USING (trip_id, business_unit)
      WHERE t.actual_escort AND t.trip_direction='LOGOUT'
    """)
    show("escort legs: how many and what gender", """
      SELECT emp_role, count(*) n,
             count(*) FILTER (WHERE gender='MALE') male,
             count(*) FILTER (WHERE gender='FEMALE') female
      FROM emp WHERE emp_role='escort' GROUP BY 1
    """)
    for lbl, colname in [("INCLUDING escort legs (safety.md method)", "last_incl_escort"),
                         ("EXCLUDING escort legs (employees.md method)", "last_excl_escort")]:
        show(f"female-last-drop night LOGOUT CAB, % unescorted -- {lbl}", f"""
          SELECT t.business_unit, count(*) n_female_last_drop,
                 count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
                 round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
          FROM trips t JOIN ld l USING (trip_id, business_unit)
          WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB'
            AND l.{colname}='FEMALE' AND t.shift_type LIKE '%:%'
            AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
                 OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
          GROUP BY 1 ORDER BY pct_no_escort DESC
        """)
    show("the tie-breaker: on UNESCORTED night trips the two methods must agree", """
      SELECT count(*) unescorted_night_logout_cab,
             count(*) FILTER (WHERE l.last_incl_escort='FEMALE') f_incl,
             count(*) FILTER (WHERE l.last_excl_escort='FEMALE') f_excl
      FROM trips t JOIN ld l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND NOT t.actual_escort
        AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
    """)
    show("so what IS orbit-Slc's 1,891? unescorted female-last-drop night trips by BU (both ways)", """
      SELECT t.business_unit,
             count(*) FILTER (WHERE NOT t.actual_escort AND l.last_incl_escort='FEMALE') unesc_f_incl,
             count(*) FILTER (WHERE NOT t.actual_escort AND l.last_excl_escort='FEMALE') unesc_f_excl,
             count(*) FILTER (WHERE t.actual_escort AND l.last_incl_escort='FEMALE') esc_f_incl,
             count(*) FILTER (WHERE t.actual_escort AND l.last_excl_escort='FEMALE') esc_f_excl
      FROM trips t JOIN ld l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
      GROUP BY 1 ORDER BY unesc_f_excl DESC
    """)


@d
def d2_wta_feedback_n():
    """D2: crosstable F4 reports n_ratings=649 for WOMAN_TRAVELLING_ALONE.
       Is that trip-level, or fanned out by the ~2 alerts per trip?"""
    show("WTA alert volume vs distinct trips", """
      SELECT count(*) alerts, count(DISTINCT trip_id) distinct_trip_ids,
             count(DISTINCT (trip_id, business_unit)) distinct_trip_bu,
             round(count(*)*1.0/count(DISTINCT (trip_id, business_unit)),2) alerts_per_trip
      FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE'
    """)
    show("feedback rows on WTA trips: deduped vs fanned out", """
      WITH ded AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE'),
           raw AS (SELECT trip_id, business_unit FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
      SELECT 'dedupe alerts first (correct)' m, count(*) n_rating_rows,
             round(avg(f.safety_rating),3) safety,
             round(100.0*count(*) FILTER (WHERE f.safety_rating<=3)/count(*),3) pct_le3
      FROM fb f JOIN ded USING (trip_id, business_unit)
      UNION ALL
      SELECT 'join alert rows directly (fan-out)', count(*),
             round(avg(f.safety_rating),3),
             round(100.0*count(*) FILTER (WHERE f.safety_rating<=3)/count(*),3)
      FROM fb f JOIN raw USING (trip_id, business_unit)
    """)
    show("effect vs baseline, on the deduped number", """
      WITH ded AS (SELECT DISTINCT trip_id, business_unit FROM alerts WHERE event_type='WOMAN_TRAVELLING_ALONE')
      SELECT (SELECT count(*) FROM fb f JOIN ded USING (trip_id, business_unit)) n_wta,
             (SELECT count(*) FROM fb f JOIN ded USING (trip_id, business_unit)
              WHERE f.safety_rating<=3) det_wta,
             (SELECT count(*) FROM fb) n_all,
             (SELECT count(*) FROM fb WHERE safety_rating<=3) det_all
    """)
    show("is it HER, or the whole cab? flagged rider vs co-rider on the same trip", """
      WITH w AS (SELECT DISTINCT trip_id, business_unit, stwid FROM alerts
                 WHERE event_type='WOMAN_TRAVELLING_ALONE' AND stwid NOT IN ('0','0.0')),
           t AS (SELECT DISTINCT trip_id, business_unit FROM w)
      SELECT CASE WHEN w.stwid IS NOT NULL THEN 'the flagged rider'
                  ELSE 'other rider on same trip' END g,
             count(*) n, round(avg(f.safety_rating),3) safety,
             round(100.0*count(*) FILTER (WHERE f.safety_rating<=3)/count(*),3) pct_le3
      FROM fb f JOIN t USING (trip_id, business_unit)
      LEFT JOIN w ON w.trip_id=f.trip_id AND w.business_unit=f.business_unit AND w.stwid=f.stwid
      GROUP BY 1 ORDER BY 1
    """)


@d
def d3_delay_rating_corr():
    """D3: feedback.md reports corr(delay_minutes, rating) = -0.029..-0.035.
       I get -0.003. Which population?"""
    show("correlation under different populations", """
      SELECT 'all trips' pop, count(*) n, round(corr(t.delay_minutes, f.driver_rating),5) driver,
             round(corr(t.delay_minutes, f.route_rating),5) route
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      UNION ALL
      SELECT 'excl SPOT_2.0', count(*), round(corr(t.delay_minutes, f.driver_rating),5),
             round(corr(t.delay_minutes, f.route_rating),5)
      FROM fb f JOIN trips t USING (trip_id, business_unit) WHERE t.product_type<>'SPOT_2.0'
      UNION ALL
      SELECT 'delay capped at 240 min', count(*),
             round(corr(least(t.delay_minutes,240), f.driver_rating),5),
             round(corr(least(t.delay_minutes,240), f.route_rating),5)
      FROM fb f JOIN trips t USING (trip_id, business_unit)
      UNION ALL
      SELECT 'delay <= 240 min only', count(*), round(corr(t.delay_minutes, f.driver_rating),5),
             round(corr(t.delay_minutes, f.route_rating),5)
      FROM fb f JOIN trips t USING (trip_id, business_unit) WHERE t.delay_minutes<=240
      UNION ALL
      SELECT 'JOIN ON trip_id ONLY (fan-out)', count(*),
             round(corr(t.delay_minutes, f.driver_rating),5),
             round(corr(t.delay_minutes, f.route_rating),5)
      FROM fb f JOIN trips t ON f.trip_id=t.trip_id
    """)
    show("how many feedback rows sit on extreme-delay trips", """
      SELECT count(*) n_fb_rows, max(t.delay_minutes) max_delay,
             count(*) FILTER (WHERE t.delay_minutes>1000) fb_on_delay_gt1000
      FROM fb f JOIN trips t USING (trip_id, business_unit)
    """)
    show("the honest statement: group means still move (dose-response)", """
      SELECT CASE WHEN t.delay_minutes=0 THEN 'a 0'
                  WHEN t.delay_minutes<=5 THEN 'b 1-5'
                  WHEN t.delay_minutes<=15 THEN 'c 6-15'
                  WHEN t.delay_minutes<=30 THEN 'd 16-30'
                  WHEN t.delay_minutes<=60 THEN 'e 31-60'
                  ELSE 'f 60+' END b,
             count(*) n, round(avg(f.route_rating),4) route,
             round(100.0*count(*) FILTER (WHERE f.route_rating<=2)/count(*),3) route_det_pct
      FROM fb f JOIN trips t USING (trip_id, business_unit) GROUP BY 1 ORDER BY 1
    """)


@d
def d4_driver_nc():
    """D4: timeliness.md DQ-warning 1 says is_driver_nc/is_cab_nc are 0 on all rows.
       safety.md MEDIUM-7 says 784 / 32. Who is right?"""
    show("raw string values as they appear in the CSV", """
      SELECT is_driver_nc, is_cab_nc, count(*) n
      FROM read_csv('/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw/Ride_data*.csv',
                    header=true, union_by_name=true, null_padding=true, ignore_errors=true,
                    all_varchar=true, sample_size=-1)
      GROUP BY 1,2 ORDER BY n DESC
    """)
    show("by month -- is the flag present in all three files?", """
      SELECT month, count(*) n,
             count(*) FILTER (WHERE is_driver_nc) drv_nc,
             count(*) FILTER (WHERE is_cab_nc) cab_nc,
             count(*) FILTER (WHERE is_driver_nc IS NULL) drv_null
      FROM trips GROUP BY 1 ORDER BY 1
    """)
    show("does the flag predict alerts or punctuality?", """
      WITH a AS (SELECT trip_id, business_unit, count(*) al FROM alerts GROUP BY 1,2)
      SELECT t.is_driver_nc, count(*) trips, round(100.0*avg(t.on_time),2) ota,
             round(1000.0*sum(coalesce(a.al,0))/count(*),2) alerts_per_1k
      FROM trips t LEFT JOIN a USING (trip_id, business_unit)
      GROUP BY 1 ORDER BY 1
    """)


@d
def d5_fb_coverage_vanta_aus():
    """D5: dataquality.md reports vanta-Aus feedback coverage 12.43%.
       feedback.md and my check both say 3.85%. Which?"""
    show("three candidate definitions of 'coverage'", """
      WITH t AS (SELECT business_unit, count(*) trips, count(DISTINCT trip_id) d_trips FROM trips GROUP BY 1),
           f AS (SELECT business_unit, count(*) fb_rows,
                        count(DISTINCT trip_id) fb_trip_ids FROM fb GROUP BY 1)
      SELECT t.business_unit, trips, fb_rows, fb_trip_ids,
             round(100.0*fb_trip_ids/trips,2) A_dtrips_over_trips,
             round(100.0*fb_rows/trips,2)     B_rows_over_trips,
             round(100.0*fb_trip_ids/d_trips,2) C_dtrips_over_dtrips
      FROM t JOIN f USING (business_unit) ORDER BY A_dtrips_over_trips
    """)
    show("cross-check: rated trips computed from the ride side (join, not count-distinct)", """
      SELECT t.business_unit, count(*) trips,
             count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb
                       WHERE fb.trip_id=t.trip_id AND fb.business_unit=t.business_unit)) rated,
             round(100.0*count(*) FILTER (WHERE EXISTS (SELECT 1 FROM fb
                       WHERE fb.trip_id=t.trip_id AND fb.business_unit=t.business_unit))/count(*),2) coverage_pct
      FROM trips t GROUP BY 1 ORDER BY coverage_pct
    """)


@d
def d6_delay_epoch_agreement():
    """D6: 'delay_minutes agrees with epoch arithmetic on 4.85% of trips' (dataquality)
       vs my 35.49%. The difference is whether you clip epoch lateness at zero."""
    show("agreement rate under four definitions", """
      SELECT count(*) n,
        round(100.0*avg(CASE WHEN abs(delay_minutes-((actual_end_epoch-planned_end_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),3) A_raw_end_dev,
        round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(actual_end_epoch-planned_end_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),3) B_clipped_end_dev,
        round(100.0*avg(CASE WHEN abs(delay_minutes-((actual_start_epoch-planned_start_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),3) C_raw_start_dev,
        round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(actual_start_epoch-planned_start_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),3) D_clipped_start_dev
      FROM trips
    """)
    show("...and it splits by direction (LOGIN=arrival, LOGOUT=departure)", """
      SELECT trip_direction, count(*) n,
        round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(actual_end_epoch-planned_end_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),2) matches_end,
        round(100.0*avg(CASE WHEN abs(delay_minutes-greatest(0,(actual_start_epoch-planned_start_epoch)/60.0))<=1
             THEN 1 ELSE 0 END),2) matches_start,
        round(corr(delay_minutes, greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)),3) corr_end,
        round(corr(delay_minutes, greatest(0,(actual_start_epoch-planned_start_epoch)/60.0)),3) corr_start
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1 ORDER BY 1
    """)
    show("OTA under five defensible definitions", """
      SELECT month,
        round(100.0*avg(on_time),2) A_delay_col_le5,
        round(100.0*avg(CASE WHEN delay_reason='NODELAY' THEN 1 ELSE 0 END),2) B_no_delay_reason,
        round(100.0*avg(CASE WHEN actual_end_epoch<=planned_end_epoch THEN 1 ELSE 0 END),2) C_end_le_plan,
        round(100.0*avg(CASE WHEN actual_end_epoch<=planned_end_epoch+300 THEN 1 ELSE 0 END),2) D_end_5min_grace,
        round(100.0*avg(CASE WHEN actual_start_epoch<=planned_start_epoch+300 THEN 1 ELSE 0 END),2) E_start_5min_grace
      FROM trips GROUP BY 1 ORDER BY 1
    """)


@d
def d7_overhead_owner():
    """D7: cost.md says positive OverHead is billed by exactly one vendor. Verify."""
    show("OverHead by vendor and sign", """
      SELECT vendor_id, count(*) n, round(sum(trip_cost),2) amt,
             count(*) FILTER (WHERE trip_cost>0) n_pos, count(*) FILTER (WHERE trip_cost<0) n_neg,
             count(DISTINCT business_unit) bus, count(DISTINCT office) offices
      FROM bill WHERE trip_id_raw='OverHead' GROUP BY 1 ORDER BY amt DESC
    """)
    show("Maple Grove Office: 100% OverHead?", """
      SELECT office, count(*) n, count(*) FILTER (WHERE trip_id_raw='OverHead') n_overhead,
             round(sum(trip_cost),2) net
      FROM bill GROUP BY 1 HAVING count(*) FILTER (WHERE trip_id_raw='OverHead')>0 ORDER BY n
    """)
    show("Pinecrest Office nets negative", """
      SELECT office, count(*) n, round(sum(trip_cost),2) net_spend,
             round(sum(trip_cost) FILTER (WHERE trip_cost>0),2) gross,
             round(sum(trip_cost) FILTER (WHERE trip_cost<0),2) credits
      FROM bill GROUP BY 1 ORDER BY net_spend LIMIT 4
    """)


@d
def d8_vendor_price_uniformity():
    """D8: crosstable F6 says vendor pricing is uniform (6.6pt index spread) but
       cost.md F1 says a 35% spread on BUS-ORRNEW-TT. Both can be true -- check."""
    show("vendor cost index vs peers on identical contract+BU+cycle_month", """
      WITH b AS (SELECT * FROM bill WHERE trip_cost>0 AND trip_id_raw<>'OverHead'),
           peer AS (SELECT contract_name, business_unit, cycle_month, avg(trip_cost) pc
                    FROM b GROUP BY 1,2,3)
      SELECT b.vendor_id, count(*) n, round(100.0*avg(b.trip_cost)/avg(peer.pc),2) cost_index
      FROM b JOIN peer USING (contract_name, business_unit, cycle_month)
      GROUP BY 1 HAVING count(*)>=1000 ORDER BY cost_index DESC
    """)
    show("...but WITHIN the fixed-rate bus contract at one office the spread is real", """
      SELECT contract_name, count(*) n,
             round(min(v),2) cheapest_vendor_avg, round(max(v),2) dearest_vendor_avg,
             round(100.0*(max(v)-min(v))/min(v),1) spread_pct
      FROM (SELECT contract_name, vendor_id, avg(trip_cost) v, count(*) c
            FROM bill WHERE contract_name IN ('BUS-ORRNEW-TT','BUS-ORRNEW-SML')
              AND trip_cost>0 AND office='Denver Office'
            GROUP BY 1,2 HAVING count(*)>=500)
      GROUP BY 1
    """)
    show("reconciliation: the index averages over contracts, so it hides within-contract spread", """
      WITH b AS (SELECT * FROM bill WHERE trip_cost>0 AND contract_name='BUS-ORRNEW-TT'
                   AND office='Denver Office')
      SELECT vendor_id, count(*) n, round(avg(trip_cost),2) avg_cost,
             round(100.0*avg(trip_cost)/(SELECT avg(trip_cost) FROM b),1) index_vs_contract_avg
      FROM b GROUP BY 1 HAVING count(*)>=500 ORDER BY index_vs_contract_avg DESC
    """)


@d
def d9_meera_alert_rate():
    """D9: crosstable says Meera Lebedev 180.96 alerts/1000 trips; I got 620. Which basis?"""
    show("three bases for the alert rate", """
      WITH t AS (SELECT vendor_id, count(*) trips FROM trips GROUP BY 1),
           a AS (SELECT x.vendor_id, count(*) alert_rows, count(DISTINCT x.event_id) d_events,
                        count(DISTINCT (x.trip_id, x.business_unit)) alerted_trips
                 FROM (SELECT al.*, t.vendor_id FROM alerts al
                       JOIN trips t ON al.trip_id=t.trip_id AND al.business_unit=t.business_unit) x
                 GROUP BY 1)
      SELECT t.vendor_id, trips, coalesce(alert_rows,0) alert_rows, coalesce(alerted_trips,0) alerted_trips,
             round(1000.0*coalesce(alert_rows,0)/trips,2) rows_per_1k,
             round(1000.0*coalesce(alerted_trips,0)/trips,2) alerted_trips_per_1k
      FROM t LEFT JOIN a USING (vendor_id) WHERE trips>=1000
      ORDER BY rows_per_1k DESC LIMIT 8
    """)


@d
def d10_rider_ota_denominator():
    """D10: employees.md rider pickup OTA = 71.56/69.21/71.53 (n=417,776...);
       crosstable = 72.12/69.30/71.27 (n=403,033...). Which denominator?"""
    show("rider pickup OTA under two null-handling rules", """
      SELECT month, count(*) FILTER (WHERE planned_pickup_epoch IS NOT NULL
                                       AND actual_pickup_epoch IS NOT NULL) n_pickup_only,
             round(100.0*avg(CASE WHEN (actual_pickup_epoch-planned_pickup_epoch)/60.0<=5 THEN 1.0 ELSE 0 END)
                   FILTER (WHERE planned_pickup_epoch IS NOT NULL AND actual_pickup_epoch IS NOT NULL),2) ota_pickup_only,
             count(*) FILTER (WHERE planned_pickup_epoch IS NOT NULL) n_planned_pickup,
             round(100.0*avg(CASE WHEN actual_pickup_epoch IS NOT NULL
                       AND (actual_pickup_epoch-planned_pickup_epoch)/60.0<=5 THEN 1.0 ELSE 0 END)
                   FILTER (WHERE planned_pickup_epoch IS NOT NULL),2) ota_noshow_counts_as_fail
      FROM emp GROUP BY 1 ORDER BY 1
    """)
    show("the structural nulls that make the denominator a choice", """
      SELECT count(*) legs,
             count(*) FILTER (WHERE boarding_status='Not Boarded') not_boarded,
             count(*) FILTER (WHERE actual_pickup_epoch IS NULL) null_actual_pickup,
             count(*) FILTER (WHERE planned_pickup_epoch IS NULL) null_planned_pickup,
             count(*) FILTER (WHERE signintype IN ('Adhoc','Guest')) adhoc_guest,
             count(*) FILTER (WHERE planned_pickup_epoch IS NOT NULL
                                AND actual_pickup_epoch IS NOT NULL) measurable
      FROM emp
    """)


@d
def d11_escort_deepdive():
    """D11: pin down the orbit-Slc escort claim. safety.md HIGH-5 says 23.28% of
       female-last-drop night trips are unescorted at orbit-Slc; employees.md F5 says
       the platform-wide breach count is 270 and orbit's rate is 2-5%. I reproduce 18."""
    con.sql("""
      CREATE OR REPLACE TEMP VIEW ld2 AS
      SELECT trip_id, business_unit,
             arg_max(gender, actual_drop_epoch) FILTER (WHERE emp_role IS DISTINCT FROM 'escort') AS lastg,
             max(actual_drop_epoch) FILTER (WHERE emp_role IS DISTINCT FROM 'escort')             AS last_drop
      FROM emp WHERE actual_drop_epoch IS NOT NULL GROUP BY 1,2
    """)
    show("does actual_escort even fire in every BU?", """
      SELECT business_unit, count(*) trips,
             count(*) FILTER (WHERE actual_escort) escorted,
             round(100.0*count(*) FILTER (WHERE actual_escort)/count(*),2) pct_escorted
      FROM trips GROUP BY 1 ORDER BY pct_escorted DESC
    """)
    show("A. night by SHIFT hour (19:00-05:59), LOGOUT, ALL products", """
      SELECT t.business_unit, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t JOIN ld2 l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND l.lastg='FEMALE' AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
      GROUP BY 1 ORDER BY pct_no_escort DESC
    """)
    show("B. night by ACTUAL LAST-DROP hour, UTC+5 offset, LOGOUT CAB", """
      SELECT t.business_unit, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t JOIN ld2 l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND l.lastg='FEMALE'
        AND (hour(to_timestamp(l.last_drop + 5*3600) AT TIME ZONE 'UTC')>=19
             OR hour(to_timestamp(l.last_drop + 5*3600) AT TIME ZONE 'UTC')<=5)
      GROUP BY 1 ORDER BY pct_no_escort DESC
    """)
    show("C. NO gender filter -- all night LOGOUT CAB, % unescorted (is orbit just low-escort?)", """
      SELECT t.business_unit, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
      GROUP BY 1 ORDER BY pct_no_escort DESC
    """)
    show("D. ANY female on board (not last-drop) at night, % unescorted", """
      WITH anyf AS (SELECT trip_id, business_unit,
                           max(CASE WHEN gender='FEMALE' AND emp_role IS DISTINCT FROM 'escort'
                                    THEN 1 ELSE 0 END) has_f,
                           count(*) FILTER (WHERE emp_role IS DISTINCT FROM 'escort') riders
                    FROM emp WHERE boarding_status='Boarded' GROUP BY 1,2)
      SELECT t.business_unit, count(*) n, count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t JOIN anyf a USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND t.product_type='CAB' AND a.has_f=1 AND t.shift_type LIKE '%:%'
        AND (TRY_CAST(split_part(t.shift_type,':',1) AS INT)>=19
             OR TRY_CAST(split_part(t.shift_type,':',1) AS INT)<=5)
      GROUP BY 1 ORDER BY pct_no_escort DESC
    """)
    show("E. the shift-boundary exposure: shift 17/18 LOGOUT whose last drop lands >=19:00 local", """
      SELECT t.business_unit, count(*) exposed, count(*) FILTER (WHERE NOT t.actual_escort) no_escort,
             round(100.0*count(*) FILTER (WHERE NOT t.actual_escort)/count(*),2) pct_no_escort
      FROM trips t JOIN ld2 l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND l.lastg='FEMALE' AND t.shift_type IN ('17:00','17:30','18:00','18:30','17:15','17:16','18:15','18:16')
        AND hour(to_timestamp(l.last_drop + 5*3600) AT TIME ZONE 'UTC')>=19
      GROUP BY 1 ORDER BY exposed DESC
    """)
    show("F. apples-to-apples: shift-18 vs shift-19 LOGOUT, last drop between 19:00 and 21:00", """
      SELECT TRY_CAST(split_part(t.shift_type,':',1) AS INT) shift_hour,
             count(*) n_female_last_drop,
             round(100.0*avg(CASE WHEN t.actual_escort THEN 1 ELSE 0 END),2) pct_escort
      FROM trips t JOIN ld2 l USING (trip_id, business_unit)
      WHERE t.trip_direction='LOGOUT' AND l.lastg='FEMALE' AND t.shift_type LIKE '%:%'
        AND TRY_CAST(split_part(t.shift_type,':',1) AS INT) IN (18,19)
        AND hour(to_timestamp(l.last_drop + 5*3600) AT TIME ZONE 'UTC') BETWEEN 19 AND 20
      GROUP BY 1 ORDER BY 1
    """)


def main():
    build()
    names = sys.argv[1:] or list(D)
    for nm in names:
        for k in [k for k in D if k == nm or k.startswith(nm)]:
            print(f"\n{'='*78}\n== {k}: {D[k].__doc__}\n{'='*78}")
            try:
                D[k]()
            except Exception as e:
                print(f"!! FAILED {k}: {type(e).__name__}: {e}")


if __name__ == '__main__':
    main()


