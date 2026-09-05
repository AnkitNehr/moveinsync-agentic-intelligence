import sys
sys.path.insert(0,'/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis')
from crosstable_base import con, show
c = con()

print("="*100); print("SECTION 0: KEY / JOIN INTEGRITY ACROSS ALL 5 TABLES")
show(c,"""select 'bill_raw_nonnumeric' k, count(*) n from read_csv('/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw/bill_data.csv',header=true,all_varchar=true,sample_size=-1)
 where try_cast(replace(trip_id,',','') as bigint) is null""","bill trip_id that fail cast (OverHead)")
show(c,"""select trip_id_raw, count(*) n, round(sum(trip_cost),0) tot from bill where trip_id is null group by 1 order by 2 desc limit 5""","what are they + how much money")

show(c,"""select 'trips' t, count(*) n, count(distinct trip_id) d, count(distinct (trip_id,business_unit)) db from trips
union all select 'bill', count(*), count(distinct trip_id), count(distinct (trip_id,business_unit)) from bill where trip_id is not null
union all select 'fb', count(*), count(distinct trip_id), count(distinct (trip_id,business_unit)) from fb
union all select 'alerts', count(*), count(distinct trip_id), count(distinct (trip_id,business_unit)) from alerts
union all select 'emp', count(*), count(distinct trip_id), count(distinct (trip_id,business_unit)) from emp""","row vs key cardinality")

# does trip_id alone collide across BU? (6753 dupes found earlier)
show(c,"""select count(*) n_ids, sum(nbu) rows_affected from (
  select trip_id, count(distinct business_unit) nbu from trips group by 1 having count(distinct business_unit)>1)""","trip_ids spanning >1 BU")

show(c,"""select 'trips->bill' j, count(*) nn from trips t join bill b using(trip_id,business_unit)
union all select 'trips no bill', count(*) from trips t left join bill b using(trip_id,business_unit) where b.trip_id is null
union all select 'bill no trip', count(*) from bill b left join trips t using(trip_id,business_unit) where t.trip_id is null and b.trip_id is not null
union all select 'trips->fb(distinct)', count(distinct (t.trip_id,t.business_unit)) from trips t join fb f using(trip_id,business_unit)
union all select 'trips->alerts(distinct)', count(distinct (t.trip_id,t.business_unit)) from trips t join alerts a using(trip_id,business_unit)
union all select 'trips->emp(distinct)', count(distinct (t.trip_id,t.business_unit)) from trips t join emp e using(trip_id,business_unit)""","coverage")

show(c,"""select 'join on trip_id ONLY' j, count(*) nn, round(sum(b.trip_cost),0) tot from trips t join bill b on t.trip_id=b.trip_id
 union all select 'join on (trip_id,BU)', count(*), round(sum(b.trip_cost),0) from trips t join bill b on t.trip_id=b.trip_id and t.business_unit=b.business_unit""","FAN-OUT DAMAGE of naive trip_id-only join")

print("="*100); print("SECTION 3: ALERTS -> RATINGS")
show(c,"""select event_type, count(*) n, count(distinct trip_id) trips, count(distinct stwid) emps,
 round(100.0*count(*) filter (where trip_id is null)/count(*),2) pct_null_tripid
 from alerts group by 1 order by 2 desc""","alert volume by event_type")
show(c,"""select severity, count(*) n from alerts group by 1 order by 2 desc""","severity values (stray 'False')")
show(c,"""select event_type, severity, count(*) n from alerts group by 1,2 order by 1,3 desc""","event x severity")

# trip-level: alerted vs not
c.sql("""CREATE OR REPLACE VIEW trip_alert AS
 select trip_id, business_unit, count(*) n_alerts,
  max(case when event_type='WOMAN_TRAVELLING_ALONE' then 1 else 0 end) wta,
  max(case when event_type='SOS' then 1 else 0 end) sos,
  max(case when event_type='PANIC' then 1 else 0 end) panic
 from alerts where trip_id is not null group by 1,2""")
