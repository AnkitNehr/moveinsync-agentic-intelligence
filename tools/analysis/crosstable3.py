import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()

print("="*100); print("SECTION 3c: WTA VERIFICATION (artifact checks)")
c.sql("""CREATE OR REPLACE VIEW trip_alert AS
 select trip_id, business_unit, count(*) n_alerts,
  max(case when event_type='WOMAN_TRAVELLING_ALONE' then 1 else 0 end) wta
 from alerts where trip_id is not null group by 1,2""")
# A1: is it just female riders rating lower?
show(c,"""select e.gender, count(*) n, round(avg(f.safety_rating),4) safety,
 round(100.0*count(*) filter (where f.safety_rating<=3)/count(f.safety_rating),3) pct_le3
 from fb f join emp e on f.trip_id=e.trip_id and f.business_unit=e.business_unit and f.stwid=e.stwid
 group by 1 order by 2 desc""","A1: baseline safety rating by rider gender")
# A2: WTA effect restricted to FEMALE raters only
show(c,"""select case when ta.wta=1 then 'WTA trip' else 'no WTA' end g, count(*) n,
 round(avg(f.safety_rating),4) safety,
 round(100.0*count(*) filter (where f.safety_rating<=3)/count(f.safety_rating),3) pct_le3
 from fb f join emp e on f.trip_id=e.trip_id and f.business_unit=e.business_unit and f.stwid=e.stwid
 left join trip_alert ta on f.trip_id=ta.trip_id and f.business_unit=ta.business_unit
 where e.gender='FEMALE' group by 1 order by 1""","A2: FEMALE raters only, WTA vs not")
# A3: is it the flagged woman herself, or all riders on that trip?
show(c,"""select case when a.stwid is not null then 'the flagged rider' else 'other rider on same trip' end g,
 count(*) n, round(avg(f.safety_rating),4) safety,
 round(100.0*count(*) filter (where f.safety_rating<=3)/count(f.safety_rating),3) pct_le3
 from fb f join trip_alert ta on f.trip_id=ta.trip_id and f.business_unit=ta.business_unit and ta.wta=1
 left join alerts a on a.trip_id=f.trip_id and a.business_unit=f.business_unit and a.stwid=f.stwid and a.event_type='WOMAN_TRAVELLING_ALONE'
 group by 1 order by 1""","A3: flagged rider vs co-rider on WTA trips")
# A4: shift/BU confound
show(c,"""select t.shift_type, count(*) n_wta_ratings, round(avg(f.safety_rating),4) safety_wta
 from fb f join trip_alert ta on f.trip_id=ta.trip_id and f.business_unit=ta.business_unit and ta.wta=1
 join trips t on t.trip_id=f.trip_id and t.business_unit=f.business_unit
 group by 1 order by 2 desc limit 8""","A4: WTA ratings by shift_type")
show(c,"""select t.shift_type, count(*) n, round(avg(f.safety_rating),4) safety
 from fb f join trips t on t.trip_id=f.trip_id and t.business_unit=f.business_unit
 group by 1 order by 2 desc limit 8""","A4b: ALL ratings by shift_type (baseline)")
# A5 how many trips / distinct riders behind it
show(c,"""select count(*) n_rating_rows, count(distinct (f.trip_id,f.business_unit)) trips, count(distinct f.stwid) riders
 from fb f join trip_alert ta on f.trip_id=ta.trip_id and f.business_unit=ta.business_unit and ta.wta=1""","A5: sample size behind WTA finding")

print("="*100); print("SECTION 4: NO-SHOWS -> COST")
c.sql("""CREATE OR REPLACE VIEW tb AS
 SELECT t.*, b.vendor, b.contract, b.slab_name, b.bill_km, b.trip_cost
 FROM trips t JOIN bill b USING (trip_id, business_unit)""")
show(c,"""select count(*) n, count(*) filter (where noshow>0) n_with_noshow,
 round(100.0*count(*) filter (where noshow>0)/count(*),2) pct_trips, sum(noshow) total_noshow_seats,
 sum(emp_planned) planned_seats, round(100.0*sum(noshow)/sum(emp_planned),2) pct_seats_noshow
 from tb""","no-show prevalence")
