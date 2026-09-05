import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()

print("="*100); print("SECTION 1d: delay_minutes is NOT derived from epochs - prove it")
show(c,"""select count(*) n,
 round(avg(abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)),2) vs_END,
 round(avg(abs(delay_minutes-(actual_start_epoch-planned_start_epoch)/60.0)),2) vs_START,
 round(avg((actual_end_epoch-planned_end_epoch)/60.0),2) mean_end_late,
 round(avg((actual_start_epoch-planned_start_epoch)/60.0),2) mean_start_late
 from (select TRY_CAST(replace(delay_minutes,',','') as double) delay_minutes,
   TRY_CAST(replace(actual_end_epoch,',','') as bigint) actual_end_epoch,
   TRY_CAST(replace(planned_end_epoch,',','') as bigint) planned_end_epoch,
   TRY_CAST(replace(actual_start_epoch,',','') as bigint) actual_start_epoch,
   TRY_CAST(replace(planned_start_epoch,',','') as bigint) planned_start_epoch
  from read_csv('/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw/Ride_data*.csv',header=true,union_by_name=true,
   null_padding=true,ignore_errors=true,all_varchar=true,sample_size=-1))
 where delay_minutes is not null and actual_end_epoch is not null""","delay_minutes vs both epoch pairs")
# independent OTA from epochs
c.sql("""CREATE OR REPLACE VIEW t2 AS select *, (actual_end_epoch-planned_end_epoch)/60.0 end_late,
 case when (actual_end_epoch-planned_end_epoch)/60.0<=5 then 1 else 0 end end_ontime from trips
 where actual_end_epoch is not null and planned_end_epoch is not null""")
show(c,"""select month, count(*) n, round(100.0*avg(on_time),2) reported_ota,
 round(100.0*avg(end_ontime),2) epoch_derived_ota, round(median(end_late),2) med_end_late
 from t2 group by 1 order by 1""","REPORTED OTA vs EPOCH-DERIVED OTA by month")
show(c,"""select delay_reason, count(*) n, round(100.0*avg(end_ontime),2) epoch_ota, round(avg(end_late),2) mean_end_late,
 round(avg(delay_minutes),2) reported_delay from t2 group by 1 order by 1""","epoch lateness by reported delay_reason")

print("="*100); print("SECTION 7b: VENDOR SCORECARD ARTIFACT CHECKS")
c.sql("""CREATE OR REPLACE VIEW trip_alert AS select trip_id,business_unit,count(*) n_alerts from alerts where trip_id is not null group by 1,2""")
c.sql("""CREATE OR REPLACE VIEW fb_trip AS select trip_id,business_unit, count(*) n_fb,
 count(*) filter (where driver_rating<=3) n_det, avg(driver_rating) dr from fb group by 1,2""")
c.sql("""CREATE OR REPLACE VIEW vs AS
 select t.vendor_id, t.trip_id, t.business_unit, t.month, t.office, t.on_time, t.product_type,
  t.emp_actual, t.cab_capacity, b.contract, b.trip_cost,
  coalesce(a.n_alerts,0) n_alerts, coalesce(f.n_fb,0) n_fb, coalesce(f.n_det,0) n_det, f.dr
 from trips t join bill b using(trip_id,business_unit)
 left join trip_alert a using(trip_id,business_unit) left join fb_trip f using(trip_id,business_unit)
 where b.trip_cost>=0""")
show(c,"""select vendor_id, count(*) n_trips,
 round(100.0*count(*) filter (where n_fb>0)/count(*),2) fb_coverage_pct,
 round(100.0*sum(n_det)/nullif(sum(n_fb),0),3) pct_detractor, sum(n_fb) n_ratings
 from vs group by 1 having count(*)>=1000 order by 3""","FEEDBACK COVERAGE vs detractor rate (selection bias?)")
show(c,"""select round(corr(fb_coverage_pct, pct_detractor),3) corr_coverage_detractor from
 (select vendor_id, 100.0*count(*) filter (where n_fb>0)/count(*) fb_coverage_pct,
  100.0*sum(n_det)/nullif(sum(n_fb),0) pct_detractor from vs group by 1 having count(*)>=1000)""","correlation: coverage vs detractor rate")
# Meera Lebedev drill-down
show(c,"""select month, count(*) n, round(100.0*avg(on_time),2) ota, contract, office,
 round(avg(emp_actual),2) riders, round(avg(cab_capacity),2) cap, round(sum(trip_cost),0) spend
 from vs where vendor_id='Meera Lebedev Travel' group by 1,4,5 order by 1,2 desc""","Meera Lebedev Travel drill-down")
show(c,"""select vendor_id, count(*) n, round(100.0*avg(on_time),2) ota from vs
 where business_unit='vanta-Sea' and contract='6S-PREMIUMNEW' group by 1 order by 2 desc""","peers on the SAME contract as Meera Lebedev")
show(c,"""select v.vendor_id, count(*) n, round(100.0*avg(v.on_time),2) ota_vendor,
 round(100.0*avg(pb.peer_ota),2) peer_ota_same_office_month,
 round(100.0*avg(v.on_time)-100.0*avg(pb.peer_ota),2) ota_gap
 from vs v join (select office,month,avg(on_time) peer_ota from vs group by 1,2 having count(*)>=500) pb
 using(office,month) group by 1 having count(*)>=1000 order by 5""","OTA GAP vs same office+month peers (removes route-mix confound)")

print("="*100); print("SECTION 3d: WTA exact significance")
show(c,"""select count(*) n_ratings, count(*) filter (where f.safety_rating<=3) n_detractors,
 round(avg(f.safety_rating),4) safety
 from fb f join alerts a on f.trip_id=a.trip_id and f.business_unit=a.business_unit and f.stwid=a.stwid
 where a.event_type='WOMAN_TRAVELLING_ALONE'""","WTA: flagged rider exact counts")
show(c,"""select count(*) n_ratings, count(*) filter (where safety_rating<=3) n_detractors from fb""","baseline exact counts")
show(c,"""select f.business_unit bu, count(*) n, count(*) filter (where f.safety_rating<=3) det, round(avg(f.safety_rating),3) safety
 from fb f join alerts a on f.trip_id=a.trip_id and f.business_unit=a.business_unit and f.stwid=a.stwid
 where a.event_type='WOMAN_TRAVELLING_ALONE' group by 1 order by 2 desc""","WTA detractors by BU (is it one BU?)")
show(c,"""select a.event_type, count(distinct a.stwid) riders, count(*) alerts,
 round(count(*)*1.0/count(distinct a.stwid),2) alerts_per_rider from alerts a
 where a.event_type='WOMAN_TRAVELLING_ALONE' group by 1""","WTA concentration")
