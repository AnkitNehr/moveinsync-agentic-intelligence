# Data Quality & Integrity — Exhaustive Audit

**Script:** `/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis/dataquality.py`
**Engine:** DuckDB 1.5.5 · **Run:** `.venv/bin/python tools/analysis/dataquality.py <stage>`
**Stages:** `profile refint dupes impossible dates drift categorical whitespace impact collision semantics outage final` (or `all`)

Every number below is pasted from a query that was actually executed. Nothing is estimated.

**Corpus as loaded:** ride 615,546 rows · bill 620,942 · emp 1,637,906 · feedback 512,873 · alerts 51,699.
**Money:** gross positive ₹849,479,569.03 · credits −₹15,502,797.74 · **net ₹833,976,771.29**.

---

## Part 1 — Ranked findings

### 🔴 HIGH-1 · `trip_id` is not a primary key: 6,753 IDs are recycled between two business units

`ride_data` has 615,546 rows but only 608,793 distinct `trip_id`. Every one of the 6,753 duplicated IDs
appears **exactly twice**, and every pair is a genuinely different trip:

```
--- which BUs suffer the collision ---
business_unit  colliding_ids  rows_affected  bu_rows  pct_of_bu
orbit-Slc               6753           6753    48295     13.983
vanta-Aus               6753           6753    70199      9.620

--- when do the two copies occur ---
src_month     mn           mx          n
July     2026-07-03   2026-07-31   6753
June     2026-06-01   2026-06-05    910
may      2026-05-01   2026-05-31   5843

--- side-by-side ---
trip_id  src_month  trip_date   business_unit  office              vendor_id                traveled_km
1208678  may        2026-05-01  orbit-Slc      Eastgate Office     Rohan Mikhailov Travel          2.90
1208678  July       2026-07-03  vanta-Aus      Cedar Ridge Office  Sneha Mikhailov Travel          8.40
```

Proof it is **ID recycling, not duplicate records**: 0 of 6,753 pairs share a date; all 6,753 are >30 days
apart (gap 54–63 days, median 61). The colliding IDs occupy one contiguous block, 1,208,678–1,260,079.

**Business impact — a naive `JOIN ... USING (trip_id)` silently overstates spend:**

```
join_rows  bill_rows  inflated_total  true_total     overstatement
   628551     620782   844,880,382.27  833,976,771.29  ₹10,903,610.98
```

₹18,753,571.08 (**2.249% of spend**, 13,998 bill rows) sits on IDs that cannot be attributed to one unique trip.
38,387 `emp_Data` rows (2.344%) sit on ambiguous IDs.

**Handling — verified safe keys (all give `still_dup = 0` on 615,546 rows):** `(trip_id, trip_date)`,
`(trip_id, business_unit)`, `(trip_id, src_month)`. Joining `trips ⋈ bill` on `(trip_id, business_unit)`
yields 614,800 rows and ₹826,459,283.95 with zero fan-out.

*Personas: facilities_head (spend is overstated by ₹10.9M), transport_manager (any trip lookup by ID is ambiguous).*

---

### 🔴 HIGH-2 · `delay_minutes` is reason-gated, not measured — the 94% OTA headline is an artifact

`delay_minutes` agrees with epoch arithmetic on only **4.847%** of trips. It is a perfect function of `delay_reason`:

```
--- delay_reason vs delay_minutes ---
delay_reason      n       pct_zero  avg_delay  avg_epoch_delay
NODELAY      555237        100.00        0.00             8.31
TRAFFIC       23274          0.00       19.23            35.87
EMPLOYEE      20476          0.00       10.07            30.60
DRIVER        16559          0.00       22.52            43.26

--- contradiction check ---
n         nodelay_but_positive  reason_but_zero
615546                       0                0
```

Zero contradictions in either direction across 615,546 rows. So `delay_minutes = 0` means *"no delay reason was
logged"*, **not** *"the cab was on time"* — and those 555,237 NODELAY trips ran an average of **8.31 minutes late**
by their own epochs. 56.96% of all trips carry `delay_minutes = 0` while `actual_end_epoch > planned_end_epoch`.

**Business impact — OTA computed three defensible ways gives three different answers:**

```
ota_from_delay_col  ota_from_end_epoch  ota_from_start_epoch
             94.12               44.59                 74.79
```

