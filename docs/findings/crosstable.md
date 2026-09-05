# Cross-Table Causal Links — findings

Scripts (all run, all numbers below are pasted from real output):
`tools/analysis/crosstable_base.py` (views) · `crosstable.py` · `crosstable2.py` · `crosstable3.py` · `crosstable4.py` · `crosstable5.py` · `crosstable6.py`

**Join key used everywhere: `(TRY_CAST(replace(trip_id,',','') AS BIGINT), business_unit)`.** See F7 for why `trip_id` alone is wrong.

Base join coverage:

```
j                        nn
-----------------------  -------
trips->bill              614,800
trips no bill            746
bill no trip             5,982
trips->fb(distinct)      298,437
trips->alerts(distinct)  33,229
trips->emp(distinct)     615,546
```

---

## F1 — HIGH — "On-Time Arrival 95%" is an operator-entered code, not a measurement. Three tables give three different answers.
**Persona: facilities_head (the SLA number in the contract is not measuring what it claims), transport_manager**

`delay_minutes` is exactly `0` for **100.00%** of NODELAY rows, and NODELAY is **555,237 / 615,546 = 90.2%** of all trips:

```
delay_reason  n        pct_zero
------------  -------  --------
NODELAY       555,237  100.000
TRAFFIC       23,274   0.000
EMPLOYEE      20,476   0.000
DRIVER        16,559   0.000
```

It is not derived from the timestamps in the same row (n=615,546):

```
n        vs_END  vs_START  mean_end_late  mean_start_late
-------  ------  --------  -------------  ---------------
615,546  18.030  10.520    11.030         -2.770
```
Mean absolute gap of 18.03 min against end-epoch lateness, 10.52 min against start; only **4.75%** of rows match end-lateness within 1 minute. So `delay_minutes` is a dispatcher's delay code, and "OTA" = "share of trips nobody coded a delay reason on".

Rebuild OTA three independent ways:

```
month       n        reported_ota  epoch_derived_ota  med_end_late
----------  -------  ------------  -----------------  ------------
2026-05-01  188,992  95.310        46.890             6.420
2026-06-01  210,669  92.460        41.070             9.280
2026-07-01  215,885  94.690        46.010             6.770
```
```
RIDER-LEVEL pickup OTA (emp_data, 1.33M rider legs)
month       n_riders  rider_pickup_ota  avg_delay  med_delay
----------  --------  ----------------  ---------  ---------
2026-05-01  403,033   72.120            -0.440     1.330
2026-06-01  457,576   69.300            0.470      1.730
2026-07-01  474,345   71.270            0.010      1.570
```

**95% / 47% / 71%.** And on the *same trips*, trip-level delay barely relates to what riders felt:

```
month       n_trips  trip_ota  rider_pickup_ota  corr_tripdelay_riderdelay
----------  -------  --------  ----------------  -------------------------
2026-05-01  187,154  95.340    71.200            0.032
2026-06-01  208,612  92.460    68.360            0.091
2026-07-01  214,420  94.750    70.690            0.140
```

**Artifact check — is the epoch version just a bad plan baseline?** Partly: cabs *start* 2.77 min early on average and *end* 11.03 min late, so the plan under-books run time. But that is exactly the point — the systematic ~6-9 min median overrun is invisible in the reported metric. And the direction is consistent across all three: NODELAY trips still only make 49.22% epoch-OTA while TRAFFIC makes 0.02%, so the delay code does carry real signal, it just fires ~10x too rarely.

**Confirms and amplifies finding A.** The June dip is real in all three measurements, and *bigger* than reported: reported −2.85pt, epoch-derived **−5.82pt** (46.89→41.07), rider-level **−2.82pt** (72.12→69.30). All three recover in July.

---

## F2 — HIGH — Finding A's June attribution is partly wrong at rider level. BUS is not the culprit; Denver is not the epicentre.
**Persona: transport_manager**

Finding A (trip-level): BUS −6.25 vs CAB −2.20; Denver −4.15, Clearwater −4.07. Rider-level pickup punctuality from `emp_Data` says something different:

