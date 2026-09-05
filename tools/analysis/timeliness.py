#!/usr/bin/env python
"""
timeliness.py - TIMELINESS & OPERATIONS analysis on ride_data_trip.

Usage:  python timeliness.py <stage>
Stage 0 = build persisted duckdb table (run once)
Stage 1 = shift_type profiling + shift bands
Stage 2 = day-of-week + daily time series / change points
Stage 3 = delay distribution (p50/p90/p99), concentration of delay minutes
Stage 4 = planned vs actual duration from epochs
Stage 5 = km drift (traveled vs planned)
Stage 6 = capacity / occupancy / noshow
Stage 7 = cross-checks: occupancy vs OTA, artifact hunts
"""
import sys, textwrap
import duckdb

DB = "/private/tmp/claude-501/-Users-ankitnehra-Documents-ankit/4aa30f9f-2c2d-4402-94e1-d7ce64f088f1/scratchpad/timeliness.duckdb"
RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw/Ride_data*.csv"

con = duckdb.connect(DB)
con.sql("SET threads TO 8")


def show(rel):
    """pandas-free table printer."""
    cols = rel.columns
    rows = rel.fetchall()
    def fmt(v):
        if v is None:
            return "NULL"
        if isinstance(v, float):
            return f"{v:,.2f}" if abs(v) < 1e12 else f"{v:.4g}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)
    table = [list(cols)] + [[fmt(v) for v in r] for r in rows]
    w = [max(len(row[i]) for row in table) for i in range(len(cols))]
    sep = "-+-".join("-" * x for x in w)
    out = [" | ".join(table[0][i].ljust(w[i]) for i in range(len(cols))), sep]
    for r in table[1:]:
        out.append(" | ".join(r[i].rjust(w[i]) for i in range(len(cols))))
    out.append(f"({len(rows)} rows)")
    print("\n".join(out))


def q(title, sql):
    print("\n" + "=" * 100)
    print(f"### {title}")
    print("=" * 100)
    show(con.sql(textwrap.dedent(sql)))


def build():
    con.sql(f"""
    CREATE OR REPLACE TABLE trips AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, office, product_type, vendor_id, trip_direction,
      shift_type,
      coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, actual_cab_fuel_type,
      route_source,
      strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
      date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
      dayname(strptime(trip_date,'%B %d, %Y')::DATE) AS dow,
      isodow(strptime(trip_date,'%B %d, %Y')::DATE) AS dow_n,
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
      planned_cab_registration, actual_cab_registration,
      TRY_CAST(replace(planned_start_epoch,',','') AS BIGINT) AS planned_start_epoch,
      TRY_CAST(replace(planned_end_epoch,',','')   AS BIGINT) AS planned_end_epoch,
      TRY_CAST(replace(actual_start_epoch,',','')  AS BIGINT) AS actual_start_epoch,
      TRY_CAST(replace(actual_end_epoch,',','')    AS BIGINT) AS actual_end_epoch,
      CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
    FROM read_csv('{RAW}', header=true, union_by_name=true,
      null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)
    """)
    show(con.sql("SELECT count(*) n_rows, count(trip_id) tid_ok, min(trip_date) d0, max(trip_date) d1, "
                 "count(DISTINCT trip_date) n_days, count(DISTINCT shift_type) n_shifts FROM trips"))


SHIFT_BAND = """
  CASE
    WHEN shift_hour IS NULL THEN 'UNPARSED'
    WHEN shift_hour < 6  THEN '00:00-05:59'
    WHEN shift_hour < 10 THEN '06:00-09:59'
    WHEN shift_hour < 16 THEN '10:00-15:59'
    WHEN shift_hour < 21 THEN '16:00-20:59'
    ELSE '21:00-23:59' END
"""


def add_band():
    con.sql("""
    CREATE OR REPLACE VIEW t AS
    SELECT *,
      CASE WHEN regexp_matches(shift_type, '^[0-9]{1,2}:[0-9]{2}')
           THEN TRY_CAST(split_part(shift_type, ':', 1) AS INT) END AS shift_hour
    FROM trips
    """)
    con.sql(f"CREATE OR REPLACE VIEW tb AS SELECT *, {SHIFT_BAND} AS shift_band FROM t")