**The saving grace — the month-over-month story survives, the level does not:**

```
month       ota_delay_col  ota_end_epoch
2026-05-01          95.31          46.89
2026-06-01          92.46          41.07   <- June is the dip under BOTH definitions
2026-07-01          94.69          46.01
```

**Handling:** the existing June-dip finding is safe. The 94% *level* must never be quoted as punctuality —
label it "trips with no delay reason logged". Report true punctuality from epochs and state the definition.

*Personas: facilities_head (SLA reporting against a vendor at 94% is indefensible), transport_manager.*

---

### 🔴 HIGH-3 · Feedback coverage varies 26× across business units — cross-BU CSAT is meaningless

```
--- feedback coverage by BU ---
business_unit   trips   coverage_pct
vanta-Sea      180064           3.66
catalyst-Sac    65214          11.60
vanta-Aus       70199          12.43
pinnacle-Slc   251774          93.49
orbit-Slc       48295          95.67
```

Overall 311,073 trips (50.536%) have no feedback at all. `pinnacle-Slc` + `orbit-Slc` supply 495,323 of
512,873 feedback rows (96.6%) while representing 49% of trips. Any BU league table on CSAT is ranking
response rates, not service quality.

**Handling:** never compare raw CSAT across BUs. Report CSAT with an explicit `n` and coverage %, or restrict
comparison to the two high-coverage BUs.

*Personas: facilities_head (vendor scorecards), transport_manager.*

---

### 🔴 HIGH-4 · `marshal_rating = 0` is "no marshal", not a zero score — a 13× error

```
--- trip_feedback.marshal_rating distribution ---
val        n        pct
  0   473692     92.360
  1      207      0.040
  2       65      0.013
  3      120      0.023
  4     4357      0.850
  5    34432      6.714

--- the trap ---
naive_avg  avg_excl_zero  n_real
    0.371          4.857   39181
```

The other four rating columns have exactly 2 zero rows each (a single junk record) — so `0` is a legitimate
score there but a **not-applicable sentinel** for `marshal_rating` only. `AVG(marshal_rating)` returns 0.371
instead of 4.857.

**Handling:** `AVG(marshal_rating) FILTER (WHERE marshal_rating > 0)`, and report `n = 39,181`, not 512,873.

*Personas: facilities_head, transport_manager.*

---

### 🔴 HIGH-5 · `bill_data.slab_name`: 30 labels, 19 real slabs — ₹352.8M mis-bucketed by a naive GROUP BY

```
--- slab labels that are the SAME slab written differently ---
slab_norm    raw_variants  variants                           n        amt
UNLABELLED              3  null,NA,0                     124913  184920860
1                       2  Slab1,Slab 1                  101486  103543241
ZONEA                   2  Zone_A,ZONE A                  14406   18390505
020                     3  Slab-0-20,0-20,0 - 20          12596   13423140
2130                    3  Slab-21-30,21-30,21 - 30       10492   13627658
31ABOVE                 3  Slab-31-above,31 - above,31-above 8202  12859133
4                       2  Slab4,Slab 4                    4263    6082590

raw_labels  normalised_labels
        30                 19

money_in_split_buckets  pct_of_spend  n_rows
           352,847,125         42.31  276358

unlabelled_spend  pct     n_rows
     184,920,860  22.17   124913
```

These are **not** whitespace variants — the hygiene scan proves `d_raw = d_trim = d_lower = 30`, so they are
genuinely distinct strings that mean the same commercial band. `GROUP BY slab_name` splits one band across
up to four buckets. Separately, `slab_name` carries the **literal string `'null'`** (121,111 rows, ₹178.0M)
plus `'NA'` and `'0'` — a string sentinel, never a SQL NULL.

**Handling:** normalise before grouping: strip a leading `Slab[- ]?`, collapse `[ _-]`, uppercase, and map
`{'null','NA','0'} → UNLABELLED`.

*Persona: facilities_head.*

---

### 🟠 MEDIUM-6 · ₹15.5M of credit notes, 94.6% of it in one vendor+contract, and one contract nets negative