```
product_type  may     jun     jul     swing   n_jun
------------  ------  ------  ------  ------  -------
CAB           70.870  68.010  70.370  -2.860  353,239
BUS           76.530  73.830  74.530  -2.700  103,788
```
BUS −2.70 vs CAB −2.86 — **CAB is marginally worse**, and BUS is the segment that fails to recover in July (74.53 vs 76.53 May). The BUS story is a trip-completion story, not a rider-pickup story.

```
business_unit  office               may     jun     jul     jun_swing  n_jun
-------------  -------------------  ------  ------  ------  ---------  -------
pinnacle-Slc   Ashford Commons      66.190  61.530  67.470  -4.660     1,019
vanta-Aus      Cedar Ridge Office   86.440  83.020  82.120  -3.420     51,851
pinnacle-Slc   Willow Bend Campus   53.120  49.830  54.730  -3.290     40,625
pinnacle-Slc   Clearwater Campus    46.640  43.490  49.510  -3.140     75,795
vanta-Sea      Denver Office        89.560  88.150  88.830  -1.410     156,139
catalyst-Sac   Crestwood Campus     76.210  82.060  84.550  5.840      8,160
```
Clearwater confirms (−3.14). **Denver is only −1.41 at rider level vs −4.15 at trip level** — Denver's June problem was trips finishing late, not riders being picked up late. New name in the frame: **vanta-Aus Cedar Ridge (−3.42, n=51,851) never recovers** (82.12 in July, below both May and June) — that is a durable regression, not a June blip, and it is invisible in finding A.

Also note the rider-level *levels*: pinnacle-Slc runs at **45.87–50.75%** pickup punctuality all three months (n≈153k/month) while vanta-Sea runs at 88–90%. That structural gap dwarfs the June movement.

---

## F3 — HIGH — ₹15.5M of credit notes sit in `trip_cost` and invert the headline conclusion about driver delay.
**Persona: facilities_head**

The naive answer to "what does delay cost us", matched on contract+BU+month:

```
delay_reason  n       actual_spend    baseline_spend  excess          excess_per_trip
------------  ------  --------------  --------------  --------------  ---------------
TRAFFIC       22,669  35,378,776.000  34,217,141.000  1,161,636.000   51.240
EMPLOYEE      20,447  24,037,312.000  23,519,328.000  517,984.000     25.330
DRIVER        16,200  16,179,139.000  18,022,944.000  -1,843,805.000  -113.820
```
"Driver delay **saved** us ₹1.84M" — obviously wrong. It is **33 rows**:

```
NEGATIVE trip_cost in bill
n    tot              mn
---  ---------------  --------------
189  -15,502,798.000  -2,233,332.990

the 5 most negative billed trips
trip_id    business_unit  month       delay_reason  contract       vendor                tc
---------  -------------  ----------  ------------  -------------  --------------------  --------------
4,899,016  vanta-Sea      2026-05-01  DRIVER        6S-PREMIUMNEW  Meera Lebedev Travel  -2,233,332.990
4,898,283  vanta-Sea      2026-05-01  NODELAY       6S-PREMIUMNEW  Meera Lebedev Travel  -837,620.450
4,871,552  vanta-Sea      2026-05-01  NODELAY       6S-PREMIUMNEW  Meera Lebedev Travel  -232,598.360
```
189 negative rows totalling **−₹15,502,798**; **152 rows / −₹14,660,227** all on **Meera Lebedev Travel / vanta-Sea / 6S-PREMIUMNEW**, all in May. These are credit notes/adjustments stored in the same column as charges.

Re-run with `trip_cost >= 0`:

```
EXCESS spend, credits EXCLUDED (contract+BU+month matched)
delay_reason  n       actual_spend    excess         excess_per_trip
------------  ------  --------------  -------------  ---------------
TRAFFIC       22,663  35,603,166.000  1,081,753.000  47.730
EMPLOYEE      20,429  24,824,208.000  576,275.000    28.210
DRIVER        16,167  20,179,075.000  78,211.000     4.840
```
Tighter control (contract + **slab_name** + BU + month) shrinks it further and reorders it:

```
delay_reason  n       excess       per_trip
------------  ------  -----------  --------
EMPLOYEE      20,412  355,815.000  17.430
TRAFFIC       22,430  305,581.000  13.620
DRIVER        16,131  61,131.000   3.790
```

**The honest headline: delay is nearly free to us and expensive to riders.** Across ₹826M of billed spend over three months, *all* coded delay explains **₹0.72M–₹1.74M** depending on how tightly you control (0.09%–0.21%). Driver-caused delay costs ₹3.79–4.84 per trip. There is no "driver delay cost us X million" story — the cost of lateness is not in the invoice.

Also: **`trip_id = 'OverHead'`, 160 rows, ₹4,457,560** of spend with no trip attached (and a plain `CAST` crashes on it).

---

## F4 — HIGH — WOMAN_TRAVELLING_ALONE: the flagged woman rates safety 16x worse. Nothing else in the alert table comes close.
**Persona: facilities_head (duty of care / SLA), transport_manager (tonight's escort roster)**

```
ratings by alert event_type (n>=500 rating rows)
event_type                        n_ratings  safety  driver  route  pct_safety_le3
--------------------------------  ---------  ------  ------  -----  --------------
WOMAN_TRAVELLING_ALONE            649        4.562   4.548   4.492  12.173
VEHICLE_STOPPAGE                  3,284      4.846   4.846   4.805  1.736
EMPLOYEE_GEOFENCE_VIOLATION       9,468      4.870   4.870   4.848  1.405
EMPLOYEE_SIGN_OFF_TIME_VIOLATION  15,670     4.882   4.877   4.866  1.110
OVER_SPEEDING                     1,172      4.895   4.896   4.883  0.939
DEVICE_NOT_REACHABLE              4,768      4.896   4.889   4.883  1.007
ALL feedback baseline             512,873    4.888                  0.793
```

Mean ratings are useless here (ceiling: everything is 4.85±0.05). **Detractor rate (`safety_rating <= 3`) is the metric that moves**, and it moves 15x.

**Artifact checks, all four passed:**

1. *Is it just women rating lower?* No. Baseline by rater gender: MALE 4.900 / 0.764% detractor (n=318,984), FEMALE **4.867 / 0.842%** (n=193,750). The female baseline is essentially the global baseline.
2. *Female raters only, WTA vs not:* 4.640 / **9.000%** (n=200) vs 4.867 / 0.833% (n=193,550). Effect survives.
3. *Is it the whole cab, or her?* It is her:
```
g                         n    safety  pct_le3
------------------------  ---  ------  -------
the flagged rider         254  4.528   12.992
other rider on same trip  90   4.856   3.333
```
4. *Is it one BU?* No — vanta-Sea 28/197, vanta-Aus 4/43, pinnacle-Slc 1/14. Concentrated but not singular.

**Sample size, stated honestly.** The clean cell is **254 rating rows from 166 distinct riders across 256 trips** — below the 500-row bar. But the effect is not marginal: 33 detractors observed where **2.02** were expected.
```
WTA flagged-rider detractors: 33/254 = 12.992 %
baseline: 4069/512873 = 0.793 %
expected detractors under baseline: 2.02
one-sided binomial p = 2.6197959728063994e-29
rate ratio = 16.4 x
```
n is small because feedback coverage is low, not because the event is rare: **10,669 WTA alerts / 5,430 trips / 2,151 distinct women, 4.96 alerts per woman.**

**Actionable lever, with the caveat.** Escorts:
```
esc    n_trips  wta_trips  wta_per_1000
-----  -------  ---------  ------------
false  513,884  5,115      9.954
true   101,662  313        3.079
```
Treat as **directional only** — an escort on board may partly *define away* "travelling alone", so this is not a clean causal estimate. The defensible claim is the rating one.

---

## F5 — HIGH — No-shows cost us almost no extra rupees. They cost us 7.71% of the seats we bought.
**Persona: facilities_head**

The tempting finding:
```
cost by noshow count (RAW - confounded)
g   n        avg_cost   planned  actual
--  -------  ---------  -------  ------
0   528,246  1,306.940  2.200    2.220
1   65,886   1,505.430  3.520    2.790
2   14,097   1,720.820  5.470    3.760
3+  6,571    1,921.460  8.970    5.610
```
"Every no-show adds ~₹200 to the bill." **Wrong.** Control for contract and it reverses in 14 of 16 contracts:

```
contract           n        cost_no_ns  n_ns    cost_ns    delta
-----------------  -------  ----------  ------  ---------  --------
4Seater            150,834  1,038.800   3,135   969.830    -68.970
4S-150ORRNEW       73,835   1,417.930   10,840  1,365.440  -52.490
6S-150ORRNEW       36,011   1,786.800   14,325  1,689.590  -97.210
6S-HYD             23,790   1,505.570   8,093   1,377.280  -128.290
8SEATER_BTT_2025   4,109    1,617.540   1,532   1,505.860  -111.680
BUS-ORRNEW-TT      22,067   1,683.560   13,410  1,781.550  98.000
BUS-ORRNEW-SML     11,471   2,716.810   6,415   2,796.810  80.000
4S-EV-Z            47,447   1,242.790   8,706   1,239.100  -3.680
```
The raw gradient was pure confounding: trips with more no-shows are simply *bigger* trips (2.20 → 8.97 planned riders) on bigger, dearer contracts. Nobody bills us for an absent passenger.

**So the real cost is capacity, not cash.** 86,554 trips (14.08%) had ≥1 no-show; **118,026 of 1,530,025 planned seats (7.71%)** were bought and not used. Value that at each trip's own cost:

```
month       n        seats_noshow  spend            noshow_seat_value  pct_of_spend
----------  -------  ------------  ---------------  -----------------  ------------
2026-05-01  188,971  44,505        252,103,921.000  18,443,875.000     7.320
2026-06-01  210,406  42,888        282,039,867.000  17,350,423.000     6.150
2026-07-01  215,423  30,633        292,315,497.000  12,883,664.000     4.410
```
**₹48.68M of seat value over three months — and it is falling fast (7.32% → 6.15% → 4.41%).** State it as *notional* seat value: it is only recoverable by right-sizing vehicles, not by a credit note.

Where to right-size:
```
business_unit  office               n        seats   noshow_seat_value  pct_of_spend
-------------  -------------------  -------  ------  -----------------  ------------
vanta-Sea      Denver Office        179,650  77,567  31,387,522.000     11.230
vanta-Aus      Cedar Ridge Office   69,800   21,759  9,155,299.000      10.040
orbit-Slc      Lakeside Commons     21,063   6,532   2,645,351.000      9.310
pinnacle-Slc   Clearwater Campus    114,068  3,335   1,318,001.000      1.040
```
Two offices are 10-11x worse than Clearwater. **Denver Office alone is ₹31.4M / 64% of the total.**

Supporting: fleet occupancy is low everywhere, and cost-per-rider tracks it almost perfectly —
```
cab_capacity  n        planned  actual  occ_pct  avg_cost   cost_per_rider
------------  -------  -------  ------  -------  ---------  --------------
3             422,801  1.990    1.830   61.000   1,212.350  662.350
12            36,610   6.180    5.290   44.100   2,098.910  396.550
```
Best contract in the book: **5S_Jan2024_CNG_AC — 93.6% occupancy, ₹311.67/rider (n=3,791)**. Worst: **4S-WOW150ORRNEW — 48.0% occupancy, ₹1,354.34/rider (n=3,310)**, 4.3x more per seat delivered.

*(Checked and negative: there are zero "ghost trips" — `emp_actual` ranges 1..15 with no zeros or nulls across all 615,546 trips. We never pay for a completely empty cab.)*

---

## F6 — HIGH — Vendor scorecard: cost is flat, service is not. One vendor is bad on every single axis.
**Persona: transport_manager (primary), facilities_head**

22 vendors with n≥1,000 trips, credits excluded:

```
vendor_id                n_trips  ota     alerts_per_1000  drv_rating  cost_per_rider  occ_pct  spend_mn
-----------------------  -------  ------  ---------------  ----------  --------------  -------  --------
Meera Lebedev Travel     1,061    63.620  180.960          5.000       2,148.830       28.700   3.270
Pooja Mikhailov Travel   16,672   91.300  51.460           4.902       640.450         58.900   19.010
Rahul Orlov Travel       12,159   91.460  50.660           4.917       772.440         56.500   15.930
Amit Volkov Travel       10,954   92.060  43.270           4.899       633.760         59.200   12.420
Karan Mikhailov Travel   28,129   92.300  52.120           4.907       754.680         54.100   34.580
Aarav Mikhailov Travel   55,138   92.930  57.620           4.906       584.070         55.500   75.610
Sanjay Mikhailov Travel  74,174   93.480  62.230           4.894       567.430         56.000   109.660
Rohan Mikhailov Travel   66,548   95.010  52.890           4.897       564.440         63.800   86.220
Rahul Mikhailov Travel   36,409   95.450  30.400           4.876       536.990         59.400   42.690
Vikram Mikhailov Travel  24,942   97.190  82.190           4.830       508.640         74.800   39.800
Meera Pavlov Travel      15,557   98.660  32.400           4.748       513.360         64.900   20.130
Sneha Mikhailov Travel   19,319   98.730  37.220           4.800       522.380         65.800   24.200
```

**Artifact check — is raw OTA just route mix?** Yes, mostly. Index each vendor against its *own office+month* peers:
```
vendor_id                n       ota_vendor  peer_ota_same_office_month  ota_gap
-----------------------  ------  ----------  --------------------------  -------
Meera Lebedev Travel     1,007   63.850      92.700                      -28.850
Rahul Orlov Travel       12,072  91.580      92.760                      -1.180
Pooja Mikhailov Travel   16,546  91.800      92.710                      -0.910
...
Divya Sokolov Travel     9,801   94.570      92.660                      1.910
```
**Every vendor except one lands within ±1.91 points of its peers.** Vendor-vs-vendor OTA differences are route assignment, not vendor quality — which is consistent with prior finding D.

**The exception is real and it is a demo slide.** Meera Lebedev Travel, n=1,061:
- OTA **63.62%**, gap **−28.85pt** vs same office+month peers (n=1,007) — 15x the next-largest gap
- alert rate **180.96 / 1,000 trips** vs next-worst 82.19, fleet median ~52
- occupancy **28.7%** — 1.33 to 1.44 riders in a 5-seat cab, every month
- cost per rider **₹2,148.83** vs fleet ~₹560 — **3.8x**
- **sole-source**: it is the only vendor on 6S-PREMIUMNEW in vanta-Sea, so nobody benchmarks it
- it owns 98% of the ₹15.5M of credit notes in F3
- and it is *growing*: 168 trips in May → 337 in June → 386 in July at Denver Office
```
month       n    ota      contract       office               riders  cap    spend
----------  ---  -------  -------------  -------------------  ------  -----  -------------
2026-05-01  168  69.640   6S-PREMIUMNEW  Denver Office        1.440   5.050  544,607.000
2026-06-01  337  62.020   6S-PREMIUMNEW  Denver Office        1.390   5.010  1,045,256.000
2026-07-01  386  63.470   6S-PREMIUMNEW  Denver Office        1.330   5.000  1,132,139.000
```

**Artifact check — the satisfaction column is a lie, do not rank on it.** Feedback coverage varies 32x across vendors and drives the detractor rate:
```
vendor_id                n_trips  fb_coverage_pct  pct_detractor  n_ratings
-----------------------  -------  ---------------  -------------  ---------
Meera Lebedev Travel     1,061    2.920            0.000          31
Aarav Petrov Travel      15,095   3.430            3.656          547
Meera Pavlov Travel      15,557   4.000            5.873          647
Priya Mikhailov Travel   56,562   3.870            5.590          2,254
Vikram Mikhailov Travel  24,942   12.360           2.732          3,258
Rohan Mikhailov Travel   66,548   78.400           0.651          97,627
Divya Kozlov Travel      8,143    94.730           0.498          12,456
Amit Volkov Travel       10,954   94.810           1.003          17,654

corr(fb_coverage_pct, pct_detractor) = -0.727
```
When only 4% of riders rate, the ones who do are angry. **Meera Pavlov's "worst satisfaction" (5.873%) is selection bias, and Meera Lebedev's perfect 5.000 driver rating rests on 31 ratings from 2.92% coverage.** Any vendor satisfaction league table must be gated on coverage ≥ ~50% (which leaves 8 vendors, all clustered 0.50–1.16%).

**And the punchline for procurement:** on identical contract+BU+month, vendor pricing is essentially uniform.
```
COST INDEX vs peer avg on identical contract+BU+month (100 = par)
Rahul Orlov Travel       12,159  103.810   <- most expensive
...
Aarav Petrov Travel      15,095  97.190    <- cheapest
```
**A 6.6-point spread, top to bottom.** There is no cheap-but-terrible or expensive-but-excellent vendor — price is negotiated at the contract, not the vendor. So vendor selection is a *pure service decision*: switching away from Meera Lebedev buys ~29 points of OTA and 3.8x better cost-per-rider at par price.

---

## F7 — MEDIUM — `trip_id` is not unique. Joining on it alone inflates spend by ₹18.4M.
**Persona: facilities_head (any number built on a naive join is wrong)**

```
t       n          d(trip_id)  db(trip_id,BU)
------  ---------  ----------  --------------
trips   615,546    608,793     615,546
bill    620,782    613,783     620,782
emp     1,637,906  608,793     615,546
fb      512,873    298,321     298,521
alerts  51,699     33,474      33,478

trip_ids spanning >1 BU: 6,753 ids / 13,506 rows
```
```
FAN-OUT DAMAGE
j                     nn       tot
--------------------  -------  ---------------
join on trip_id ONLY  628,551  844,880,382.000
join on (trip_id,BU)  614,800  826,459,284.000
```
**+13,751 phantom trips and +₹18,421,098 (2.2%) of phantom spend** from one missing join column. `trip_id` is unique only *within* a business unit.

---

## Secondary results (real, ranked lower)

- **MEDIUM — Traffic delay is the most expensive delay and the most hated.** Excess ₹1,081,753 (₹47.73/trip, n=22,663) and the steepest satisfaction damage per minute: route rating loses **4.296 pts per 1,000 delay-minutes** vs EMPLOYEE 3.058 and DRIVER 2.799. Traffic-delayed trips also travel furthest (18.73 avg km vs 15.38 on NODELAY) — the excess is largely distance, not penalty.
- **MEDIUM — Rating damage is real but tiny until 30 minutes.** On-time 4.879 route vs late 4.819 (n=481,028 / 31,706). Only past 30 min does it bite: DRIVER delay 31-60 min → route 4.713 (n=1,203) vs 4.865 at 0-5 min (n=8,010). Mean ratings are a poor instrument; use detractor rate.
- **LOW — `alerts.severity` is unusable as-is.** `False` (15,037) and `NA` (16,348) together are **60.7% of 51,699 rows**, and severity is assigned inconsistently per event type: WOMAN_TRAVELLING_ALONE is `False` 6,750 / `Sev-3` 3,919 — the same event, two "severities", neither meaning anything. Severity cannot be used for triage; `event_type` can.
- **LOW — Three alert types have `stwid` = 1 distinct value** (DEVICE_NOT_REACHABLE, VEHICLE_STOPPAGE, OVER_SPEEDING, PANIC_FIXED_DEVICE, PANIC_DEVICE) — they are vehicle-level events with a placeholder rider id. Never join them to `emp_Data` on stwid.

## Checks that came back negative (worth knowing)
- **No ghost trips.** `emp_actual` min=1, max=15, zero nulls, zero zeros across 615,546 trips.
- **Alerts→ratings, in aggregate, is weak.** Alerted trips 4.871 safety vs 4.889 (n=23,769 / 489,104) — a 0.018 gap. It holds within BU (pinnacle-Slc 4.887 vs 4.905; catalyst-Sac 4.733 vs 4.828) but is only interesting once you split by `event_type` (F4). "Any alert" is not a useful predictor.
- **Vendor cost differentiation: none** (6.6pt index spread, F6).
