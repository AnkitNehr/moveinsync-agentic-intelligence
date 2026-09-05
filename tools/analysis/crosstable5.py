import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()
c.sql("""CREATE OR REPLACE VIEW tb AS
 SELECT t.*, b.vendor, b.contract, b.slab_name, b.bill_km, b.trip_cost
 FROM trips t JOIN bill b USING (trip_id, business_unit)""")

print("="*100); print("SECTION 1b: WAS THE 'DRIVER DELAY SAVES MONEY' RESULT ONE CREDIT NOTE?")
show(c,"""select delay_reason, month, count(*) n, round(sum(trip_cost),0) tot,
 round(min(trip_cost),2) mn, count(*) filter (where trip_cost<0) n_neg,
 round(sum(trip_cost) filter (where trip_cost<0),0) neg_tot
 from tb where trip_cost<0 or delay_reason='DRIVER' group by 1,2 order by 1,2""","negative costs by delay_reason x month")
show(c,"""select trip_id, business_unit, month, delay_reason, contract, vendor, round(trip_cost,2) tc
 from tb order by trip_cost limit 5""","the 5 most negative billed trips")

# redo excess-spend analysis EXCLUDING negative/credit rows
c.sql("""CREATE OR REPLACE VIEW tbc AS select * from tb where trip_cost>=0""")
c.sql("""CREATE OR REPLACE VIEW baseline AS
 select contract, business_unit, month, avg(trip_cost) base_cost, count(*) base_n
 from tbc where delay_reason='NODELAY' group by 1,2,3""")
show(c,"""select t.delay_reason, count(*) n, round(sum(t.trip_cost),0) actual_spend,
 round(sum(t.trip_cost-bl.base_cost),0) excess, round(avg(t.trip_cost-bl.base_cost),2) excess_per_trip
 from tbc t join baseline bl using (contract,business_unit,month)
 where t.delay_reason<>'NODELAY' and bl.base_n>=100 group by 1 order by 4 desc""","EXCESS spend, credits EXCLUDED (contract+BU+month matched)")
show(c,"""select month, t.delay_reason, count(*) n, round(sum(t.trip_cost-bl.base_cost),0) excess,
 round(avg(t.trip_cost-bl.base_cost),2) per_trip
 from tbc t join baseline bl using (contract,business_unit,month)
 where t.delay_reason<>'NODELAY' and bl.base_n>=100 group by 1,2 order by 1,4 desc""","excess by month, credits excluded")
# tighter control: also match slab_name
c.sql("""CREATE OR REPLACE VIEW baseline2 AS
 select contract, slab_name, business_unit, month, avg(trip_cost) base_cost, count(*) base_n
 from tbc where delay_reason='NODELAY' group by 1,2,3,4""")
show(c,"""select t.delay_reason, count(*) n, round(sum(t.trip_cost-bl.base_cost),0) excess,
 round(avg(t.trip_cost-bl.base_cost),2) per_trip
 from tbc t join baseline2 bl using (contract,slab_name,business_unit,month)
 where t.delay_reason<>'NODELAY' and bl.base_n>=100 group by 1 order by 3 desc""","excess vs contract+SLAB+BU+month baseline")

print("="*100); print("SECTION 1c: WHAT IS delay_minutes ACTUALLY MEASURING?")
show(c,"""select count(*) n,
 round(avg(abs(delay_minutes - (actual_end_epoch-planned_end_epoch)/60.0)),3) mean_abs_diff_vs_END,
 round(100.0*count(*) filter (where abs(delay_minutes-(actual_end_epoch-planned_end_epoch)/60.0)<1)/count(*),2) pct_match_END
 from trips where actual_end_epoch is not null and planned_end_epoch is not null and delay_minutes is not null""","delay_minutes == end-time lateness?")
show(c,"""select count(*) n, round(100.0*count(*) filter (where delay_minutes=0)/count(*),2) pct_zero,
 round(100.0*count(*) filter (where delay_minutes<0)/count(*),2) pct_neg from trips""","delay_minutes shape")
show(c,"""select delay_reason, count(*) n, round(100.0*count(*) filter (where delay_minutes=0)/count(*),2) pct_zero
 from trips group by 1 order by 2 desc""","zero-delay by reason (is NODELAY definitionally 0?)")

print("="*100); print("SECTION 7: VENDOR SCORECARD (n>=1000)")
c.sql("""CREATE OR REPLACE VIEW trip_alert AS
 select trip_id, business_unit, count(*) n_alerts from alerts where trip_id is not null group by 1,2""")
c.sql("""CREATE OR REPLACE VIEW fb_trip AS
 select trip_id, business_unit, avg(driver_rating) driver_rating, avg(safety_rating) safety_rating,
  count(*) n_fb, count(*) filter (where driver_rating<=3) n_det
 from fb group by 1,2""")
c.sql("""CREATE OR REPLACE VIEW vs AS
 select t.vendor_id, t.trip_id, t.business_unit, t.month, t.on_time, t.delay_minutes, t.delay_reason,
  t.is_driver_nc, t.is_cab_nc, t.emp_actual, t.cab_capacity, t.noshow, t.emp_planned,
  b.contract, b.trip_cost, b.bill_km,
  coalesce(a.n_alerts,0) n_alerts, f.driver_rating, f.n_fb, f.n_det
 from trips t join bill b using(trip_id,business_unit)
 left join trip_alert a using(trip_id,business_unit)
 left join fb_trip f using(trip_id,business_unit)
 where b.trip_cost>=0""")
show(c,"""select vendor_id, count(*) n_trips,
 round(100.0*avg(on_time),2) ota,
 round(1000.0*count(*) filter (where n_alerts>0)/count(*),2) alerts_per_1000,
 round(100.0*avg(case when is_driver_nc then 1 else 0 end),3) driver_nc_pct,
 round(100.0*avg(case when is_cab_nc then 1 else 0 end),3) cab_nc_pct,
 round(avg(driver_rating),4) drv_rating, count(driver_rating) n_rated,
 round(100.0*sum(n_det)/nullif(sum(n_fb),0),3) pct_detractor,
 round(sum(trip_cost)/nullif(sum(emp_actual),0),2) cost_per_rider,
 round(100.0*avg(emp_actual)/nullif(avg(cab_capacity),0),1) occ_pct,
 round(sum(trip_cost)/1e6,2) spend_mn
 from vs group by 1 having count(*)>=1000 order by 3""","VENDOR SCORECARD raw")

# fair cost comparison: index each vendor's cost against the contract+BU+month average
c.sql("""CREATE OR REPLACE VIEW cbase AS
 select contract, business_unit, month, avg(trip_cost) mkt from vs group by 1,2,3 having count(*)>=200""")
show(c,"""select v.vendor_id, count(*) n, round(100.0*avg(v.trip_cost/nullif(cb.mkt,0)),2) cost_index_vs_peers
 from vs v join cbase cb using(contract,business_unit,month) group by 1 having count(*)>=1000 order by 3 desc""","COST INDEX: vendor cost vs peer avg on identical contract+BU+month (100=par)")

show(c,"""select vendor_id, count(distinct contract) n_contracts, count(distinct business_unit) n_bu,
 string_agg(distinct business_unit,',') bus from vs group by 1 having count(*)>=1000 order by 2 desc""","vendor footprint (is comparison apples-to-apples?)")