```
--- negative trip_cost ---
n_neg_rows   neg_total     most_negative   d_ids  pct_rows
       189  -15,502,797.74  -2,233,332.99     157    0.0304

--- who owns it ---
business_unit  vendor                  contract         n         amt
vanta-Sea      Meera Lebedev Travel    6S-PREMIUMNEW   152  -14,660,227.46
vanta-Sea      Amit Mikhailov Travel   6S-PREMIUMNEW     6     -803,472.78
pinnacle-Slc   Neha Mikhailov Travel   NA               11      -17,250.00

--- 6S-PREMIUMNEW nets negative ---
n_rows   positive       negative        net
  1267  3,500,591.37  -15,463,700.24  -11,963,108.87

--- credits by cycle month ---
mo          n        credits        net
2026-05-01  191266  -15,480,950.24  254,608,547.76
2026-06-01  212486           NULL   284,809,881.83
2026-07-01  217190      -21,847.50  294,558,341.70

--- credit exposure by BU ---
business_unit   net_spend      credits        credit_pct_of_gross
vanta-Sea     278,719,581.43  -15,463,700.24                5.256
pinnacle-Slc  294,233,033.11      -26,025.00                0.009
```

99.86% of all credits land in the May cycle, on `vanta-Sea`. `SUM(trip_cost)` on `6S-PREMIUMNEW` returns a
**negative** number, which will break any ratio, share-of-spend or cost-per-km chart that includes it.

**Handling:** report gross and net separately; exclude negative rows from any denominator; flag `6S-PREMIUMNEW`
as adjustment-dominated.

*Persona: facilities_head.*

---

### 🟠 MEDIUM-7 · `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` stops on **18 May**, not in June

The known monthly view (7,670 May → 46 Jun → 20 Jul) hides the actual event. Daily:

```
d           n     signoff  other        d           n    signoff
2026-05-15  1089      408    681        2026-05-15   408
2026-05-16    82       38     44        2026-05-16    38
2026-05-17    23        5     18        2026-05-17     5
2026-05-18   730        2    728        2026-05-18     2
2026-05-19   649        0    649
2026-05-20   708        0    708
2026-05-21   696        0    696

--- which event types stop on May 18 ---
event_type                        n_before  n_after      n
EMPLOYEE_GEOFENCE_VIOLATION           1427     9369  10796
WOMAN_TRAVELLING_ALONE                1697     8972  10669
DEVICE_NOT_REACHABLE                  1498     8416   9914
VEHICLE_STOPPAGE                      1364     7366   8730
EMPLOYEE_SIGN_OFF_TIME_VIOLATION      7666       70   7736   <-- the only one that dies
```

Every other event type *grows* across the boundary. This is a single-rule instrumentation cut-over dated
**2026-05-18**, and monthly aggregation makes it look like a gradual Q2 improvement.

**Handling:** treat `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` as unavailable after 2026-05-18; exclude it from any
total-alerts trend or the whole alert series shows a fake −60% step.

*Personas: transport_manager, facilities_head.*

---

### 🟠 MEDIUM-8 · Two data outages that look like operational collapses

**(a) pinnacle-Slc, 2026-05-28 — an upstream source gap, present in ALL four files simultaneously:**

```
d           ride   emp    fb    alerts
2026-05-27  4034   7996  6056     157
2026-05-28   237    401   267       7
2026-05-29  2115   3903  2303      76
2026-06-01  3507   6729   319     151

--- which pinnacle offices vanish on May 28 ---
office              thu_21  thu_28
Clearwater Campus     1921       1
Willow Bend Campus    1162      30
Oakmont Office        1108     195
```

Every other BU is flat on the same day (vanta-Sea 2,833→2,683; vanta-Aus 1,128→1,010). Because all four
files drop together, this is collection loss, not a holiday.

**(b) 2026-06-01 — a feedback-only outage:**

```
d           trips   trips_with_fb  coverage_pct
2026-05-28   5051            782         15.48   (Thursday baseline 48.20)
2026-05-29   6830           2259         33.07   (Friday   baseline 46.29)
2026-06-01   8217            622          7.57   (Monday   baseline 47.75)
2026-06-02   8919           4948         55.48
```

On 1 June ride/emp/alerts are all normal — only feedback collapses. 21,678 trips (3.52% of all trips) fall in
the 28 May–1 Jun window with unmeasurable CSAT.

**Handling:** exclude 2026-05-28, 2026-05-29 and 2026-06-01 from CSAT trends; exclude 2026-05-28 pinnacle-Slc
from volume/OTA trends. Weekend coverage of 5–21% is *normal*, not an outage.