def stage1():
    add_band()
    q("1a. shift_type raw format sample (top 40 by volume)", """
      SELECT shift_type, count(*) n, round(100.0*avg(on_time),2) ota,
             round(median(delay_minutes),1) p50_delay
      FROM trips GROUP BY 1 ORDER BY n DESC LIMIT 40""")
    q("1b. shift_type distinct count + null/blank", """
      SELECT count(DISTINCT shift_type) distinct_shifts,
             sum(CASE WHEN shift_type IS NULL THEN 1 ELSE 0 END) null_shift,
             sum(CASE WHEN shift_type='' THEN 1 ELSE 0 END) blank_shift,
             count(*) total FROM trips""")
    q("1c. shift_hour parse coverage", """
      SELECT CASE WHEN shift_hour IS NULL THEN 'UNPARSED' ELSE 'parsed' END k,
             count(*) n, count(DISTINCT shift_type) shifts
      FROM t GROUP BY 1 ORDER BY n DESC""")
    q("1d. Unparsed shift_type values", """
      SELECT shift_type, count(*) n FROM t WHERE shift_hour IS NULL
      GROUP BY 1 ORDER BY n DESC LIMIT 30""")
    q("1e. ALL 100 shift_types with OTA (full list, ordered by minute)", """
      SELECT shift_type, split_part(shift_type,':',2) AS mm, count(*) n,
             round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay
      FROM trips GROUP BY 1,2 ORDER BY mm, shift_type""")
    q("1f. *** MINUTE-SUFFIX FAMILIES: the :15/:16 anomaly ***", """
      SELECT split_part(shift_type,':',2) AS minute_suffix, count(DISTINCT shift_type) n_shifts,
             count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),3) mean_delay,
             round(max(delay_minutes),2) max_delay,
             round(100.0*avg(CASE WHEN delay_minutes=0 THEN 1 ELSE 0 END),2) pct_delay_exactly_0,
             round(100.0*avg(CASE WHEN delay_minutes IS NULL THEN 1 ELSE 0 END),2) pct_null_delay
      FROM trips GROUP BY 1 ORDER BY n DESC""")
    q("1g. ARTIFACT CHECK: who are the :16 shifts? BU/office/product/vendor/route_source", """
      SELECT CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 'odd_min_15_16' ELSE 'normal' END grp,
             business_unit, office, product_type, route_source, count(*) n,
             round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2,3,4,5 ORDER BY grp, n DESC LIMIT 40""")
    q("1h. ARTIFACT CHECK: do :15/:16 shifts have real epochs & km, or are they synthetic?", """
      SELECT CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 'odd_min_15_16' ELSE 'normal' END grp,
        count(*) n,
        round(100.0*avg(CASE WHEN actual_end_epoch IS NULL THEN 1 ELSE 0 END),2) pct_null_actual_end,
        round(100.0*avg(CASE WHEN delay_minutes IS NULL THEN 1 ELSE 0 END),2) pct_null_delay,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),3) mean_end_dev_min,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.9),2) p90_end_dev,
        round(avg(traveled_km),2) mean_km, round(avg(emp_actual),2) mean_riders,
        count(DISTINCT delay_reason) n_delay_reasons
      FROM trips GROUP BY 1""")
    q("1i. :15/:16 volume by month (is this growing? does it mask the June dip?)", """
      SELECT month,
        sum(CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 1 ELSE 0 END) n_odd,
        count(*) n_total,
        round(100.0*avg(CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 1 ELSE 0 END),2) pct_odd,
        round(100.0*avg(on_time),2) ota_all,
        round(100.0*avg(CASE WHEN split_part(shift_type,':',2) NOT IN ('15','16') THEN on_time END),2) ota_excl_odd
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("1j. OTA by shift_band x month", """
      SELECT shift_band, month, count(*) n, round(100.0*avg(on_time),2) ota
      FROM tb GROUP BY 1,2 ORDER BY 1,2""")
    q("1k. shift_band June/July deltas (pivot)", """
      WITH m AS (SELECT shift_band, month, count(*) n, 100.0*avg(on_time) ota FROM tb GROUP BY 1,2)
      SELECT shift_band,
        max(CASE WHEN month='2026-05-01' THEN n END) n_may,
        max(CASE WHEN month='2026-06-01' THEN n END) n_jun,
        max(CASE WHEN month='2026-07-01' THEN n END) n_jul,
        round(max(CASE WHEN month='2026-05-01' THEN ota END),2) may,
        round(max(CASE WHEN month='2026-06-01' THEN ota END),2) jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END),2) jul,
        round(max(CASE WHEN month='2026-06-01' THEN ota END)-max(CASE WHEN month='2026-05-01' THEN ota END),2) d_jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END)-max(CASE WHEN month='2026-06-01' THEN ota END),2) d_jul
      FROM m GROUP BY 1 ORDER BY d_jun""")
    q("1l. shift_band excluding :15/:16 synthetic-looking shifts", """
      WITH m AS (SELECT shift_band, month, count(*) n, 100.0*avg(on_time) ota
                 FROM tb WHERE split_part(shift_type,':',2) NOT IN ('15','16') GROUP BY 1,2)
      SELECT shift_band,
        max(CASE WHEN month='2026-05-01' THEN n END) n_may,
        max(CASE WHEN month='2026-06-01' THEN n END) n_jun,
        round(max(CASE WHEN month='2026-05-01' THEN ota END),2) may,
        round(max(CASE WHEN month='2026-06-01' THEN ota END),2) jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END),2) jul,
        round(max(CASE WHEN month='2026-06-01' THEN ota END)-max(CASE WHEN month='2026-05-01' THEN ota END),2) d_jun
      FROM m GROUP BY 1 ORDER BY d_jun""")
    q("1m. Worst shift_types overall (n>=500)", """
      SELECT shift_type, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),1) mean_delay,
             round(quantile_cont(delay_minutes,0.9),1) p90
      FROM trips GROUP BY 1 HAVING count(*)>=500 ORDER BY ota ASC LIMIT 25""")
    q("1n. Biggest June drop by shift_type (n>=500 in both May and June)", """
      WITH m AS (SELECT shift_type, month, count(*) n, 100.0*avg(on_time) ota FROM trips GROUP BY 1,2)
      SELECT shift_type,
        max(CASE WHEN month='2026-05-01' THEN n END) n_may,
        max(CASE WHEN month='2026-06-01' THEN n END) n_jun,
        round(max(CASE WHEN month='2026-05-01' THEN ota END),2) may,
        round(max(CASE WHEN month='2026-06-01' THEN ota END),2) jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END),2) jul,
        round(max(CASE WHEN month='2026-06-01' THEN ota END)-max(CASE WHEN month='2026-05-01' THEN ota END),2) d_jun
      FROM m GROUP BY 1
      HAVING max(CASE WHEN month='2026-05-01' THEN n END)>=500
         AND max(CASE WHEN month='2026-06-01' THEN n END)>=500
      ORDER BY d_jun ASC LIMIT 20""")
    q("1o. Non Shift / Adhoc detail", """
      SELECT shift_type, month, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay
      FROM trips WHERE shift_type IN ('Non Shift','Adhoc') GROUP BY 1,2 ORDER BY 1,2""")


def stage2():
    add_band()
    q("2a. DOW pivot with June delta", """
      WITH m AS (SELECT dow_n, dow, month, count(*) n, 100.0*avg(on_time) ota FROM trips GROUP BY 1,2,3)
      SELECT dow_n, dow,
        max(CASE WHEN month='2026-05-01' THEN n END) n_may,
        max(CASE WHEN month='2026-06-01' THEN n END) n_jun,
        max(CASE WHEN month='2026-07-01' THEN n END) n_jul,
        round(max(CASE WHEN month='2026-05-01' THEN ota END),2) may,
        round(max(CASE WHEN month='2026-06-01' THEN ota END),2) jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END),2) jul,
        round(max(CASE WHEN month='2026-06-01' THEN ota END)-max(CASE WHEN month='2026-05-01' THEN ota END),2) d_jun
      FROM m GROUP BY 1,2 ORDER BY dow_n""")
    q("2b. Daily time series - all 92 days", """
      SELECT trip_date, dow, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay
      FROM trips GROUP BY 1,2 ORDER BY 1""")
    q("2c. Change point scan: 7-day trailing mean OTA", """
      WITH d AS (SELECT trip_date, count(*) n, 100.0*avg(on_time) ota FROM trips GROUP BY 1)
      SELECT trip_date, n, round(ota,2) ota,
        round(avg(ota) OVER (ORDER BY trip_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),2) ma7,
        round(ota - avg(ota) OVER (ORDER BY trip_date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING),2) vs_prev7
      FROM d ORDER BY trip_date""")
    q("2d. Worst 20 days overall", """
      SELECT trip_date, dow, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2 ORDER BY ota ASC LIMIT 20""")
    q("2e. Weekday vs weekend monthly OTA", """
      SELECT CASE WHEN dow_n<=5 THEN 'weekday' ELSE 'weekend' END k, month,
             count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2 ORDER BY 1,2""")
    q("2f. Week-of-month buckets", """
      SELECT month, ceil(day(trip_date)/7.0) wk, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2 ORDER BY 1,2""")
    q("2g. ISO week series", """
      SELECT weekofyear(trip_date) iso_wk, min(trip_date) wk_start, count(*) n,
             round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("2h. Same-weekday comparison: Mondays only, all months", """
      SELECT dow, trip_date, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow_n=1 GROUP BY 1,2 ORDER BY 2""")
    q("2i. Weekday-only OTA by month, EXCLUDING :15/:16 shifts", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow_n<=5 AND split_part(shift_type,':',2) NOT IN ('15','16')
      GROUP BY 1 ORDER BY 1""")


def stage3():
    add_band()
    q("3a. delay_minutes distribution by month", """
      SELECT month, count(*) n, count(delay_minutes) non_null,
        round(min(delay_minutes),2) mn,
        round(quantile_cont(delay_minutes,0.50),2) p50,
        round(quantile_cont(delay_minutes,0.75),2) p75,
        round(quantile_cont(delay_minutes,0.90),2) p90,
        round(quantile_cont(delay_minutes,0.95),2) p95,
        round(quantile_cont(delay_minutes,0.99),2) p99,
        round(max(delay_minutes),1) mx, round(avg(delay_minutes),2) mean
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("3b. delay by product_type x month", """
      SELECT product_type, month, count(*) n, round(100.0*avg(on_time),2) ota,
        round(quantile_cont(delay_minutes,0.50),2) p50,
        round(quantile_cont(delay_minutes,0.90),2) p90,
        round(quantile_cont(delay_minutes,0.99),2) p99,
        round(avg(delay_minutes),2) mean
      FROM trips GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("3c. Share of total delay minutes from worst 1%/5%/10% (positive-delay trips)", """
      WITH r AS (SELECT delay_minutes, ntile(1000) OVER (ORDER BY delay_minutes DESC) AS b
                 FROM trips WHERE delay_minutes>0)
      SELECT count(*) n_pos_delay_trips, round(sum(delay_minutes),0) total_delay_min,
        round(100.0*sum(CASE WHEN b<=10  THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_1pct,
        round(100.0*sum(CASE WHEN b<=50  THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_5pct,
        round(100.0*sum(CASE WHEN b<=100 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_10pct
      FROM r""")
    q("3c2. Same, denominator = ALL non-null trips", """
      WITH r AS (SELECT delay_minutes, ntile(1000) OVER (ORDER BY delay_minutes DESC) AS b
                 FROM trips WHERE delay_minutes IS NOT NULL)
      SELECT count(*) n_all, round(sum(delay_minutes),0) total_delay,
        round(100.0*sum(CASE WHEN b<=10 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_1pct,
        round(100.0*sum(CASE WHEN b<=50 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_5pct,
        round(100.0*sum(CASE WHEN b<=100 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_10pct
      FROM r""")
    q("3d. Delay buckets by month", """
      SELECT month, count(*) n,
        round(100.0*avg(CASE WHEN delay_minutes<=0 THEN 1 ELSE 0 END),2) pct_le0,
        round(100.0*avg(CASE WHEN delay_minutes>0  AND delay_minutes<=5  THEN 1 ELSE 0 END),2) pct_0_5,
        round(100.0*avg(CASE WHEN delay_minutes>5  AND delay_minutes<=15 THEN 1 ELSE 0 END),2) pct_5_15,
        round(100.0*avg(CASE WHEN delay_minutes>15 AND delay_minutes<=30 THEN 1 ELSE 0 END),2) pct_15_30,
        round(100.0*avg(CASE WHEN delay_minutes>30 AND delay_minutes<=60 THEN 1 ELSE 0 END),2) pct_30_60,
        round(100.0*avg(CASE WHEN delay_minutes>60 THEN 1 ELSE 0 END),4) pct_gt60,
        sum(CASE WHEN delay_minutes>60 THEN 1 ELSE 0 END) n_gt60,
        sum(CASE WHEN delay_minutes>240 THEN 1 ELSE 0 END) n_gt240
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("3e. Extreme delay (>240min): what are they?", """
      SELECT month, product_type, trip_direction, route_source, coalesce(delay_reason,'NULL') dr,
             count(*) n, round(avg(delay_minutes),0) avg_delay
      FROM trips WHERE delay_minutes>240 GROUP BY 1,2,3,4,5 ORDER BY n DESC LIMIT 25""")
    q("3f. ARTIFACT: >240min trips - does epoch diff agree with delay_minutes?", """
      SELECT count(*) n,
        round(avg(delay_minutes),1) avg_delay_col,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),1) avg_epoch_diff_min,
        round(corr(delay_minutes,(actual_end_epoch-planned_end_epoch)/60.0),4) corr
      FROM trips WHERE delay_minutes>240 AND actual_end_epoch IS NOT NULL AND planned_end_epoch IS NOT NULL""")
    q("3g. GLOBAL: is delay_minutes == (actual_end-planned_end)/60?", """
      SELECT count(*) n,
        round(corr(delay_minutes,(actual_end_epoch-planned_end_epoch)/60.0),5) corr,
        round(avg(abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)),3) mean_abs_diff,
        round(100.0*avg(CASE WHEN abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<1 THEN 1 ELSE 0 END),2) pct_match_1min
      FROM trips WHERE delay_minutes IS NOT NULL AND actual_end_epoch IS NOT NULL AND planned_end_epoch IS NOT NULL""")
    q("3h. delay_reason x month", """
      SELECT coalesce(delay_reason,'NULL') dr, month, count(*) n,
             round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),1) mean_delay
      FROM trips GROUP BY 1,2 HAVING count(*)>=200 ORDER BY 1,2""")
    q("3i. SLA minutes lost per month", """
      SELECT month, count(*) n,
        sum(CASE WHEN delay_minutes>5 THEN 1 ELSE 0 END) n_late,
        round(sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END),0) pos_delay_min,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END),0) min_beyond_sla,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/60.0,0) hrs_beyond_sla
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("3j. Late-trip severity: conditional on being late (>5), how late?", """
      SELECT month, count(*) n_late,
        round(avg(delay_minutes),2) mean, round(quantile_cont(delay_minutes,0.5),2) p50,
        round(quantile_cont(delay_minutes,0.9),2) p90, round(quantile_cont(delay_minutes,0.99),2) p99
      FROM trips WHERE delay_minutes>5 GROUP BY 1 ORDER BY 1""")
    q("3k. p90/p99 by shift_band x month", """
      SELECT shift_band, month, count(*) n, round(100.0*avg(on_time),2) ota,
        round(quantile_cont(delay_minutes,0.9),2) p90, round(quantile_cont(delay_minutes,0.99),2) p99
      FROM tb GROUP BY 1,2 ORDER BY 1,2""")


def stage4():
    add_band()
    q("4a. Epoch sanity", """
      SELECT count(*) n,
        count(planned_start_epoch) ps, count(planned_end_epoch) pe,
        count(actual_start_epoch) ast, count(actual_end_epoch) ae,
        min(planned_start_epoch) min_ps, max(planned_start_epoch) max_ps,
        CAST(to_timestamp(min(planned_start_epoch)) AS VARCHAR) t0,
        CAST(to_timestamp(max(planned_start_epoch)) AS VARCHAR) t1
      FROM trips""")
    q("4b. Raw duration outlier profile", """
      WITH d AS (SELECT month, (planned_end_epoch-planned_start_epoch)/60.0 pdur,
                        (actual_end_epoch-actual_start_epoch)/60.0 adur FROM trips)
      SELECT month, count(*) n, count(pdur) pdur_nn, count(adur) adur_nn,
        sum(CASE WHEN pdur<0 THEN 1 ELSE 0 END) neg_plan,
        sum(CASE WHEN adur<0 THEN 1 ELSE 0 END) neg_actual,
        sum(CASE WHEN pdur>600 THEN 1 ELSE 0 END) plan_gt10h,
        sum(CASE WHEN adur>600 THEN 1 ELSE 0 END) act_gt10h,
        round(quantile_cont(pdur,0.99),1) p99_plan, round(quantile_cont(adur,0.99),1) p99_act
      FROM d GROUP BY 1 ORDER BY 1""")
    q("4c. Planned vs actual duration by month (0-600 min filter)", """
      WITH d AS (SELECT month, (planned_end_epoch-planned_start_epoch)/60.0 pdur,
                        (actual_end_epoch-actual_start_epoch)/60.0 adur FROM trips)
      SELECT month, count(*) n,
        round(avg(pdur),2) mean_planned_min, round(avg(adur),2) mean_actual_min,
        round(avg(adur-pdur),2) mean_overrun_min,
        round(quantile_cont(adur-pdur,0.5),2) p50_overrun,
        round(quantile_cont(adur-pdur,0.9),2) p90_overrun,
        round(100.0*avg(CASE WHEN adur>pdur THEN 1 ELSE 0 END),2) pct_over_plan
      FROM d WHERE pdur BETWEEN 0 AND 600 AND adur BETWEEN 0 AND 600 GROUP BY 1 ORDER BY 1""")
    q("4d. Start-dev vs duration-dev decomposition by month", """
      WITH d AS (SELECT month,
          (actual_start_epoch-planned_start_epoch)/60.0 start_dev,
          (actual_end_epoch-planned_end_epoch)/60.0 end_dev,
          (actual_end_epoch-actual_start_epoch)/60.0-(planned_end_epoch-planned_start_epoch)/60.0 dur_dev
        FROM trips)
      SELECT month, count(*) n,
        round(avg(start_dev),2) mean_start_dev, round(quantile_cont(start_dev,0.5),2) p50_start_dev,
        round(avg(end_dev),2) mean_end_dev, round(quantile_cont(end_dev,0.5),2) p50_end_dev,
        round(avg(dur_dev),2) mean_dur_dev, round(quantile_cont(dur_dev,0.5),2) p50_dur_dev,
        round(100.0*avg(CASE WHEN start_dev>5 THEN 1 ELSE 0 END),2) pct_start_late5,
        round(100.0*avg(CASE WHEN dur_dev>5 THEN 1 ELSE 0 END),2) pct_dur_over5
      FROM d WHERE abs(start_dev)<600 AND abs(end_dev)<600 AND abs(dur_dev)<600
      GROUP BY 1 ORDER BY 1""")
    q("4e. Among LATE trips only: was it a late start or a slow run?", """
      WITH d AS (SELECT month, delay_minutes,
          (actual_start_epoch-planned_start_epoch)/60.0 start_dev,
          (actual_end_epoch-actual_start_epoch)/60.0-(planned_end_epoch-planned_start_epoch)/60.0 dur_dev
        FROM trips WHERE delay_minutes>5)
      SELECT month, count(*) n_late,
        round(avg(start_dev),2) mean_start_dev, round(avg(dur_dev),2) mean_dur_dev,
        round(100.0*avg(CASE WHEN start_dev>dur_dev THEN 1 ELSE 0 END),2) pct_start_dominated,
        round(100.0*avg(CASE WHEN start_dev<=5 AND dur_dev>5 THEN 1 ELSE 0 END),2) pct_ontime_start_slow_run,
        round(100.0*avg(CASE WHEN start_dev>5 THEN 1 ELSE 0 END),2) pct_started_late
      FROM d WHERE abs(start_dev)<600 AND abs(dur_dev)<600 GROUP BY 1 ORDER BY 1""")
    q("4f. Decomposition by shift_band x month", """
      WITH d AS (SELECT month, shift_band,
          (actual_start_epoch-planned_start_epoch)/60.0 start_dev,
          (actual_end_epoch-actual_start_epoch)/60.0-(planned_end_epoch-planned_start_epoch)/60.0 dur_dev
        FROM tb)
      SELECT shift_band, month, count(*) n,
        round(avg(start_dev),2) mean_start_dev, round(avg(dur_dev),2) mean_dur_dev
      FROM d WHERE abs(start_dev)<600 AND abs(dur_dev)<600 GROUP BY 1,2 ORDER BY 1,2""")
    q("4g. Planned duration realism: planned vs actual by product_type", """
      WITH d AS (SELECT product_type, month, (planned_end_epoch-planned_start_epoch)/60.0 pdur,
                        (actual_end_epoch-actual_start_epoch)/60.0 adur FROM trips)
      SELECT product_type, month, count(*) n,
        round(avg(pdur),2) planned, round(avg(adur),2) actual, round(avg(adur-pdur),2) overrun
      FROM d WHERE pdur BETWEEN 0 AND 600 AND adur BETWEEN 0 AND 600
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")


def stage5():
    add_band()
    q("5a. km sanity by month", """
      SELECT month, count(*) n, count(planned_km) pk_nn, count(traveled_km) tk_nn,
        sum(CASE WHEN planned_km<0 THEN 1 ELSE 0 END) neg_pk,
        sum(CASE WHEN traveled_km<0 THEN 1 ELSE 0 END) neg_tk,
        sum(CASE WHEN planned_km=0 THEN 1 ELSE 0 END) zero_pk,
        sum(CASE WHEN traveled_km=0 THEN 1 ELSE 0 END) zero_tk,
        round(min(planned_km),2) min_pk, round(max(planned_km),1) max_pk,
        round(min(traveled_km),2) min_tk, round(max(traveled_km),1) max_tk
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("5b. km drift by month (planned_km>0)", """
      SELECT month, count(*) n,
        round(sum(planned_km),0) sum_planned, round(sum(traveled_km),0) sum_traveled,
        round(100.0*(sum(traveled_km)-sum(planned_km))/sum(planned_km),2) pct_drift,
        round(avg(traveled_km-planned_km),3) mean_excess_km,
        round(quantile_cont(traveled_km-planned_km,0.5),3) p50_excess,
        round(quantile_cont(traveled_km-planned_km,0.9),3) p90_excess,
        round(100.0*avg(CASE WHEN traveled_km>planned_km THEN 1 ELSE 0 END),2) pct_over_plan
      FROM trips WHERE planned_km>0 AND traveled_km IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("5c. km drift by office x month", """
      SELECT office, month, count(*) n,
        round(100.0*(sum(traveled_km)-sum(planned_km))/sum(planned_km),2) pct_drift,
        round(avg(traveled_km-planned_km),3) mean_excess
      FROM trips WHERE planned_km>0 AND traveled_km IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("5d. km drift by vendor x month", """
      SELECT vendor_id, month, count(*) n,
        round(100.0*(sum(traveled_km)-sum(planned_km))/sum(planned_km),2) pct_drift,
        round(avg(traveled_km-planned_km),3) mean_excess
      FROM trips WHERE planned_km>0 AND traveled_km IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("5e. Does excess km predict delay?", """
      SELECT CASE WHEN traveled_km-planned_km <= 0 THEN 'a. <=0'
                  WHEN traveled_km-planned_km <= 2 THEN 'b. 0-2'
                  WHEN traveled_km-planned_km <= 5 THEN 'c. 2-5'
                  WHEN traveled_km-planned_km <= 10 THEN 'd. 5-10'
                  ELSE 'e. >10' END bucket,
        count(*) n, round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay
      FROM trips WHERE planned_km>0 AND traveled_km IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("5f. route_source x month: drift + OTA", """
      SELECT route_source, month, count(*) n, round(100.0*avg(on_time),2) ota,
        round(100.0*(sum(traveled_km)-sum(planned_km))/sum(planned_km),2) pct_drift
      FROM trips WHERE planned_km>0 GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("5g. ARTIFACT: distribution of traveled/planned ratio", """
      SELECT round(quantile_cont(traveled_km/planned_km,0.01),3) p01,
             round(quantile_cont(traveled_km/planned_km,0.10),3) p10,
             round(quantile_cont(traveled_km/planned_km,0.50),3) p50,
             round(quantile_cont(traveled_km/planned_km,0.90),3) p90,
             round(quantile_cont(traveled_km/planned_km,0.99),3) p99,
             count(*) n,
             round(100.0*avg(CASE WHEN traveled_km=planned_km THEN 1 ELSE 0 END),2) pct_exactly_equal
      FROM trips WHERE planned_km>0 AND traveled_km>0""")
    q("5h. km drift by shift_band x month", """
      SELECT shift_band, month, count(*) n,
        round(100.0*(sum(traveled_km)-sum(planned_km))/sum(planned_km),2) pct_drift
      FROM tb WHERE planned_km>0 AND traveled_km IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")


def stage6():
    add_band()
    q("6a. Capacity sanity", """
      SELECT month, count(*) n, count(cab_capacity) cap_nn, count(emp_actual) ea_nn,
        min(cab_capacity) min_cap, max(cab_capacity) max_cap,
        min(emp_actual) min_ea, max(emp_actual) max_ea,
        sum(CASE WHEN cab_capacity=0 THEN 1 ELSE 0 END) cap0,
        sum(CASE WHEN emp_actual=0 THEN 1 ELSE 0 END) ea0,
        sum(CASE WHEN emp_actual>cab_capacity THEN 1 ELSE 0 END) over_cap
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("6b. cab_capacity distribution", """
      SELECT cab_capacity, count(*) n, round(avg(emp_actual),2) mean_riders,
             round(avg(emp_planned),2) mean_planned, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1 ORDER BY n DESC LIMIT 20""")
    q("6c. Occupancy by month (cap>0)", """
      SELECT month, count(*) n,
        round(100.0*sum(emp_actual)/sum(cab_capacity),2) seat_fill_pct,
        sum(emp_actual) seats_used, sum(cab_capacity) seats_offered,
        round(avg(emp_actual),3) mean_riders,
        round(100.0*avg(CASE WHEN emp_actual=1 THEN 1 ELSE 0 END),2) pct_solo,
        round(100.0*avg(CASE WHEN emp_actual=0 THEN 1 ELSE 0 END),2) pct_zero_riders
      FROM trips WHERE cab_capacity>0 AND emp_actual IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("6d. Occupancy by product_type x month", """
      SELECT product_type, month, count(*) n,
        round(100.0*sum(emp_actual)/sum(cab_capacity),2) seat_fill_pct,
        round(avg(emp_actual),2) mean_riders, round(avg(cab_capacity),2) mean_cap,
        round(100.0*avg(CASE WHEN emp_actual<=1 THEN 1 ELSE 0 END),2) pct_le1
      FROM trips WHERE cab_capacity>0 AND emp_actual IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("6e. Occupancy by office x month", """
      SELECT office, month, count(*) n,
        round(100.0*sum(emp_actual)/sum(cab_capacity),2) seat_fill_pct,
        round(avg(emp_actual),2) mean_riders,
        round(100.0*avg(CASE WHEN emp_actual<=1 THEN 1 ELSE 0 END),2) pct_le1
      FROM trips WHERE cab_capacity>0 AND emp_actual IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("6f. Occupancy by shift_band x month", """
      SELECT shift_band, month, count(*) n,
        round(100.0*sum(emp_actual)/sum(cab_capacity),2) seat_fill_pct,
        round(avg(emp_actual),2) mean_riders, round(avg(cab_capacity),2) mean_cap,
        round(100.0*avg(CASE WHEN emp_actual<=1 THEN 1 ELSE 0 END),2) pct_le1
      FROM tb WHERE cab_capacity>0 AND emp_actual IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")
    q("6g. Solo/near-empty trips: consolidation headroom", """
      SELECT product_type, cab_capacity, count(*) n,
        round(100.0*avg(CASE WHEN emp_actual<=1 THEN 1 ELSE 0 END),2) pct_le1,
        sum(CASE WHEN emp_actual<=1 THEN 1 ELSE 0 END) n_le1,
        round(sum(CASE WHEN emp_actual<=1 THEN traveled_km ELSE 0 END),0) km_le1
      FROM trips WHERE cab_capacity>0 AND emp_actual IS NOT NULL
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY n_le1 DESC LIMIT 25""")
    q("6h. ARTIFACT: are zero-rider trips real? profile them", """
      SELECT CASE WHEN emp_actual=0 THEN 'zero_riders' WHEN emp_actual=1 THEN 'solo' ELSE 'shared' END k,
        count(*) n, round(avg(emp_planned),2) mean_planned, round(avg(noshow),2) mean_noshow,
        round(avg(traveled_km),2) mean_km, round(avg(planned_km),2) mean_planned_km,
        round(100.0*avg(on_time),2) ota,
        round(100.0*avg(CASE WHEN traveled_km=0 THEN 1 ELSE 0 END),2) pct_zero_km
      FROM trips WHERE emp_actual IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("6i. Noshow trend by month", """
      SELECT month, count(*) n, sum(emp_planned) planned, sum(noshow) noshows,
        round(100.0*sum(noshow)/nullif(sum(emp_planned),0),2) noshow_rate_pct,
        round(100.0*avg(CASE WHEN noshow>0 THEN 1 ELSE 0 END),2) pct_trips_with_noshow,
        round(avg(noshow),3) mean_noshow
      FROM trips WHERE emp_planned IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("6j. Noshow by shift_band x month", """
      SELECT shift_band, month, count(*) n, sum(emp_planned) planned, sum(noshow) noshows,
        round(100.0*sum(noshow)/nullif(sum(emp_planned),0),2) noshow_rate_pct
      FROM tb WHERE emp_planned IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")
    q("6k. Noshow by direction x shift_band", """
      SELECT trip_direction, shift_band, count(*) n, sum(emp_planned) planned,
        round(100.0*sum(noshow)/nullif(sum(emp_planned),0),2) noshow_rate_pct
      FROM tb WHERE emp_planned IS NOT NULL GROUP BY 1,2 HAVING count(*)>=500
      ORDER BY noshow_rate_pct DESC""")
    q("6l. Identity check: emp_planned = emp_actual + noshow?", """
      SELECT count(*) n,
        round(100.0*avg(CASE WHEN emp_planned = emp_actual + noshow THEN 1 ELSE 0 END),2) pct_identity_holds,
        round(avg(emp_planned - emp_actual - noshow),4) mean_resid
      FROM trips WHERE emp_planned IS NOT NULL AND emp_actual IS NOT NULL AND noshow IS NOT NULL""")
    q("6m. Noshow by office x month (n>=500)", """
      SELECT office, month, count(*) n, sum(emp_planned) planned,
        round(100.0*sum(noshow)/nullif(sum(emp_planned),0),2) noshow_rate_pct
      FROM trips WHERE emp_planned IS NOT NULL GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")


def stage7():
    add_band()
    q("7a. OTA by riders on board", """
      SELECT emp_actual, count(*) n, round(100.0*avg(on_time),2) ota,
        round(avg(delay_minutes),2) mean_delay, round(avg(traveled_km),2) mean_km,
        round(avg((actual_end_epoch-actual_start_epoch)/60.0),1) mean_dur_min
      FROM trips WHERE emp_actual IS NOT NULL GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")
    q("7b. OTA by seat-fill bucket", """
      SELECT CASE WHEN emp_actual*1.0/cab_capacity<=0.25 THEN 'a. <=25%'
                  WHEN emp_actual*1.0/cab_capacity<=0.50 THEN 'b. 26-50%'
                  WHEN emp_actual*1.0/cab_capacity<=0.75 THEN 'c. 51-75%'
                  WHEN emp_actual*1.0/cab_capacity<=1.00 THEN 'd. 76-100%'
                  ELSE 'e. >100%' END bucket,
        count(*) n, round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay
      FROM trips WHERE cab_capacity>0 AND emp_actual IS NOT NULL GROUP BY 1 ORDER BY 1""")
    q("7c. CONTROLLED: OTA by riders within product_type", """
      SELECT product_type, emp_actual, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE emp_actual IS NOT NULL AND emp_actual<=8
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("7d. CONTROLLED: OTA by riders within shift_band x direction", """
      SELECT shift_band, trip_direction, emp_actual, count(*) n, round(100.0*avg(on_time),2) ota
      FROM tb WHERE emp_actual IS NOT NULL AND emp_actual<=8
      GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY 1,2,3""")
    q("7e. Escort effect by shift_band", """
      SELECT shift_band, actual_escort, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay, round(avg(emp_actual),2) mean_riders
      FROM tb GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("7f. NC flags vs OTA by month", """
      SELECT month, is_driver_nc, is_cab_nc, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY 2,3,1""")
    q("7g. Cab swap vs OTA", """
      SELECT month,
        CASE WHEN planned_cab_registration IS NULL OR actual_cab_registration IS NULL THEN 'null'
             WHEN planned_cab_registration=actual_cab_registration THEN 'same' ELSE 'swapped' END k,
        count(*) n, round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay
      FROM trips GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 2,1""")
    q("7h. Volume/denominator check by month", """
      SELECT month, count(*) n, count(DISTINCT trip_date) n_days,
        round(count(*)*1.0/count(DISTINCT trip_date),0) trips_per_day,
        count(DISTINCT office) offices, count(DISTINCT vendor_id) vendors,
        count(DISTINCT shift_type) shifts, count(DISTINCT actual_cab_registration) cabs
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("7i. Shift_band mix share by month (composition test)", """
      SELECT shift_band,
        round(100.0*sum(CASE WHEN month='2026-05-01' THEN 1 ELSE 0 END)
              /sum(sum(CASE WHEN month='2026-05-01' THEN 1 ELSE 0 END)) OVER (),2) may_share,
        round(100.0*sum(CASE WHEN month='2026-06-01' THEN 1 ELSE 0 END)
              /sum(sum(CASE WHEN month='2026-06-01' THEN 1 ELSE 0 END)) OVER (),2) jun_share,
        round(100.0*sum(CASE WHEN month='2026-07-01' THEN 1 ELSE 0 END)
              /sum(sum(CASE WHEN month='2026-07-01' THEN 1 ELSE 0 END)) OVER (),2) jul_share
      FROM tb GROUP BY 1 ORDER BY 1""")
    q("7j. MIX-ADJUSTED OTA: reweight all months to May's shift_band mix", """
      WITH r AS (SELECT shift_band, month, count(*) n, avg(on_time) ota FROM tb GROUP BY 1,2),
      w AS (SELECT shift_band, n AS w_may FROM r WHERE month='2026-05-01')
      SELECT r.month, round(100.0*sum(r.ota*w.w_may)/sum(w.w_may),2) mix_adj_ota,
             round(100.0*sum(r.ota*r.n)/sum(r.n),2) raw_ota
      FROM r JOIN w USING(shift_band) GROUP BY 1 ORDER BY 1""")
    q("7k. MIX-ADJUSTED OTA on full shift_type (100 cells)", """
      WITH r AS (SELECT shift_type, month, count(*) n, avg(on_time) ota FROM trips GROUP BY 1,2),
      w AS (SELECT shift_type, n AS w_may FROM r WHERE month='2026-05-01')
      SELECT r.month, round(100.0*sum(r.ota*w.w_may)/sum(w.w_may),2) mix_adj_ota,
             round(100.0*sum(r.ota*r.n)/sum(r.n),2) raw_ota
      FROM r JOIN w USING(shift_type) GROUP BY 1 ORDER BY 1""")
    q("7l. Occupancy x OTA within cab_capacity=4 only (tight control)", """
      SELECT emp_actual, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay, round(avg(traveled_km),2) mean_km
      FROM trips WHERE cab_capacity=4 AND emp_actual IS NOT NULL
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")


def stage8():
    """DIAGNOSTICS: what does delay_minutes actually measure? + artifact checks."""
    add_band()
    q("8a. Joint dist: delay_minutes=0 trips - what is their end deviation?", """
      SELECT CASE WHEN delay_minutes=0 THEN 'delay=0' WHEN delay_minutes>0 THEN 'delay>0' ELSE 'delay<0' END k,
        count(*) n,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.10),2) p10_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.50),2) p50_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.90),2) p90_end_dev,
        round(100.0*avg(CASE WHEN actual_end_epoch>planned_end_epoch THEN 1 ELSE 0 END),2) pct_arrived_after_plan
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("8b. Is delay = greatest(0, start_dev)? test all candidate definitions", """
      WITH d AS (SELECT delay_minutes dm,
          (actual_start_epoch-planned_start_epoch)/60.0 sdev,
          (actual_end_epoch-planned_end_epoch)/60.0 edev,
          (actual_end_epoch-actual_start_epoch)/60.0-(planned_end_epoch-planned_start_epoch)/60.0 ddev
        FROM trips)
      SELECT
        round(100.0*avg(CASE WHEN abs(dm-greatest(0,edev))<0.51 THEN 1 ELSE 0 END),2) pct_eq_max0_enddev,
        round(100.0*avg(CASE WHEN abs(dm-greatest(0,sdev))<0.51 THEN 1 ELSE 0 END),2) pct_eq_max0_startdev,
        round(100.0*avg(CASE WHEN abs(dm-greatest(0,ddev))<0.51 THEN 1 ELSE 0 END),2) pct_eq_max0_durdev,
        round(corr(dm, greatest(0,edev)),4) corr_max0_enddev,
        round(corr(dm, greatest(0,sdev)),4) corr_max0_startdev
      FROM d""")
    q("8c. *** THE BLIND SPOT: trips arriving >5min after planned end but recorded delay<=5 ***", """
      SELECT month, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        sum(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0>5 AND on_time=1 THEN 1 ELSE 0 END) n_hidden_late,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0>5 AND on_time=1 THEN 1 ELSE 0 END),2) pct_hidden_late
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("8d. Hidden-late trips: who are they? by product/direction/shift_band", """
      SELECT product_type, trip_direction, shift_band, count(*) n,
        sum(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0>5 AND on_time=1 THEN 1 ELSE 0 END) n_hidden,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0>5 AND on_time=1 THEN 1 ELSE 0 END),2) pct_hidden,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota
      FROM tb GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY pct_hidden DESC LIMIT 30""")
    q("8e. :15/:16 group - reported vs epoch OTA (verify the 100% claim)", """
      SELECT CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 'odd_min_15_16' ELSE 'normal' END grp,
        count(*) n, round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev,
        round(avg((actual_start_epoch-planned_start_epoch)/60.0),2) mean_start_dev
      FROM trips GROUP BY 1""")
    q("8f. :16 shifts: which direction/product/office", """
      SELECT split_part(shift_type,':',2) mm, trip_direction, product_type, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota
      FROM trips WHERE split_part(shift_type,':',2) IN ('15','16')
      GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY n DESC""")
    q("8g. ARTIFACT: SPOT_2.0 aggregate - real product or open-ended rental?", """
      SELECT product_type, count(*) n, round(100.0*avg(on_time),2) ota,
        round(avg(delay_minutes),1) mean_delay, round(quantile_cont(delay_minutes,0.5),1) p50_delay,
        round(avg((planned_end_epoch-planned_start_epoch)/60.0),1) mean_planned_dur,
        round(avg((actual_end_epoch-actual_start_epoch)/60.0),1) mean_actual_dur,
        round(avg(traveled_km),2) mean_km, round(avg(emp_actual),2) mean_riders,
        count(DISTINCT office) offices, count(DISTINCT vendor_id) vendors
      FROM trips GROUP BY 1 ORDER BY n DESC""")
    q("8h. SPOT_2.0 share of all delay minutes", """
      SELECT product_type, count(*) n,
        round(100.0*count(*)/sum(count(*)) OVER (),3) pct_of_trips,
        round(sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END),0) delay_min,
        round(100.0*sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END)
              /sum(sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END)) OVER (),2) pct_of_delay_min
      FROM trips GROUP BY 1 ORDER BY pct_of_delay_min DESC""")
    q("8i. Delay concentration EXCLUDING SPOT_2.0 (is the 37% just SPOT?)", """
      WITH r AS (SELECT delay_minutes, ntile(1000) OVER (ORDER BY delay_minutes DESC) b
                 FROM trips WHERE delay_minutes>0 AND product_type<>'SPOT_2.0')
      SELECT count(*) n, round(sum(delay_minutes),0) total,
        round(100.0*sum(CASE WHEN b<=10 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_1pct,
        round(100.0*sum(CASE WHEN b<=50 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_5pct
      FROM r""")
    q("8j. *** LOGIN vs LOGOUT: occupancy effect on OTA (CAB only, weekday) ***", """
      SELECT trip_direction, emp_actual, count(*) n, round(100.0*avg(on_time),2) ota,
             round(avg(delay_minutes),2) mean_delay,
             round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev
      FROM trips WHERE product_type='CAB' AND dow_n<=5 AND emp_actual<=6
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("8k. LOGIN occupancy effect WITHIN a single office+shift_band (tightest control)", """
      SELECT office, emp_actual, count(*) n, round(100.0*avg(on_time),2) ota
      FROM tb WHERE trip_direction='LOGIN' AND product_type='CAB'
        AND shift_band='10:00-15:59' AND emp_actual<=6
      GROUP BY 1,2 HAVING count(*)>=500 ORDER BY 1,2""")
    q("8l. ARTIFACT: escort trips - are they a different population?", """
      SELECT actual_escort, count(*) n, round(100.0*avg(on_time),2) ota,
        round(avg(emp_actual),2) mean_riders, round(avg(traveled_km),2) mean_km,
        count(DISTINCT office) offices,
        round(100.0*avg(CASE WHEN trip_direction='LOGOUT' THEN 1 ELSE 0 END),2) pct_logout,
        round(100.0*avg(CASE WHEN split_part(shift_type,':',2) IN ('15','16') THEN 1 ELSE 0 END),2) pct_odd_shift
      FROM trips GROUP BY 1""")
    q("8m. Escort effect controlled for direction+shift_band+product", """
      SELECT shift_band, trip_direction, actual_escort, count(*) n, round(100.0*avg(on_time),2) ota
      FROM tb WHERE product_type='CAB' GROUP BY 1,2,3 HAVING count(*)>=500 ORDER BY 1,2,3""")
    q("8n. ARTIFACT: cab-swap trips only in July - what are they?", """
      SELECT month, product_type, route_source, shift_type, count(*) n,
        round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),1) mean_delay
      FROM trips WHERE planned_cab_registration<>actual_cab_registration
      GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 15""")
    q("8o. ARTIFACT: route_source SHUTTLE_SERVICE only in July? no HAVING filter", """
      SELECT route_source, month, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1,2 ORDER BY 1,2""")
    q("8p. Identity violations: emp_planned vs emp_actual+noshow", """
      SELECT CASE WHEN emp_planned = emp_actual+noshow THEN 'exact'
                  WHEN emp_actual+noshow > emp_planned THEN 'actual+noshow > planned'
                  ELSE 'actual+noshow < planned' END k,
        count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct,
        round(avg(emp_planned),2) mean_planned, round(avg(emp_actual),2) mean_actual,
        round(avg(noshow),2) mean_noshow
      FROM trips GROUP BY 1 ORDER BY n DESC""")
    q("8q. *** MINUTES-LOST per trip: is June really worse? ***", """
      SELECT month, count(*) n,
        round(100.0*avg(on_time),2) ota,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/count(*),3) sla_min_lost_per_trip,
        round(sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END)/count(*),3) delay_min_per_trip,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/60.0,0) hrs_beyond_sla,
        round(sum(CASE WHEN delay_minutes>5 THEN (delay_minutes-5)*emp_actual ELSE 0 END)/60.0,0) employee_hrs_lost,
        round(sum(CASE WHEN delay_minutes>5 THEN (delay_minutes-5)*emp_actual ELSE 0 END)/sum(emp_actual),3) emp_min_lost_per_seat
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("8r. Same, EXCLUDING SPOT_2.0 (remove the outlier product)", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) ota,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/count(*),3) sla_min_lost_per_trip,
        round(sum(CASE WHEN delay_minutes>5 THEN (delay_minutes-5)*emp_actual ELSE 0 END)/sum(emp_actual),3) emp_min_lost_per_seat
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1 ORDER BY 1""")
    q("8s. ISO week: OTA vs minutes-lost-per-trip (divergence check)", """
      SELECT weekofyear(trip_date) iso_wk, min(trip_date) wk_start, count(*) n,
        round(100.0*avg(on_time),2) ota,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/count(*),3) sla_min_per_trip
      FROM trips GROUP BY 1 ORDER BY 1""")
    q("8t. Solo trips: planned solo vs became solo (noshow)", """
      SELECT CASE WHEN emp_actual=1 AND emp_planned=1 THEN 'planned solo'
                  WHEN emp_actual=1 AND emp_planned>1 THEN 'became solo (noshow)'
                  ELSE 'shared' END k,
        count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct,
        round(sum(traveled_km),0) total_km, round(avg(traveled_km),2) mean_km,
        round(avg(cab_capacity),2) mean_cap, round(100.0*avg(on_time),2) ota
      FROM trips GROUP BY 1 ORDER BY n DESC""")
    q("8u. Planned-solo trips by office x month (where is the rostering waste?)", """
      SELECT office, month, count(*) n,
        sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END) n_planned_solo,
        round(100.0*avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
        round(sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN traveled_km ELSE 0 END),0) km_planned_solo
      FROM trips GROUP BY 1,2 HAVING count(*)>=500 ORDER BY pct_planned_solo DESC LIMIT 20""")
    q("8v. Weekday Tuesday-vs-Friday gap: consistent across all 3 months + offices?", """
      SELECT office, dow, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow IN ('Tuesday','Friday') GROUP BY 1,2
      HAVING count(*)>=500 ORDER BY 1,2""")
    q("8w. Volume by DOW: is Tuesday just the busiest day? (load hypothesis)", """
      SELECT dow_n, dow, count(*) n, round(count(*)/count(DISTINCT trip_date),0) trips_per_day,
        round(100.0*avg(on_time),2) ota,
        round(avg(emp_actual),2) mean_riders,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/count(*),3) sla_min_per_trip
      FROM trips GROUP BY 1,2 ORDER BY 1""")
    q("8x. LOGIN-band load: trips per day by shift_band x dow (peak crunch)", """
      SELECT shift_band, dow, round(count(*)/count(DISTINCT trip_date),0) trips_per_day,
             count(*) n, round(100.0*avg(on_time),2) ota
      FROM tb WHERE dow IN ('Tuesday','Friday') GROUP BY 1,2 ORDER BY 1,2""")


def stage9():
    """Nail the metric definition; test load hypothesis; final artifact sweeps."""
    add_band()
    q("9a. *** METRIC DEFINITION by direction: which epoch does delay track? ***", """
      WITH d AS (SELECT trip_direction dir, delay_minutes dm,
          (actual_start_epoch-planned_start_epoch)/60.0 sdev,
          (actual_end_epoch-planned_end_epoch)/60.0 edev
        FROM trips WHERE product_type<>'SPOT_2.0')
      SELECT dir, count(*) n,
        round(100.0*avg(CASE WHEN abs(dm-greatest(0,edev))<0.51 THEN 1 ELSE 0 END),2) pct_matches_END,
        round(100.0*avg(CASE WHEN abs(dm-greatest(0,sdev))<0.51 THEN 1 ELSE 0 END),2) pct_matches_START,
        round(corr(dm,greatest(0,edev)),4) corr_END,
        round(corr(dm,greatest(0,sdev)),4) corr_START
      FROM d GROUP BY 1 ORDER BY 1""")
    q("9b. *** LOGOUT last-passenger burden: end_dev by riders ***", """
      SELECT emp_actual, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.5),2) p50_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.9),2) p90_end_dev,
        round(avg((actual_end_epoch-actual_start_epoch)/60.0),1) mean_ride_min
      FROM trips WHERE trip_direction='LOGOUT' AND product_type='CAB' AND emp_actual<=6
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")
    q("9c. LOGIN mirror: end_dev by riders (does the same pattern hold?)", """
      SELECT emp_actual, count(*) n, round(100.0*avg(on_time),2) reported_ota,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev,
        round(avg((actual_end_epoch-actual_start_epoch)/60.0),1) mean_ride_min
      FROM trips WHERE trip_direction='LOGIN' AND product_type='CAB' AND emp_actual<=6
      GROUP BY 1 HAVING count(*)>=500 ORDER BY 1""")
    q("9d. Employee-minutes in-cab beyond plan, by direction (the real cost)", """
      SELECT trip_direction, month, count(*) n,
        round(sum(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)*emp_actual)/60.0,0) emp_hrs_beyond_plan,
        round(sum(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)*emp_actual)/sum(emp_actual),2) min_per_seat,
        round(100.0*avg(on_time),2) reported_ota
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1,2 ORDER BY 1,2""")
    q("9e. *** LOAD TEST: daily trips vs daily OTA, per office (weekdays only) ***", """
      WITH d AS (SELECT office, trip_date, count(*) n, 100.0*avg(on_time) ota
                 FROM trips WHERE dow_n<=5 GROUP BY 1,2)
      SELECT office, count(*) n_days, round(avg(n),0) mean_trips_day,
             round(corr(n, ota),3) corr_load_vs_ota
      FROM d GROUP BY 1 HAVING count(*)>=60 ORDER BY corr_load_vs_ota""")
    q("9f. LOAD TEST global: decile of daily office-load vs OTA", """
      WITH d AS (SELECT office, trip_date, count(*) n, avg(on_time) ota
                 FROM trips WHERE dow_n<=5 GROUP BY 1,2),
      r AS (SELECT *, ntile(5) OVER (PARTITION BY office ORDER BY n) q FROM d)
      SELECT q AS load_quintile_within_office, count(*) n_office_days,
             round(avg(n),0) mean_trips, round(100.0*sum(ota*n)/sum(n),2) ota
      FROM r GROUP BY 1 ORDER BY 1""")
    q("9g. Friday effect: is it lower load or different riders?", """
      SELECT dow, count(*) n, round(count(*)/count(DISTINCT trip_date),0) trips_day,
        round(avg(emp_actual),3) mean_riders,
        round(sum(emp_actual)/count(DISTINCT trip_date),0) seats_day,
        round(100.0*avg(CASE WHEN trip_direction='LOGIN' THEN 1 ELSE 0 END),2) pct_login,
        round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow_n<=5 GROUP BY 1 ORDER BY trips_day DESC""")
    q("9h. Tuesday-vs-Friday gap holds within LOGIN 10:00-15:59 CAB only?", """
      SELECT dow, count(*) n, round(count(*)/count(DISTINCT trip_date),0) trips_day,
             round(100.0*avg(on_time),2) ota, round(avg(delay_minutes),2) mean_delay
      FROM tb WHERE dow_n<=5 AND trip_direction='LOGIN' AND shift_band='10:00-15:59'
      GROUP BY 1 ORDER BY trips_day DESC""")
    q("9i. June dip: LOGIN vs LOGOUT x shift_band (localize precisely)", """
      WITH m AS (SELECT shift_band, trip_direction, month, count(*) n, 100.0*avg(on_time) ota
                 FROM tb GROUP BY 1,2,3)
      SELECT shift_band, trip_direction,
        max(CASE WHEN month='2026-05-01' THEN n END) n_may,
        max(CASE WHEN month='2026-06-01' THEN n END) n_jun,
        round(max(CASE WHEN month='2026-05-01' THEN ota END),2) may,
        round(max(CASE WHEN month='2026-06-01' THEN ota END),2) jun,
        round(max(CASE WHEN month='2026-07-01' THEN ota END),2) jul,
        round(max(CASE WHEN month='2026-06-01' THEN ota END)-max(CASE WHEN month='2026-05-01' THEN ota END),2) d_jun
      FROM m GROUP BY 1,2
      HAVING max(CASE WHEN month='2026-05-01' THEN n END)>=500
         AND max(CASE WHEN month='2026-06-01' THEN n END)>=500
      ORDER BY d_jun""")
    q("9j. Week-23 (June 1-7) deep dive: which office x band collapsed?", """
      SELECT office, shift_band, count(*) n,
        round(100.0*avg(CASE WHEN weekofyear(trip_date)=23 THEN on_time END),2) wk23_ota,
        sum(CASE WHEN weekofyear(trip_date)=23 THEN 1 ELSE 0 END) n_wk23,
        round(100.0*avg(CASE WHEN weekofyear(trip_date) IN (19,20) THEN on_time END),2) wk19_20_ota,
        sum(CASE WHEN weekofyear(trip_date) IN (19,20) THEN 1 ELSE 0 END) n_wk19_20
      FROM tb GROUP BY 1,2
      HAVING sum(CASE WHEN weekofyear(trip_date)=23 THEN 1 ELSE 0 END)>=500
      ORDER BY (100.0*avg(CASE WHEN weekofyear(trip_date)=23 THEN on_time END)
               -100.0*avg(CASE WHEN weekofyear(trip_date) IN (19,20) THEN on_time END)) ASC LIMIT 20""")
    q("9k. ARTIFACT: planned-solo - is it a small-cab-fleet constraint by office?", """
      SELECT office, count(*) n,
        round(avg(cab_capacity),2) mean_cap,
        round(100.0*avg(CASE WHEN cab_capacity=3 THEN 1 ELSE 0 END),2) pct_cap3,
        round(100.0*avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
        round(avg(traveled_km),2) mean_km,
        round(avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN traveled_km END),2) mean_km_solo,
        count(DISTINCT actual_cab_registration) cabs
      FROM trips GROUP BY 1 HAVING count(*)>=500 ORDER BY pct_planned_solo DESC""")
    q("9l. Planned-solo: LOGIN or LOGOUT? and which shift_band?", """
      SELECT trip_direction, shift_band, count(*) n,
        round(100.0*avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
        sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END) n_solo
      FROM tb GROUP BY 1,2 HAVING count(*)>=500 ORDER BY n_solo DESC LIMIT 15""")
    q("9m. FINAL: reported OTA vs epoch-OTA by office x month (scorecard)", """
      SELECT office, month, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        round(100.0*avg(on_time)-100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) gap
      FROM trips GROUP BY 1,2 HAVING count(*)>=500 ORDER BY gap DESC LIMIT 25""")
    q("9n. Does epoch-OTA reproduce the June dip? (metric-independent confirmation)", """
      SELECT month, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1 ORDER BY 1""")
    q("9o. ISO-week epoch-OTA (does the 5-week slide show in epochs too?)", """
      SELECT weekofyear(trip_date) iso_wk, min(trip_date) wk_start, count(*) n,
        round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota
      FROM trips WHERE product_type<>'SPOT_2.0' GROUP BY 1 ORDER BY 1""")


def stage10():
    """Final confirmations for every number cited in the writeup."""
    add_band()
    q("10a. CONTROLLED COMPARISON: 3 pinnacle-Slc offices, same cap-3 fleet", """
      SELECT business_unit, office, count(*) n,
        round(100.0*avg(CASE WHEN cab_capacity=3 THEN 1 ELSE 0 END),2) pct_cap3,
        round(100.0*avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END),2) pct_planned_solo,
        round(avg(emp_planned),2) mean_planned, round(avg(traveled_km),2) mean_km,
        round(sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN traveled_km ELSE 0 END),0) solo_km,
        round(100.0*sum(emp_actual)/sum(cab_capacity),2) seat_fill
      FROM trips WHERE office IN ('Oakmont Office','Willow Bend Campus','Clearwater Campus')
      GROUP BY 1,2 ORDER BY pct_planned_solo DESC""")
    q("10b. Consolidation sizing: Oakmont+Willow Bend solo trips at Clearwater's rate", """
      SELECT count(*) n_trips,
        sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END) n_solo,
        round(100.0*avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END),2) pct_solo,
        round(count(*)*0.1929,0) n_solo_at_clearwater_rate,
        round(sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END)-count(*)*0.1929,0) excess_solo_trips,
        round(avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN traveled_km END),2) mean_solo_km,
        round((sum(CASE WHEN emp_actual=1 AND emp_planned=1 THEN 1 ELSE 0 END)-count(*)*0.1929)
              *avg(CASE WHEN emp_actual=1 AND emp_planned=1 THEN traveled_km END),0) excess_solo_km_3mo
      FROM trips WHERE office IN ('Oakmont Office','Willow Bend Campus')""")
    q("10c. SHUTTLE_SERVICE July reclassification: by office", """
      SELECT office, month, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE route_source IN ('SHUTTLE_SERVICE','MANUAL')
      GROUP BY 1,2 ORDER BY 1,2""")
    q("10d. MANUAL vs SHUTTLE July split within Denver (the swap)", """
      SELECT month, route_source, product_type, count(*) n, round(100.0*avg(on_time),2) ota
      FROM trips WHERE office='Denver Office' AND route_source IN ('MANUAL','SHUTTLE_SERVICE')
      GROUP BY 1,2,3 ORDER BY 2,1""")
    q("10e. HEADLINE: CAB LOGOUT evening blind spot, by month", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) reported_ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_dev,
        round(quantile_cont((actual_end_epoch-planned_end_epoch)/60.0,0.9),1) p90_end_dev,
        round(sum(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)*emp_actual)/60.0,0) emp_hrs_beyond_plan
      FROM tb WHERE product_type='CAB' AND trip_direction='LOGOUT' AND shift_band='16:00-20:59'
      GROUP BY 1 ORDER BY 1""")
    q("10f. Total employee-hours beyond plan, all trips ex-SPOT, 3 months", """
      SELECT count(*) n,
        round(sum(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)*emp_actual)/60.0,0) emp_hrs_beyond_plan,
        round(sum(greatest(0,(actual_end_epoch-planned_end_epoch)/60.0)*emp_actual)/sum(emp_actual),2) min_per_seat,
        sum(emp_actual) seats
      FROM trips WHERE product_type<>'SPOT_2.0'""")
    q("10g. Tuesday/Friday load gap by month (is it stable, not a June effect?)", """
      SELECT month, dow, count(*) n, round(count(*)/count(DISTINCT trip_date),0) trips_day,
             round(100.0*avg(on_time),2) ota
      FROM trips WHERE dow IN ('Tuesday','Friday') GROUP BY 1,2 ORDER BY 2,1""")
    q("10h. SPOT_2.0 full profile for the writeup", """
      SELECT month, count(*) n, round(100.0*avg(on_time),2) ota,
        round(avg(delay_minutes),1) mean_delay, round(max(delay_minutes),0) max_delay,
        round(avg((planned_end_epoch-planned_start_epoch)/60.0),1) planned_dur,
        round(avg((actual_end_epoch-actual_start_epoch)/60.0),1) actual_dur,
        round(sum(CASE WHEN delay_minutes>0 THEN delay_minutes ELSE 0 END),0) delay_min
      FROM trips WHERE product_type='SPOT_2.0' GROUP BY 1 ORDER BY 1""")
    q("10i. Delay concentration: with vs without SPOT_2.0 side by side", """
      WITH a AS (SELECT 'ALL trips' k, delay_minutes,
                   ntile(1000) OVER (ORDER BY delay_minutes DESC) b
                 FROM trips WHERE delay_minutes>0),
      c AS (SELECT 'EXCL SPOT_2.0' k, delay_minutes,
                   ntile(1000) OVER (ORDER BY delay_minutes DESC) b
                 FROM trips WHERE delay_minutes>0 AND product_type<>'SPOT_2.0'),
      u AS (SELECT * FROM a UNION ALL SELECT * FROM c)
      SELECT k, count(*) n, round(sum(delay_minutes),0) total_delay_min,
        round(100.0*sum(CASE WHEN b<=10 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_1pct,
        round(100.0*sum(CASE WHEN b<=50 THEN delay_minutes ELSE 0 END)/sum(delay_minutes),2) pct_worst_5pct
      FROM u GROUP BY 1 ORDER BY 1""")
    q("10j. Shift-band structural ranking, ex-SPOT, ex-:15/:16 (clean OTA table)", """
      SELECT shift_band, count(*) n, round(100.0*avg(on_time),2) ota,
        round(100.0*avg(CASE WHEN (actual_end_epoch-planned_end_epoch)/60.0<=5 THEN 1 ELSE 0 END),2) epoch_ota,
        round(sum(CASE WHEN delay_minutes>5 THEN delay_minutes-5 ELSE 0 END)/count(*),3) sla_min_per_trip
      FROM tb WHERE product_type<>'SPOT_2.0' AND split_part(shift_type,':',2) NOT IN ('15','16')
      GROUP BY 1 ORDER BY ota""")
    q("10k. Noshow: LOGIN 10:00-15:59 detail by month (the worst cell)", """
      SELECT month, count(*) n, sum(emp_planned) planned, sum(noshow) noshows,
        round(100.0*sum(noshow)/sum(emp_planned),2) noshow_rate
      FROM tb WHERE trip_direction='LOGIN' AND shift_band='10:00-15:59' GROUP BY 1 ORDER BY 1""")
    q("10l. Noshow wasted seat-km (seats booked, not used)", """
      SELECT month, count(*) n, sum(noshow) noshows,
        round(sum(noshow*traveled_km),0) wasted_seat_km,
        round(100.0*sum(noshow)/sum(emp_planned),2) noshow_rate
      FROM trips GROUP BY 1 ORDER BY 1""")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "0"
    {"0": build, "1": stage1, "2": stage2, "3": stage3, "4": stage4, "5": stage5,
     "6": stage6, "7": stage7, "8": stage8, "9": stage9, "10": stage10}[stage]()
