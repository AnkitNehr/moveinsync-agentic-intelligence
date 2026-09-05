import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()

print("="*100); print("SECTION 0: JOIN INTEGRITY")
show(c,"""select 'trips' t, count(*) n, count(distinct (trip_id,business_unit)) key_uniq from trips
union all select 'bill', count(*), count(distinct (trip_id,business_unit)) from bill where trip_id is not null""","key uniqueness")
show(c,"""select count(*) recycled_ids from (select trip_id from trips group by 1 having count(*)>1)""","trip_ids reused across BU/month")

print("="*100); print("SECTION 1: MONEY COST OF LATENESS")
c.sql("""CREATE OR REPLACE VIEW tb AS
 SELECT t.*, b.vendor, b.contract, b.slab_name, b.bill_km, b.trip_cost
 FROM trips t JOIN bill b USING (trip_id, business_unit)""")
show(c,"select count(*) n, count(trip_cost) with_cost, round(sum(trip_cost),0) total_spend from tb","joined base")

show(c,"""select delay_reason, count(*) n, round(avg(delay_minutes),2) avg_delay,
 round(100.0*avg(on_time),2) ota, round(avg(trip_cost),2) avg_cost, round(sum(trip_cost),0) total_cost,
 round(100.0*sum(trip_cost)/(select sum(trip_cost) from tb),2) pct_of_spend
 from tb group by 1 order by 6 desc""","cost by delay_reason")

show(c,"""select delay_reason, count(*) n, round(avg(trip_cost),2) avg_cost, round(avg(bill_km),2) avg_bill_km,
 round(avg(traveled_km),2) avg_trav_km from tb group by 1 order by 1""","cost/km by reason")

# ARTIFACT CHECK: is cost difference driven by contract mix / distance, not delay?
show(c,"""select contract, count(*) n,
 round(avg(case when delay_reason='NODELAY' then trip_cost end),2) cost_nodelay,
 round(avg(case when delay_reason='DRIVER' then trip_cost end),2) cost_driver,
 round(avg(case when delay_reason='TRAFFIC' then trip_cost end),2) cost_traffic,
 count(*) filter (where delay_reason='DRIVER') n_driver
 from tb group by 1 having count(*)>=5000 order by 2 desc""","ARTIFACT CHECK: cost by delay reason WITHIN contract")

# excess cost vs matched baseline (same contract, same BU, same month)
c.sql("""CREATE OR REPLACE VIEW baseline AS
 select contract, business_unit, month, avg(trip_cost) base_cost, count(*) base_n
 from tb where delay_reason='NODELAY' group by 1,2,3""")
show(c,"""select t.delay_reason, count(*) n, round(sum(t.trip_cost),0) actual_spend,
 round(sum(bl.base_cost),0) baseline_spend, round(sum(t.trip_cost-bl.base_cost),0) excess,
 round(avg(t.trip_cost-bl.base_cost),2) excess_per_trip
 from tb t join baseline bl using (contract,business_unit,month)
 where t.delay_reason<>'NODELAY' and bl.base_n>=100 group by 1 order by 5 desc""","EXCESS spend vs same-contract/BU/month baseline")

show(c,"""select month, t.delay_reason, count(*) n, round(sum(t.trip_cost-bl.base_cost),0) excess
 from tb t join baseline bl using (contract,business_unit,month)
 where t.delay_reason<>'NODELAY' and bl.base_n>=100 group by 1,2 order by 1,4 desc""","excess by month")

print("="*100); print("SECTION 2: EXPERIENCE COST OF LATENESS")
c.sql("""CREATE OR REPLACE VIEW tf AS
 SELECT t.trip_id, t.business_unit, t.office, t.month, t.delay_reason, t.delay_minutes, t.on_time,
  t.vendor_id, t.trip_direction, t.product_type,
  f.stwid, f.route_rating, f.driver_rating, f.cab_rating, f.safety_rating, f.marshal_rating
 FROM trips t JOIN fb f USING (trip_id, business_unit)""")
show(c,"select count(*) n, count(distinct (trip_id,business_unit)) trips from tf","tf base")
show(c,"""select delay_reason, count(*) n_ratings,
 round(avg(route_rating),3) route, round(avg(driver_rating),3) driver, round(avg(cab_rating),3) cab,
 round(avg(safety_rating),3) safety, round(avg(marshal_rating),3) marshal
 from tf group by 1 order by 1""","rating by delay_reason")
show(c,"""select on_time, count(*) n, round(avg(route_rating),3) route, round(avg(driver_rating),3) driver,
 round(avg(cab_rating),3) cab, round(avg(safety_rating),3) safety from tf group by 1 order by 1""","rating on-time vs late")
show(c,"""select delay_reason,
 case when delay_minutes<=5 then 'a 0-5' when delay_minutes<=15 then 'b 6-15'
      when delay_minutes<=30 then 'c 16-30' when delay_minutes<=60 then 'd 31-60' else 'e 60+' end bucket,
 count(*) n, round(avg(delay_minutes),1) avg_min, round(avg(route_rating),3) route, round(avg(driver_rating),3) driver
 from tf where delay_reason<>'NODELAY' group by 1,2 having count(*)>=500 order by 1,2""","rating by delay bucket x reason")
show(c,"""with b as (select avg(route_rating) r0 from tf where delay_reason='NODELAY')
 select delay_reason, count(*) n, round(avg(delay_minutes),2) avg_delay,
  round(avg(route_rating)-(select r0 from b),4) route_delta,
  round(1000*((select r0 from b)-avg(route_rating))/nullif(avg(delay_minutes),0),3) route_pts_lost_per_1000min
 from tf where delay_reason<>'NODELAY' group by 1 order by 5 desc""","rating damage per minute of delay")