*Personas: transport_manager, facilities_head.*

---

### 🟠 MEDIUM-9 · Two disagreeing no-show definitions — a 61% relative error

```
--- boarding_status x is_no_show x reason ---
boarding_status  is_no_show  not_boarding_reason                  n       pct
Boarded          false       NULL                           1447897    88.399
Not Boarded      true        NO_SHOW                         118032     7.206
Not Boarded      false       TRIP_CANCELLED_FROM_DASHBOARD    71976     4.394
Not Boarded      false       NON_COMMUNICATING                    1     0.000

--- the two rates ---
noshow_rate_by_status  noshow_rate_by_flag  n_status  n_flag
               11.601                7.206    190009  118032
```

`boarding_status = 'Not Boarded'` gives 11.601%; `is_no_show = true` gives 7.206%. The 4.394 pt gap is
71,976 dashboard-cancelled trips — a **planner** action, not a rider no-show.

**Handling:** use `is_no_show` for rider accountability, `boarding_status` for seat utilisation. Never mix.
`ride.noshow_cnt` reconciles to `is_no_show` (only 0.41% mismatch).

*Personas: line_manager (shift readiness), transport_manager.*

---

### 🟠 MEDIUM-10 · Schema drift proved — and it is caused by exactly **one** row

```
column        may       June      July        DRIFT
planned_km    DOUBLE    DOUBLE    VARCHAR     <<< DRIFT
```

All 28 columns are otherwise identical in name, order and inferred type. The single cause:

```
src_month  business_unit  office              trip_id    trip_date     planned_km  traveled_km
July       catalyst-Sac   Santa Clara Office  1,530,501  July 9, 2026  1,092.56    980.5
```

One value crossed 1,000 and picked up a thousands separator. **The standard snippet's
`TRY_CAST(planned_km AS DOUBLE)` silently returns NULL for it** — a latent bug in the provided boilerplate.
`trip_id` and all four epochs are comma-formatted on 100% of rows in all three months; `delay_minutes` on
2/3/17 rows (only values ≥ 1000).

**Handling:** `TRY_CAST(replace(planned_km, ',', '') AS DOUBLE)` — and apply `replace(...,',','')` to
**every** numeric column in ride_data, not just the four the dictionary names.

*Persona: (engineering) — required for every other finding to be correct.*

---

### 🟠 MEDIUM-11 · Epochs are UTC-anchored; a non-UTC session shifts 25.6% of trips to the wrong day

```
--- which timezone reproduces trip_date from the epoch? ---
n        pct_date_match_utc  pct_date_match_ist
615546                99.98               74.44

--- does shift_type match the UTC or the IST rendering? ---
shift_type      n     modal_utc_hhmm  modal_ist_hhmm
15:30       26317     15:30           21:00
14:30       22619     14:30           20:00
16:30       16828     16:30           22:00
```

`to_timestamp()` renders in the **session** timezone. On this machine (Asia/Kolkata) the ride epochs render
5.5 h off, misassigning 25.56% of trips to the adjacent day and corrupting every hour-of-day / peak-shift chart.

**Handling:** always `to_timestamp(x) AT TIME ZONE 'UTC'`, or set `SET TimeZone='UTC'`.

*Personas: line_manager (shift-hour analysis), transport_manager.*

---

### 🟢 LOW-12 · Confirmed-safe: things that look broken but are not

Each of these was chased with a follow-up query and resolved as **correct data**, not a defect:

