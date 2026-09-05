import duckdb, os
RAW = "/Users/ankitnehra/Documents/ankit/moveinsync assesment/data/raw/"

def con():
    c = duckdb.connect()
    c.sql(f"""CREATE OR REPLACE VIEW trips AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, office, product_type, vendor_id, trip_direction, shift_type,
      coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason, actual_cab_fuel_type,
      route_source, strptime(trip_date,'%B %d, %Y')::DATE AS trip_date,
      date_trunc('month', strptime(trip_date,'%B %d, %Y'))::DATE AS month,
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
      TRY_CAST(replace(planned_end_epoch,',','') AS BIGINT) AS planned_end_epoch,
      TRY_CAST(replace(actual_end_epoch,',','') AS BIGINT) AS actual_end_epoch,
      CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE)<=5 THEN 1 ELSE 0 END AS on_time
    FROM read_csv('{RAW}Ride_data*.csv', header=true, union_by_name=true,
      null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)""")

    c.sql(f"""CREATE OR REPLACE VIEW bill AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      trip_id AS trip_id_raw,
      business_unit, office, vendor, contract, slab_name,
      TRY_CAST(replace(total_trip_km,',','') AS DOUBLE) AS bill_km,
      TRY_CAST(replace(trip_cost,',','') AS DOUBLE) AS trip_cost,
      strptime(cycle_start,'%B %d, %Y, %I:%M %p') AS cycle_start,
      strptime(cycle_end,'%B %d, %Y, %I:%M %p') AS cycle_end
    FROM read_csv('{RAW}bill_data.csv', header=true, all_varchar=true, sample_size=-1)""")

    c.sql(f"""CREATE OR REPLACE VIEW fb AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, trip_type, TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
      TRY_CAST(route_rating AS DOUBLE) AS route_rating,
      TRY_CAST(driver_rating AS DOUBLE) AS driver_rating,
      TRY_CAST(cab_rating AS DOUBLE) AS cab_rating,
      TRY_CAST(safety_rating AS DOUBLE) AS safety_rating,
      TRY_CAST(marshal_rating AS DOUBLE) AS marshal_rating,
      strptime(trip_date,'%B %d, %Y, %I:%M %p') AS fb_trip_date,
      strptime(creation_time,'%B %d, %Y, %I:%M %p') AS creation_time
    FROM read_csv('{RAW}trip_feedback.csv', header=true, all_varchar=true, sample_size=-1)""")

    c.sql(f"""CREATE OR REPLACE VIEW alerts AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
      event_id, event_type, state_text, severity, source,
      strptime(start_time,'%B %d, %Y, %I:%M %p') AS start_time,
      strptime(acknowledge_time,'%B %d, %Y, %I:%M %p') AS ack_time
    FROM read_csv('{RAW}alerts_data.csv', header=true, all_varchar=true, sample_size=-1)""")

    c.sql(f"""CREATE OR REPLACE VIEW emp AS SELECT
      TRY_CAST(replace(trip_id,',','') AS BIGINT) AS trip_id,
      business_unit, office, product_type, shift_type,
      TRY_CAST(replace(stwid,',','') AS BIGINT) AS stwid,
      signintype, gender, emp_role, boarding_status, not_boarding_reason,
      TRY_CAST(is_no_show AS BOOLEAN) AS is_no_show,
      TRY_CAST(trip_date AS DATE) AS trip_date,
      date_trunc('month', TRY_CAST(trip_date AS DATE))::DATE AS month,
      TRY_CAST(replace(planned_pickup_epoch,',','') AS BIGINT) AS planned_pickup_epoch,
      TRY_CAST(replace(actual_pickup_epoch,',','') AS BIGINT) AS actual_pickup_epoch,
      TRY_CAST(replace(planned_drop_epoch,',','') AS BIGINT) AS planned_drop_epoch,
      TRY_CAST(replace(actual_drop_epoch,',','') AS BIGINT) AS actual_drop_epoch,
      TRY_CAST(planned_km AS DOUBLE) AS planned_km,
      TRY_CAST(traveled_km AS DOUBLE) AS traveled_km
    FROM read_csv('{RAW}emp_Data.csv', header=true, all_varchar=true, sample_size=-1)""")
    return c

def show(c, sql, title=""):
    if title: print(f"\n--- {title}")
    r = c.sql(sql)
    cols = r.columns
    rows = r.fetchall()
    def f(v):
        if isinstance(v,float): return f"{v:,.3f}"
        if isinstance(v,int): return f"{v:,}"
        return str(v)
    data=[cols]+[[f(v) for v in row] for row in rows]
    w=[max(len(d[i]) for d in data) for i in range(len(cols))]
    for i,d in enumerate(data):
        print("  ".join(x.ljust(w[j]) for j,x in enumerate(d)))
        if i==0: print("  ".join("-"*w[j] for j in range(len(cols))))
    print(f"[{len(rows)} rows]")