show(c,"""select case when noshow=0 then '0' when noshow=1 then '1' when noshow=2 then '2' else '3+' end g,
 count(*) n, round(avg(trip_cost),2) avg_cost, round(avg(emp_planned),2) planned, round(avg(emp_actual),2) actual
 from tb group by 1 order by 1""","cost by noshow count (RAW - confounded)")
# ARTIFACT CHECK: within contract+slab, does a no-show change what we pay?
show(c,"""select contract, count(*) n,
 round(avg(trip_cost) filter (where noshow=0),2) cost_no_ns,
 count(*) filter (where noshow>0) n_ns,
 round(avg(trip_cost) filter (where noshow>0),2) cost_ns,
 round(avg(trip_cost) filter (where noshow>0)-avg(trip_cost) filter (where noshow=0),2) delta
 from tb group by 1 having count(*) filter (where noshow>0)>=1000 order by 2 desc""","ARTIFACT CHECK: does a no-show change the bill? (within contract)")
show(c,"""select case when bill_km=0 then 'fixed-rate (km=0)' else 'distance-billed' end g,
 count(*) n, round(avg(trip_cost) filter (where noshow=0),2) cost_no_ns,
 round(avg(trip_cost) filter (where noshow>0),2) cost_ns,
 count(*) filter (where noshow>0) n_ns
 from tb group by 1""","does no-show change bill: fixed vs distance contracts")
# the real cost: paid-for-but-empty seat value
show(c,"""select month, count(*) n, sum(noshow) seats_noshow, round(sum(trip_cost),0) spend,
 round(sum(trip_cost*noshow/nullif(emp_planned,0)),0) noshow_seat_value,
 round(100.0*sum(trip_cost*noshow/nullif(emp_planned,0))/sum(trip_cost),2) pct_of_spend
 from tb group by 1 order by 1""","seat-value attributable to no-shows, by month")
show(c,"""select business_unit, office, count(*) n, sum(noshow) seats,
 round(sum(trip_cost*noshow/nullif(emp_planned,0)),0) noshow_seat_value,
 round(100.0*sum(trip_cost*noshow/nullif(emp_planned,0))/sum(trip_cost),2) pct_of_spend
 from tb group by 1,2 having count(*)>=1000 order by 5 desc limit 12""","no-show seat value by office")
# empty trips: paid full, zero riders
show(c,"""select count(*) n, round(sum(trip_cost),0) spend, round(avg(trip_cost),2) avg_cost
 from tb where emp_actual=0""","GHOST TRIPS: billed but zero actual employees")
show(c,"""select month, count(*) n, round(sum(trip_cost),0) spend from tb where emp_actual=0 group by 1 order by 1""","ghost trips by month")
show(c,"""select business_unit, office, count(*) n, round(sum(trip_cost),0) spend,
 round(avg(emp_planned),2) avg_planned from tb where emp_actual=0 group by 1,2 order by 4 desc limit 10""","ghost trips by office")
# verify ghost trips against emp_data (independent table)
show(c,"""select count(*) n_trips, sum(rider_rows) rider_rows, sum(noshow_rows) noshow_rows
 from (select t.trip_id, t.business_unit, count(e.stwid) rider_rows,
        count(*) filter (where e.is_no_show) noshow_rows
       from tb t left join emp e using(trip_id,business_unit)
       where t.emp_actual=0 group by 1,2)""","VERIFY ghost trips in emp_data")

print("="*100); print("SECTION 5: OCCUPANCY -> COST PER RIDER")
show(c,"""select cab_capacity, count(*) n, round(avg(emp_planned),2) planned, round(avg(emp_actual),2) actual,
 round(100.0*avg(emp_actual)/nullif(cab_capacity,0),1) occ_pct, round(avg(trip_cost),2) avg_cost,
 round(sum(trip_cost)/nullif(sum(emp_actual),0),2) cost_per_rider
 from tb group by 1 having count(*)>=1000 order by 1""","occupancy + cost per rider by cab capacity")
show(c,"""select contract, count(*) n, round(avg(cab_capacity),2) cap, round(avg(emp_actual),2) riders,
 round(100.0*avg(emp_actual)/nullif(avg(cab_capacity),0),1) occ_pct,
 round(avg(trip_cost),2) cost_trip, round(sum(trip_cost)/nullif(sum(emp_actual),0),2) cost_per_rider
 from tb group by 1 having count(*)>=1000 order by 7 desc""","cost per rider by contract")