| Apparent problem | Follow-up result | Verdict |
|---|---|---|
| `alerts.stwid = 0` on 22,165 rows (42.873%) | 100% of `DEVICE_NOT_REACHABLE`, `VEHICLE_STOPPAGE`, `PANIC_FIXED_DEVICE`, `OVER_SPEEDING`, `PANIC_DEVICE`; **0%** of `EMPLOYEE_GEOFENCE_VIOLATION`, `WOMAN_TRAVELLING_ALONE`, `EMPLOYEE_SIGN_OFF_TIME_VIOLATION`, `PANIC_MOBILE`, `FIRST_MALE_NO_SHOW`. A clean binary split. | **Vehicle vs employee alert taxonomy.** Not missing data. Filter on event_type, don't impute. |
| `bill` has 6,999 duplicate `trip_id` incl. 246 not in the ride collision — double billing? | All 246 are the same orbit-Slc↔vanta-Aus recycle (May `NPT_4_SEATER` vs July `4S-HYD`, different cycle/vendor/contract), just where ride kept only one copy. Exposure ₹566,695.17 (0.068%). | **Zero evidence of double-billing.** Same ID-recycle defect. |
| A 24th vendor, `Neha Mikhailov Travel`, in bill but never in ride | 11 rows, all `trip_id='OverHead'`, all in the May cycle, total −₹17,250.00, 0 rows join a trip. | **An adjustment counterparty, not an operating vendor.** Exclude from vendor counts. |
| `emp` negative km (dictionary warns to −6.63) | 47 rows negative `traveled_km` (0.0029%), 1 row negative `planned_km` (−2.0). Not concentrated by `boarding_status` or `signintype`. | **Genuine noise at 0.003%.** Clamp to 0; too small to bias anything. |
| `ride.planned_km = 0` on 2,529 trips, all of which travelled (avg 34.34 km) | 2,323 of 2,529 are `SPOT_2.0` / `RENTLZ` — a rental product with no pre-planned route. | **Product characteristic.** Exclude from plan-vs-actual variance. |
| `ride.actualemployee_cnt` vs `emp_Data` row count mismatched on 25.5% of trips | Joined on `(trip_id, trip_date)` and counted only `boarding_status='Boarded'`: **100.00% match** (615,544 of 615,546 exact). | **My own join artifact.** The files reconcile perfectly. |
| `emp`/`feedback` disagree with `ride` on BU, office, date, direction (38,387 / 15,480 rows) | After excluding the 6,753 colliding IDs: **0 mismatches** in both. | **100% explained by HIGH-1.** |
| `bill.total_trip_km = 0` on 39.97% of rows | Confirmed fixed-rate: `4S-HYD` 99.96%, `6S-HYD` 99.97%, `4S-150ORRNEW` 99.68%, `12S-150ORRNEW` 100%. | **Fixed-rate contracts.** But see LOW-14 for the nuance. |
| `emp.not_boarding_reason` 88.399% NULL | 100% NULL when `Boarded`, 0% NULL when `Not Boarded`. | **Perfectly conditional.** Not missingness. |
| Whitespace / encoding across all 5 files | 0 leading/trailing spaces, 0 non-ASCII, 0 empty strings, `d_raw = d_trim = d_lower` on **every** key column in every file. | **Clean.** No normalisation step needed — a useful negative result. |

---

### 🟢 LOW-13 · Occupancy is overstated 9.2 pts if escorts and managers count as riders

```
--- boarded seats by role ---
pct_escort  pct_non_employee
      7.03             15.43

--- fleet utilisation, two ways ---
util_all_roles  util_employees_only
         59.14                49.96
```

`emp_role` has 16 values; `escort` (101,802 rows) and `projectmgr` (117,196) occupy seats but are not
employees being transported. Average boarded seats per trip: 2.352 all roles vs 1.987 employees only.

**Handling:** state the definition. For "are we moving people efficiently", filter `emp_role='employee'`.

*Personas: facilities_head (fleet right-sizing), line_manager.*

---

### 🟢 LOW-14 · `6S-EV-HTK` is a *mixed* contract — the fixed-rate/per-km split is not binary

```
contract          n      zero_km  pct_zero
6S-EV-HTK      6930         2862      41.3    <-- neither
4S-150ORRNEW  75080        74843     99.68
4Seater      151770          184      0.12
```

Every other contract is >99% or <6% zero-km. `6S-EV-HTK` (₹12.96M) is 41.3% — it genuinely bills both ways.
Any rule of the form "contract X is fixed-rate" is wrong for this one.

**Handling:** decide fixed-vs-metered **per row** (`total_trip_km = 0`), not per contract.

*Persona: facilities_head.*

---

### 🟢 LOW-15 · Smaller impossible values (all verified, all small)

