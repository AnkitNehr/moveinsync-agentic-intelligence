import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()

print("="*100); print("SECTION 4b: follow-ups (ghost trips / negative cost)")
show(c,"""select min(emp_actual) mn, max(emp_actual) mx, count(*) filter (where emp_actual is null) n_null,
 count(*) filter (where emp_actual=0) zeros, count(*) n from trips""","emp_actual range - why 0 ghost trips")
show(c,"""select count(*) n, round(sum(trip_cost),0) tot, round(min(trip_cost),2) mn from bill where trip_cost<0""","NEGATIVE trip_cost in bill")
show(c,"""select contract, count(*) n, round(sum(trip_cost),0) tot, round(avg(trip_cost),2) avg from bill where trip_cost<0 group by 1 order by 3 limit 10""","negative cost by contract")
show(c,"""select business_unit, vendor, count(*) n, round(sum(trip_cost),0) tot from bill where trip_cost<0 group by 1,2 order by 4 limit 10""","negative cost by vendor")
show(c,"""select contract, count(*) n, round(sum(trip_cost),0) tot, round(avg(trip_cost),2) avgc,
 count(*) filter (where trip_cost<0) n_neg, count(*) filter (where trip_cost>0) n_pos
 from bill where contract='6S-PREMIUMNEW' group by 1""","6S-PREMIUMNEW breakdown")

print("="*100); print("SECTION 6: RIDER-LEVEL JUNE STORY (emp_data, independent of ride_data)")
show(c,"""select min(planned_pickup_epoch) mn, max(planned_pickup_epoch) mx,
 count(*) filter (where planned_pickup_epoch is null) p_null,
 count(*) filter (where actual_pickup_epoch is null) a_null, count(*) n from emp""","epoch sanity")
c.sql("""CREATE OR REPLACE VIEW empd AS select *,
 (actual_pickup_epoch-planned_pickup_epoch)/60.0 AS pickup_delay_min,
 case when (actual_pickup_epoch-planned_pickup_epoch)/60.0 <= 5 then 1 else 0 end AS pu_ontime
 from emp where actual_pickup_epoch is not null and planned_pickup_epoch is not null""")
show(c,"""select count(*) n, round(min(pickup_delay_min),1) p1, round(median(pickup_delay_min),2) med,
 round(avg(pickup_delay_min),2) avg, round(max(pickup_delay_min),1) mx,
 round(quantile_cont(pickup_delay_min,0.99),1) p99 from empd""","pickup delay distribution")
show(c,"""select month, count(*) n_riders, round(100.0*avg(pu_ontime),2) rider_pickup_ota,
 round(avg(pickup_delay_min),2) avg_delay, round(median(pickup_delay_min),2) med_delay
 from empd group by 1 order by 1""","RIDER-LEVEL pickup OTA by month (compare to trip OTA 95.31/92.46/94.69)")
show(c,"""select business_unit, month, count(*) n, round(100.0*avg(pu_ontime),2) ota from empd
 group by 1,2 having count(*)>=1000 order by 1,2""","rider pickup OTA by BU x month")
show(c,"""select business_unit, office,
 round(100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) may,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01'),2) jun,
 round(100.0*avg(pu_ontime) filter (where month='2026-07-01'),2) jul,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01')-100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) jun_swing,
 count(*) filter (where month='2026-06-01') n_jun
 from empd group by 1,2 having count(*) filter (where month='2026-06-01')>=1000 order by 6""","rider pickup OTA: June swing by office (compare A: Denver -4.15, Clearwater -4.07)")
show(c,"""select shift_type,
 round(100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) may,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01'),2) jun,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01')-100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) swing,
 count(*) filter (where month='2026-06-01') n_jun
 from empd group by 1 having count(*) filter (where month='2026-06-01')>=2000 order by 4 limit 12""","rider pickup June swing by shift")
show(c,"""select product_type,
 round(100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) may,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01'),2) jun,
 round(100.0*avg(pu_ontime) filter (where month='2026-07-01'),2) jul,
 round(100.0*avg(pu_ontime) filter (where month='2026-06-01')-100.0*avg(pu_ontime) filter (where month='2026-05-01'),2) swing,
 count(*) filter (where month='2026-06-01') n_jun
 from empd group by 1 having count(*) filter (where month='2026-06-01')>=1000 order by 5""","rider pickup June swing by product_type (A said BUS -6.25 vs CAB -2.20)")
# does rider-level agree with trip-level on the SAME trips?
show(c,"""select t.month, count(*) n_trips,
 round(100.0*avg(t.on_time),2) trip_ota,
 round(100.0*avg(e.pu_ontime),2) rider_pickup_ota,
 round(corr(t.delay_minutes, e.mean_pu),3) corr_tripdelay_riderdelay
 from trips t join (select trip_id, business_unit, avg(pu_ontime) pu_ontime, avg(pickup_delay_min) mean_pu
                    from empd group by 1,2) e using(trip_id,business_unit)
 group by 1 order by 1""","trip-level vs rider-level on same trips + correlation")

print("="*100); print("SECTION 7: VENDOR SCORECARD")
show(c,"""select count(distinct vendor_id) trips_vendors, count(distinct vendor) bill_vendors from trips, (select distinct vendor from bill)""","vendor id spaces")
show(c,"""select t.vendor_id, b.vendor, count(*) n from trips t join bill b using(trip_id,business_unit)
 group by 1,2 order by 3 desc limit 8""","do vendor_id and bill.vendor agree?")