c.sql("""CREATE OR REPLACE VIEW fb_alert AS
 select f.*, coalesce(a.n_alerts,0) n_alerts, coalesce(a.wta,0) wta
 from fb f left join trip_alert a using(trip_id,business_unit)""")
show(c,"""select case when n_alerts>0 then 'alerted' else 'no alert' end g, count(*) n,
 round(avg(safety_rating),4) safety, round(avg(driver_rating),4) driver, round(avg(route_rating),4) route,
 round(100.0*count(*) filter (where safety_rating<=3)/count(safety_rating),3) pct_safety_le3
 from fb_alert group by 1""","ratings: alerted trips vs not")

# per event type, ratings of feedback on that trip
show(c,"""select a.event_type, count(*) n_ratings, round(avg(f.safety_rating),4) safety,
 round(avg(f.driver_rating),4) driver, round(avg(f.route_rating),4) route,
 round(100.0*count(*) filter (where f.safety_rating<=3)/count(f.safety_rating),3) pct_safety_le3
 from alerts a join fb f using(trip_id,business_unit)
 group by 1 having count(*)>=500 order by 3""","ratings by alert event_type (n>=500)")
show(c,"""select round(avg(safety_rating),4) safety, count(*) n,
 round(100.0*count(*) filter (where safety_rating<=3)/count(safety_rating),3) pct_safety_le3 from fb""","ALL feedback baseline")

# ARTIFACT CHECK 1: same-employee? WTA alert fires on the employee, does THAT employee rate lower
show(c,"""select case when a.stwid is not null then 'alert on this rider' else 'x' end g, count(*) n,
 round(avg(f.safety_rating),4) safety,
 round(100.0*count(*) filter (where f.safety_rating<=3)/count(f.safety_rating),3) pct_le3
 from fb f join alerts a on f.trip_id=a.trip_id and f.business_unit=a.business_unit and f.stwid=a.stwid
 group by 1""","ratings by the SAME rider the alert was about")
# ARTIFACT CHECK 2: is alert rate just a proxy for BU/night-shift mix?
show(c,"""select f.business_unit, count(*) n,
 round(avg(f.safety_rating) filter (where fa.n_alerts>0),4) safety_alert,
 count(*) filter (where fa.n_alerts>0) n_alert,
 round(avg(f.safety_rating) filter (where fa.n_alerts=0),4) safety_noalert
 from fb f join fb_alert fa on f.trip_id=fa.trip_id and f.business_unit=fa.business_unit and f.stwid is not distinct from fa.stwid
 group by 1 having count(*) filter (where fa.n_alerts>0)>=500 order by 4 desc""","ARTIFACT CHECK: alert effect WITHIN business_unit")

print("="*100); print("SECTION 3b: WOMAN_TRAVELLING_ALONE deep dive")
show(c,"""select a.event_type, e.gender, count(*) n from alerts a
 join emp e on a.trip_id=e.trip_id and a.business_unit=e.business_unit and a.stwid=e.stwid
 where a.event_type like 'WOMAN%' group by 1,2 order by 3 desc""","WTA alerts vs emp gender")
show(c,"""select t.actual_escort, count(*) n, round(100.0*avg(t.on_time),2) ota
 from alerts a join trips t using(trip_id,business_unit)
 where a.event_type like 'WOMAN%' group by 1""","WTA alerts: was escort present?")
show(c,"""select coalesce(t.actual_escort::varchar,'null') esc, count(*) n_trips,
 count(distinct case when ta.wta=1 then t.trip_id end) wta_trips,
 round(1000.0*count(distinct case when ta.wta=1 then t.trip_id end)/count(*),3) wta_per_1000
 from trips t left join trip_alert ta using(trip_id,business_unit) group by 1 order by 2 desc""","WTA rate by escort presence")