| Check | n | % of ride | Note |
|---|---:|---:|---|
| `emp_actual > emp_planned` | 81,977 | 13.3178 | Walk-ons; not an error, but breaks "planned vs actual" as a variance metric |
| `emp_actual > cab_capacity` | 1,494 | 0.2427 | Worst overload +4. 993 are `CAB` cap-3 seating up to 5 |
| `planned_cab != actual_cab` | 1,475 | 0.2396 | Cab substitution — an ops signal, not a defect |
| `emp_planned = 0` | 653 | 0.1061 | Trip created with no roster |
| `planned_end <= planned_start` | 344 | 0.0559 | 310 are LOGOUT/CAB — plan crosses midnight |
| `actual_end <= actual_start` | 20 | 0.0032 | |
| `bill.trip_cost = 0` | 715 | — | Zero-rated lines |
| `delay_minutes > 1440` | 20 | 0.0032 | Max 10,644 min; 12 DRIVER / 6 TRAFFIC / 2 EMPLOYEE. Epochs agree to ~21 min, so **real**, not a parse artifact |
| `alerts.acknowledge_time` NULL | 54 | — | 52 of 54 are `state_text='NEW'` — **conditional, correct** |
| `feedback` created before trip **end** | 181,210 | 35.34 | `fb.trip_date` is the *shift* time, not the trip time |
| `feedback` created after 2026-07-31 | 3,601 | 0.70 | Tail to 2026-08-29 → **July CSAT is truncated** |
| `fb` from riders not on the trip roster | 139 | 0.03 | |
| `ride` orphans in bill / fb / alerts | 5,737 / 139 / 472 | 0.924 / 0.027 / 0.913 | **emp is 0.000% — a perfect 1:1 with ride** |

---

## Part 2 — Definitive quirks table (README "Data quirks handled")

| # | File · Column | Issue | Count | % | Business impact | Handling |
|---|---|---|---:|---:|---|---|
| 1 | `ride` · `trip_id` | Not unique — recycled orbit-Slc ↔ vanta-Aus | 6,753 IDs / 13,506 rows | 2.19% of rows | Naive join overstates spend by **₹10,903,610.98**; ₹18.75M (2.249%) unattributable | Key on `(trip_id, business_unit)` or `(trip_id, trip_date)` — both 0 dups |
| 2 | `ride` · `delay_minutes` | Derived from `delay_reason`, not measured (0 ⟺ NODELAY, 0 contradictions/615,546) | 555,237 zeros | 90.20% | OTA reads 94.12% vs 44.59% by epoch — SLA claims indefensible | Keep the June-dip trend (holds under both); never quote the level as punctuality |
| 3 | `ride` · `planned_km` | Comma thousands-sep in July only → dtype drift DOUBLE→VARCHAR | 1 row (trip 1,530,501) | 0.0002% | Standard `TRY_CAST(planned_km AS DOUBLE)` silently NULLs it | `TRY_CAST(replace(planned_km,',','') AS DOUBLE)` |
| 4 | `ride` · `trip_id`, all 4 epochs | Comma-formatted on 100% of rows, all months | 615,546 | 100% | Plain CAST → all NULL | `replace(x,',','')` before cast |
| 5 | `ride` · epochs | UTC-anchored; `to_timestamp()` uses session TZ | 615,546 | 100% | 25.56% of trips land on the wrong day in a non-UTC session | `AT TIME ZONE 'UTC'` (99.98% date match vs 74.44% IST) |
| 6 | `ride` · `shift_type` | 2 of 100 values are not `HH:MM` | 14,799 | 2.40% | `strptime` fails | `'Non Shift'` (12,446), `'Adhoc'` (2,353) — keep as categories |
| 7 | `ride` · `planned_cab_registration` | NULL | 181 | 0.029% | Cab-substitution analysis loses rows | Keep NULL; do not impute |
| 8 | `ride` · `is_driver_nc`,`is_cab_nc` | NULL (May file only) | 4 each | 0.001% | — | Keep NULL |
| 9 | `ride` · `planned_km = 0` | SPOT_2.0/RENTLZ has no planned route | 2,529 | 0.411% | Plan-vs-actual variance is undefined | Exclude these product types |
| 10 | `ride` · `route_source` | `SHUTTLE_SERVICE` 169→196→**8,274** (42×) | 8,274 in July | 0.089→3.833% | New service line; July mix is not comparable to May/June | Segment by month |
| 11 | `ride` · `trip_nodal` | `'NA'` share falls 56.37%→38.67% while `HOME` rises 35.66%→55.23% | — | — | Backfill improvement masquerades as a behaviour shift | Do not trend nodal mix across months |
| 12 | `bill` · `trip_id` | Literal string `'OverHead'` — plain CAST **crashes** | 160 | 0.026% | **₹4,457,559.80** (0.534%) not linkable to any trip | `TRY_CAST(replace(...))`; keep as an overhead bucket |
| 13 | `bill` · `trip_cost` | Negative (credit notes) | 189 rows / 157 IDs | 0.0304% | −₹15,502,797.74; `6S-PREMIUMNEW` nets **−₹11.96M**; vanta-Sea credits = 5.256% of gross | Report gross and net separately; exclude from denominators |
| 14 | `bill` · `slab_name` | 30 labels = 19 real slabs (`Slab1`/`Slab 1`, `Zone_A`/`ZONE A`, `0-20`/`0 - 20`/`Slab-0-20`, …) | 276,358 rows | 44.5% of rows | **₹352,847,125 (42.31%)** in split buckets | Normalise: strip `^Slab[- ]?`, collapse `[ _-]`, uppercase |
| 15 | `bill` · `slab_name` | String sentinels `'null'`/`'NA'`/`'0'`, never SQL NULL | 124,913 | 20.1% | **₹184,920,860 (22.17%)** has no usable slab | Map to `UNLABELLED`; `IS NULL` will not catch these |
| 16 | `bill` · `total_trip_km = 0` | Fixed-rate contracts | 248,191 | **39.97% of rows / 45.42% of spend** | Blended cost-per-km is meaningless | Decide per **row**, not per contract (`6S-EV-HTK` is 41.3% — mixed) |
| 17 | `bill` · `trip_cost = 0` | Zero-rated lines | 715 | 0.115% | — | Keep |
| 18 | `bill` · `vendor` | `Neha Mikhailov Travel` bills but never operates (11 rows, all OverHead, −₹17,250) | 11 | 0.002% | Inflates vendor count 23→24 | Exclude from vendor rosters |
| 19 | `bill` → `ride` | Orphan trip_ids | 5,737 rows / 5,736 IDs | 0.924% | ₹2,825,705 (0.339%) unattributable. **99.127% of spend is attributable** | Left-join; bucket orphans |
| 20 | `ride` → `bill` | Trips never billed | 746 | 0.123% | Cannot be costed. 740 of 746 are pinnacle-Slc; rises 21→263→462 by month (cycle lag) | Exclude from cost/trip |
| 21 | `emp` · `stwid = 0` | Placeholder, not a person | 1,414 rows / 706 trips | 0.086% | Breaks `(trip_id,stwid)` as a key (708 excess) | Exclude `stwid=0`; then key is **100% unique** (1,636,492/1,636,492) |
| 22 | `emp` · `boarding_status` vs `is_no_show` | Two definitions | 71,976 disagree | 4.394% | No-show rate 11.601% vs 7.206% — **61% relative** error | `is_no_show` = rider fault; `Not Boarded` = seat unused |
| 23 | `emp` · `emp_role` | `escort`/`projectmgr` occupy seats but aren't riders | 218,998 | 13.37% | Utilisation 59.14% vs 49.96% (9.2 pt) | Filter `emp_role='employee'` for rider metrics |
| 24 | `emp` · `traveled_km`,`planned_km` | Negative (to −6.63) | 47 + 1 | 0.0029% | Negligible | Clamp to 0 |
| 25 | `emp` · `signintype` | NULL exactly where `Not Boarded` | 190,009 | 11.601% | — | Conditional; do not impute |
| 26 | `emp` · `gender`,`emp_role` | NULL | 1,559 / 1,414 | 0.095% / 0.086% | — | Keep NULL |
| 27 | `emp` · pickup/drop epochs | NULL | 112,943 / 190,009 | 6.896% / 11.601% | Per-employee ride time unavailable on 11.6% | Keep NULL |
| 28 | `feedback` · `marshal_rating = 0` | "No marshal" sentinel, not a score | 473,692 | 92.360% | `AVG` = 0.371 vs true **4.857** (13×) | `FILTER (WHERE marshal_rating > 0)`, report n = 39,181 |
| 29 | `feedback` · coverage | 3.66% (vanta-Sea) → 95.67% (orbit-Slc) | 311,073 trips uncovered | 50.536% | Cross-BU CSAT comparison is invalid | Always publish coverage % and n alongside CSAT |
| 30 | `feedback` · `creation_time` | Runs to 2026-08-29, past the window | 3,601 | 0.702% | July CSAT is truncated / still arriving | Note the cut-off; don't compare July as complete |
| 31 | `feedback` · `trip_date` | Is the **shift** time, not the trip time | 181,210 rows precede trip end | 35.34% | "Feedback before the trip" is a false alarm | Join to `ride` for actual times |
| 32 | `feedback`/`ride` all-zero rating rows | Junk records | 2 | 0.0004% | — | Drop or flag |
| 33 | `alerts` · `severity` | Stray literal `'False'`; `'NA'` sentinel | 15,037 + 16,348 | 29.086% + 31.622% | Only 39.29% carry a real Sev level; `'False'` appears in all 3 months and across all event types | Treat `'False'`/`'NA'` as UNKNOWN; never cast to boolean |
| 34 | `alerts` · `stwid = 0` | Vehicle-level alerts | 22,165 | 42.873% | Looks like 43% missing employees | **Correct data** — 100%/0% clean split by event_type |
| 35 | `alerts` · `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` | Instrumentation stops **2026-05-18** | 7,666 before / 70 after | −99.1% | Total-alert trend shows a fake −60% step | Exclude this type after 2026-05-18 |
| 36 | `alerts` · `acknowledge_time` | NULL | 54 | 0.104% | — | 52/54 are `state_text='NEW'` — conditional, correct |
| 37 | `alerts` · `source` | `'NA'` sentinel; `'MOBILE'` vs `'MOBILE_APP'` (n=1) | 39,350 + 1 | 76.11% | Source attribution unusable on 76% | Treat `'NA'` as UNKNOWN; fold `MOBILE_APP`→`MOBILE` |
| 38 | `alerts` · `event_id` | — | 51,699 / 51,699 distinct | 0 dups | **Clean** — safe primary key | — |
| 39 | Coverage · 2026-05-28 | pinnacle-Slc drops in ride+emp+fb+alerts together | 21,678 trips in window | 3.52% | Volume, OTA and CSAT all dip artificially | Exclude 05-28 (all files), 05-29, 06-01 (feedback only) |
| 40 | `office` / `vendor_id` | Not unique to a BU — 5 offices span 2 BUs; `Sanjay Mikhailov Travel` spans 4 | 5 offices / 11 vendors | — | `GROUP BY office` or `GROUP BY vendor_id` silently merges BUs | Always group by `(business_unit, office)` / `(business_unit, vendor_id)` |
| 41 | All 5 files · all key columns | Whitespace / case / encoding | **0** | 0% | None | **No normalisation needed** — verified clean |
| 42 | Date coverage | All 92 days present in ride, emp, feedback, alerts; 0 out-of-window rows; each month file holds only its month | 92/92 | 100% | None | — |

---

## Part 3 — Corrected loader snippet

The snippet supplied in the brief has two latent defects. Corrected:

```sql
CREATE OR REPLACE VIEW trips AS SELECT
  TRY_CAST(replace(trip_id,',','') AS BIGINT)              AS trip_id,
  business_unit,                                            -- (trip_id, business_unit) is the real PK
  strptime(trip_date,'%B %d, %Y')::DATE                     AS trip_date,
  TRY_CAST(replace(planned_km,',','')  AS DOUBLE)           AS planned_km,   -- FIX: July has "1,092.56"
  TRY_CAST(replace(traveled_km,',','') AS DOUBLE)           AS traveled_km,  -- FIX: defensive
  to_timestamp(TRY_CAST(replace(actual_start_epoch,',','') AS BIGINT))
      AT TIME ZONE 'UTC'                                    AS actual_start_utc,  -- FIX: TZ
  ...
FROM read_csv('.../Ride_data*.csv', header=true, union_by_name=true,
              null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1);
```

Join rule: **never** `USING (trip_id)` alone.

```sql
FROM trips t JOIN bill b ON t.trip_id = b.trip_id AND t.business_unit = b.business_unit
-- 614,800 rows, ₹826,459,283.95, zero fan-out
-- vs USING(trip_id): 628,551 rows, ₹844,880,382.27 (+₹10,903,610.98 phantom spend)
```
