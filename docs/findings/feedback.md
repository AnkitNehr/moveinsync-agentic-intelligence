# Feedback & Sentiment — Findings

Script: `/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis/feedback.py`
Run: `.venv/bin/python tools/analysis/feedback.py [zero|resp|trend|cuts|delay|alerts|raters|confound|bias]`

Base: `trip_feedback.csv` = 512,873 rows, 298,321 distinct trips, 13,258 distinct raters.
All timestamps parse (512,873/512,873). `stwid=0` does **not** occur in this file (0 rows).
Every number below is pasted from an executed query; the query id (e.g. `1.2`) is the section label in the script.

---

## 0. Join-key correction applied to everything below

`trip_id` is **not unique in ride_data**. `(trip_id, business_unit)` is.

```
1.11  metric                         v
      ride rows                      615546
      distinct trip_id               608793
      distinct (trip_id,BU)          615546     <- unique
      trip_ids appearing 2x          6753
      fb rows                        512873
      fb JOIN ON trip_id only        528214     <- +15,480 phantom rows (+3.02%)
      fb JOIN ON trip_id+BU          512734
      fb rows on colliding trip_ids  15480
```

Colliding ids are genuinely different trips (different BU, office, vendor, date):

```
D3  trip_id  business_unit  office              trip_date   direction
    1208678  orbit-Slc      Eastgate Office     2026-05-01  LOGIN
    1208678  vanta-Aus      Cedar Ridge Office  2026-07-03  LOGIN
```

**All joins in this analysis use `(trip_id, business_unit)`.** Match rate 512,734 / 512,873 = **99.973%** (139 unmatched, `2.4`). Anyone joining feedback→rides on `trip_id` alone silently inflates by 3% and misattributes ~15k ratings to the wrong BU.

---

## FINDING 1 — `marshal_rating = 0` means "no marshal on the trip", not a zero score. Reporting it naively understates the metric by 4.49 points. — **HIGH** — facilities_head, transport_manager

Raw distribution (`1.2`) — marshal is nothing like the other four:

```
rating  route   driver  cab     safety  marshal
0       2       2       2       2       473692
1       3223    1805    1930    1855    207
2       944     758     738     708     65
3       1660    1613    1562    1504    120
4       44674   44991   44970   44944   4357
5       462370  463704  463671  463860  34432
```

The joint distribution settles it (`1.3`, `1.4`) — zeros are not scattered, they are *only ever* marshal:

```
zero_pattern  n_rows  pct       n_zero  n_rows  pct
....M         473690  92.36     0       39181   7.64
.....          39181   7.64     1      473690  92.36
RDCSM              2   0.00     5           2   0.00
```

Only **2 rows** in 512,873 are all-zero. There is no "unrated" population — every submitted row carries real scores on the other four dimensions.

**Confirmation against ride_data (`4.7`) — this is the decisive test:**

```
actual_escort  n       marshal_rated  pct_marshal_rated
False          473681  740            0.16
True            39053  38441          98.43
```

Marshal is rated on 98.43% of escorted trips and 0.16% of unescorted ones. `0` = no marshal was on board.

**Impact of getting the definition wrong (`1.8`):**

```
dim      incl_zero  excl_zero  n_zero  n
route    4.876      4.876      2       512873
driver   4.887      4.887      2       512873
cab      4.887      4.887      2       512873
safety   4.888      4.888      2       512873
marshal  0.371      4.857      473692  512873   <- 4.49-point error
```

Artifact check passed: marshal-zero rows are **not** unhappy rows. Their other ratings are *higher* than marshal-rated rows (`1.5`): route 4.879 / driver 4.890 vs 4.831 / 4.855. If 0 were a genuine bad score, the other dimensions would sag with it. They don't.

**Action:** `marshal_rating` must be filtered to `>0` and reported as "4.857 across 39,181 escorted trips", never averaged over all rows. The other four dimensions need no filter (2 rows).

**Small-n guard (`8.8`):** the hour-of-day cut shows `marshal = 5.0` at hours 8, 9, 10, 15, 16, 17. Those cells have n = 5, 7, 3, 1, 1, 1 marshal-rated rows. Noise — do not report.

---

## FINDING 2 — The company satisfaction score is a survey-coverage artifact. The BUs that respond least are the BUs that rate worst, and they are 29% of all trips. — **HIGH** — facilities_head

Response rate is not a gradient, it is **bimodal — 95% vs 4%** (`8.1`):

```
business_unit  trips   fb_rows  response_rate_pct  pct_of_TRIPS  pct_of_FEEDBACK  driver  driver_det_pct
orbit-Slc       48295  113811   95.65               7.85         22.19            4.8496  0.301
pinnacle-Slc   251774  381512   93.53              40.90         74.39            4.9030  0.427
catalyst-Sac    65214    8009   11.60              10.59          1.56            4.8308  2.185
vanta-Aus       70199    2771    3.85              11.40          0.54            4.7838  3.681
vanta-Sea      180064    6770    3.66              29.25          1.32            4.7570  4.638
```

Response rate and detractor rate are **perfectly rank-inverse across all 5 BUs**: 95.65 → 0.301%, down to 3.66 → 4.638%. A **15.4x** detractor spread.

**vanta-Sea is 29.25% of all trips and 1.32% of all feedback.** The two BUs that supply 96.6% of the feedback are the two with the lowest detractor rates.

Re-weighting by trips instead of by feedback volume (`8.2`):

```
driver_feedback_wtd  driver_trip_wtd  route_feedback_wtd  route_trip_wtd  det_feedback_wtd  det_trip_wtd
4.8875               4.8349           4.8758              4.7703          0.4997            2.2064
```

The headline detractor rate is **0.50% as measured, 2.21% as experienced — a 4.4x understatement.** Route mean drops 4.8758 → 4.7703.

**Artifact check — is this self-selection or a coverage gap?** Ran the direct test (`9.1`): compare objective quality of *rated* vs *unrated* trips inside each BU.

```
business_unit  grp      trips   pct_on_time  avg_delay_min  pct_gt60
catalyst-Sac   UNRATED   57652  97.70        0.53           0.09
catalyst-Sac   rated      7562  98.28        0.38           0.08
vanta-Aus      UNRATED   67496  98.49        0.27           0.02
vanta-Aus      rated      2703  98.82        0.20           0.00
vanta-Sea      UNRATED  173478  92.51        1.36           0.08
vanta-Sea      rated      6586  93.02        1.32           0.14
```

In the low-response BUs the rated sample is **objectively representative** (vanta-Sea 93.02% vs 92.51% on-time). So the low ratings are real, not an angry-minority artifact — the 3.66% sample is a fair sample. This is a *coverage* problem, not a *bias* problem, and it means vanta-Sea's 4.638% detractor rate should be believed and acted on.

Response rate is an office-level rollout gap, not random (`B3`): every orbit/pinnacle office is 78–96%, every catalyst office 7–12%, vanta 3.7–3.9%. `9.6` shows vanta-Sea has 1,783 raters averaging 3.8 submissions vs pinnacle's 7,105 averaging 53.7.

**Action:** never publish a blended satisfaction number. Publish per-BU with response rate attached, and fix vanta/catalyst feedback collection before trusting any trend.

---

## FINDING 3 — Ratings are decoupled from punctuality. The BU with the best on-time rate has the second-worst ratings. — **HIGH** — facilities_head, transport_manager

Sort BUs by objective on-time and the perceived quality does not follow (`9.3`):

```
business_unit  trips   objective_OTA_pct  fb_rows  driver_det_pct  route_det_pct
vanta-Aus       70199  98.50               2771    3.681           8.769
catalyst-Sac    65214  97.77               8009    2.185           5.269
orbit-Slc       48295  97.75             113811    0.301           0.577
vanta-Sea      180064  92.53               6770    4.638           7.282
pinnacle-Slc   251774  92.38             381512    0.427           0.616
```

- **vanta-Aus** has the **best** OTA (98.50%) and the **second-worst** driver detractor rate (3.681%).
- **pinnacle-Slc** has the **worst** OTA (92.38%) and the **second-best** detractor rate (0.427%).
- At effectively identical OTA (**92.53% vs 92.38%**), vanta-Sea's route detractor rate is **7.282% vs pinnacle's 0.616% — 11.8x.**

At trip level the correlation is essentially zero (`5.7`, n = 512,551):

```
corr(delay_minutes, rating):  driver -0.02936   route -0.03477   cab -0.03026
```

Delay *does* shift the group means (`5.1`: delayed 4.8453 vs on-time 4.8902 driver; detractor 1.501% vs 0.434%) and the dose-response is monotonic through 31–60 min (`5.2`: route 4.8802 → 4.7238). But r ≈ −0.03 means punctuality explains ~0.1% of rating variance. **Statistically real, operationally irrelevant.**

**Artifact check — is the BU gap just a feedback-timing/mechanism difference?** Submission lag is also bimodal (`9.4`): orbit 9.02h / pinnacle 6.58h median, vs catalyst 1.05h / vanta-Sea 0.78h / vanta-Aus 0.67h. Fast submissions *are* harsher within every BU (`9.5`, pinnacle: 0.220% at 6h+ vs 1.681% at <1h). But holding the lag band constant, the BU gap survives almost intact:

```
9.5  lag_band  business_unit  n      driver  det_pct
     c 1-6h    pinnacle-Slc   131862 4.8984  0.537
     c 1-6h    orbit-Slc       21211 4.8433  0.599
     c 1-6h    catalyst-Sac     4017 4.8220  2.340
     c 1-6h    vanta-Aus         849 4.7114  5.771
     c 1-6h    vanta-Sea        2311 4.6798  5.971    <- 11.1x pinnacle at matched lag
```

The BU difference is real, not a timing artifact. **Something other than punctuality drives satisfaction** — do not manage employee experience through the OTA dashboard.

---

## FINDING 4 — pinnacle-Slc's unrated trips are its worst trips, and pooling hides it (Simpson's paradox). — **HIGH** — transport_manager

```
9.2  scope_name         grp      trips   pct_on_time  avg_delay
     ALL BUs pooled     UNRATED  317109  94.50        1.68
     ALL BUs pooled     rated    298437  93.70        1.65
     pinnacle-Slc only  UNRATED   16380  87.59       15.08
     pinnacle-Slc only  rated     235394  92.72        1.97
```

Pooled, unrated trips look **better** (94.50% vs 93.70% on-time) — you would conclude there is no response bias. Inside pinnacle-Slc the unrated 6.5% average **15.08 minutes of delay vs 1.97 — 7.7x**, and 2.48% exceed 60 minutes vs 0.17% (**14.6x**, `9.1`).

The pooled view is dominated by vanta-Sea's 173,478 unrated-but-normal trips, which drown out pinnacle's 16,380 unrated-and-terrible ones.

**So even pinnacle's 4.903 / 0.427% detractor is optimistic** — its worst trips are systematically the ones that never get rated. The employees on a 60-minute-late trip are the least likely to fill in the form.

**Action:** treat "trip completed, no feedback, delay > 30 min" as a proactive follow-up queue. In pinnacle-Slc that is 4.30% of unrated trips (`L2`, pct_delay_gt30).

---

## FINDING 5 — The mean rating is a dead metric (90% are 5-star). Use detractor rate — it is ~100x more sensitive. — **HIGH** — facilities_head, transport_manager

The known June operational dip is nearly invisible in the mean, and obvious in the detractor rate (`8.6`):

```
month       n       route_mean  pct_5star  det_pct  n_detractors
2026-05-01  148382  4.8818      90.530     0.736    1092
2026-06-01  174294  4.8722      90.058     0.896    1562
2026-07-01  190197  4.8743      89.947     0.795    1513
```

May → June: **mean moves −0.0096 (−0.20% relative). Detractor rate moves +0.160pt (+21.7% relative).** Same underlying event, ~100x difference in sensitivity. Then it partially recovers in July (0.795), mirroring the campus OTA recovery.

**Route is both the lowest-rated and the most volatile dimension** across all three months (`3.1`, `3.3`) — it is the only dimension worth trending:

```
3.1  month       route   driver  cab     safety  marshal  n_marshal
     2026-05-01  4.8818  4.8916  4.8913  4.8922  4.8508   11907
     2026-06-01  4.8722  4.8851  4.8842  4.8855  4.8570   13038
     2026-07-01  4.8743  4.8864  4.8857  4.8867  4.8610   14236

3.3  month       route_det  driver_det  cab_det  safety_det  marshal_det
     2026-05-01  0.736      0.466       0.479    0.467       0.840
     2026-06-01  0.896      0.556       0.584    0.555       0.736
     2026-07-01  0.795      0.474       0.494    0.475       0.534
```

Route detractors rose +21.7% in June vs driver +19.3%, cab +21.9%, safety +18.8% — and route sits at 1.6–1.9x the absolute level of the others every month. Marshal is the only dimension improving monotonically (4.8508 → 4.8570 → 4.8610; detractor 0.840 → 0.736 → 0.534, **−36.4%**).

**The five dimensions are barely five dimensions** (`5.6`, n = 512,871):

```
route_driver  route_cab  driver_cab  driver_safety  cab_safety
0.8526        0.8601     0.9420      0.9539         0.9522
```

driver/cab/safety inter-correlate at **0.94–0.95** — employees give one score three times (halo effect). Route is the only semi-independent signal at 0.85. **The survey is really ~2 questions: "was the route right" and "was everything else OK".**

Where the June route spike landed (`8.7`):

```
trip_direction  product_type  n       may_det  jun_det  jul_det
LOGIN           BUS            47748  0.629    0.737    0.714
LOGIN           CAB           203451  0.647    0.910    0.855
LOGOUT          BUS            10611  0.702    0.871    0.869
LOGOUT          CAB           250410  0.830    0.916    0.762
```

LOGIN/CAB moved most (+0.263pt, **+40.6% relative**) and stayed elevated into July (0.855). Worth flagging: the known OTA dip was attributed to BUS ≫ CAB, but the *perception* damage is concentrated in LOGIN **CAB**, and LOGOUT/BUS is the only cell that hasn't recovered at all (0.871 → 0.869).

---

## FINDING 6 — At matched delay length, a TRAFFIC delay costs 0.094 route points more than a DRIVER delay — the opposite of the intuitive result. — **MEDIUM** — transport_manager

Naive cut (`5.3`) already hints at it, but is confounded — TRAFFIC delays are longer (18.74 vs 16.45 min):

```
reason    n       avg_delay_min  driver  route   cab     safety  driver_det_pct
TRAFFIC     7800  18.74          4.8397  4.7997  4.8354  4.8424  1.372
DRIVER     21454  16.45          4.8500  4.8342  4.8493  4.8528  1.464
EMPLOYEE   28935   7.85          4.8726  4.8564  4.8727  4.8737  0.944
NODELAY   454545   0.00          4.8910  4.8802  4.8904  4.8912  0.411
```

Stratifying by delay bucket removes the confound (`8.5`). The 16–30 min bucket is a near-perfect natural experiment — **21.1 vs 21.3 avg minutes**:

```
bucket   delay_reason  n     avg_min  route   driver
c 6-15   TRAFFIC       2874    9.7    4.8198  4.8553
c 6-15   DRIVER        8094    9.7    4.8352  4.8536
c 6-15   EMPLOYEE      9758    9.2    4.8493  4.8687
d 16-30  TRAFFIC       1449   21.1    4.7177  4.7854
d 16-30  EMPLOYEE      2883   20.9    4.8096  4.8456
d 16-30  DRIVER        3869   21.3    4.8116  4.8219
e 31+    DRIVER        1481  114.5    4.7232  4.7718
e 31+    TRAFFIC        583  135.7    4.7307  4.8130
e 31+    EMPLOYEE       715   50.8    4.7902  4.8182
```

At **identical delay magnitude (21.1 vs 21.3 min)**: TRAFFIC route **4.7177** vs DRIVER **4.8116** — a **0.094-point penalty for the cause the operator cannot control.** Same direction in the 6–15 bucket (4.8198 vs 4.8352, 0.015pt at 9.7 min both).

Note the split personality: TRAFFIC is worse on **route** rating, DRIVER is worse on **driver** rating (4.8219 vs 4.7854 reverses). Employees do attribute correctly — they blame the route for traffic and the driver for the driver. EMPLOYEE-caused delays are consistently the most forgiven on both.

**Action:** the "DRIVER delay is the expensive one" assumption is wrong for route satisfaction. Route re-planning on chronically congested corridors buys more perceived quality than driver discipline, per minute of delay removed.

---

## FINDING 7 — Employees cannot perceive over-speeding. Safety ratings are unusable as a safety KPI. — **MEDIUM** — facilities_head

```
8.9  grp              n       safety  safety_det_pct
     none             511727  4.8879  0.500
     OVERSPEED_ALERT    1146  4.8988  0.436
```

Trips with a telemetry-confirmed `OVER_SPEEDING` alert score **higher** on safety (4.8988 vs 4.8879) and have a **lower** safety detractor rate (0.436% vs 0.500%). n = 1,146 — above the noise floor, and the effect is directionally *wrong*, not merely absent.

Consistent across the alert taxonomy (`6.3`) — `OVER_SPEEDING` is the **least** damaging alert type of all five:

```
event_type                        n     trips  driver  safety  route   cab
VEHICLE_STOPPAGE                  3153  1682   4.8462  4.8452  4.8059  4.8405
EMPLOYEE_GEOFENCE_VIOLATION       6100  3482   4.8603  4.8593  4.8354  4.8603
EMPLOYEE_SIGN_OFF_TIME_VIOLATION  8992  4753   4.8778  4.8838  4.8672  4.8829
DEVICE_NOT_REACHABLE              4617  2936   4.8898  4.8943  4.8839  4.8941
OVER_SPEEDING                     1146   742   4.8997  4.8988  4.8866  4.8997
```

What employees *do* notice is **time**: `VEHICLE_STOPPAGE` is the worst (route 4.8059), and route is the dimension it hits hardest. Speed is invisible to them; stopping is not.

Alerts overall do depress ratings, and it is not just a delay artifact (`6.6` — holding on-time constant):

```
on_time  grp        n       avg_delay  safety  driver
0        HAS_ALERT    2868  29.76      4.8407  4.8365
0        no_alert    28838  19.74      4.8486  4.8462
1        HAS_ALERT   20893   0.32      4.8749  4.8732
1        no_alert   460135   0.14      4.8912  4.8910
```

Among **on-time** trips, alert trips still rate 4.8749 vs 4.8912 safety. Real but small (0.016pt).

**Action:** do not use `safety_rating` to monitor driving safety — it measures punctuality perception, not risk. Over-speeding must be governed by telemetry alone.

---

## FINDING 8 — The 13.5x vendor rating spread collapses to 2.0x once you control for BU. Most of "vendor quality" is BU mix. — **MEDIUM** — facilities_head

Raw vendor cut (`4.1`, n ≥ 500) looks damning — detractor rate spans **0.309% → 4.173%, 13.5x**, while the means differ by only 0.16:

```
vendor_id                n      driver  driver_sd  route   driver_det_pct
Meera Pavlov Travel        647  4.7527  0.8332     4.5641  4.173
Priya Mikhailov Travel    2254  4.7733  0.8075     4.6491  4.126
Isha Mikhailov Travel     1159  4.7921  0.7634     4.7049  3.710
Sneha Mikhailov Travel     708  4.7938  0.7614     4.6808  3.672
...
Divya Kozlov Travel      12458  4.9121  0.3487     4.9059  0.345
Rahul Orlov Travel       18471  4.9129  0.3400     4.9031  0.309
```

**Artifact check (`8.3`) — every "bad" vendor operates exclusively in the low-response, harsh-rating BUs:**

```
vendor_id               business_unit  n      driver
Meera Pavlov Travel     vanta-Aus        647  4.7527
Isha Mikhailov Travel   vanta-Sea       1159  4.7921
Sneha Mikhailov Travel  vanta-Aus        708  4.7938
Priya Mikhailov Travel  vanta-Sea       1269  4.7384
Priya Mikhailov Travel  vanta-Aus        592  4.7838
Priya Mikhailov Travel  catalyst-Sac     393  4.8702
Divya Kozlov Travel     pinnacle-Slc   12458  4.9121
Rahul Orlov Travel      pinnacle-Slc   18471  4.9129
```

There is **zero overlap** — the top and bottom vendors never operate in the same BU, so the raw ranking is uninterpretable. Note Priya Mikhailov Travel scores 4.7384 in vanta-Sea but 4.8702 in catalyst-Sac: **the same vendor moves 0.13 points depending on which BU is scoring it.**

Within pinnacle-Slc alone (`8.4`), the honest vendor effect:

```
business_unit  vendor_id                n      driver  driver_sd  det_pct
pinnacle-Slc   Anjali Mikhailov Travel    635  4.8976  0.4172     0.630
pinnacle-Slc   Amit Volkov Travel       17655  4.8963  0.4065     0.600
pinnacle-Slc   Divya Mikhailov Travel   25152  4.8940  0.4012     0.576
...
pinnacle-Slc   Rahul Morozov Travel     27924  4.9103  0.3454     0.322
pinnacle-Slc   Rahul Orlov Travel       18471  4.9129  0.3400     0.309
```

**True within-BU spread: 0.309% → 0.630% = 2.0x**, not 13.5x. Still actionable (Amit Volkov and Divya Mikhailov are ~1.9x the best performers on comparable volume), but a vendor scorecard built on the raw ranking would fire the wrong vendors.

**Dispersion is the better signal than the mean.** `driver_sd` rank-orders identically to detractor rate (0.3400 → 0.4172 within pinnacle; 0.34 → 0.83 raw). A vendor with sd 0.83 and mean 4.75 is failing a visible minority of riders; one with sd 0.34 and mean 4.91 is uniformly fine. **Report vendor sd and detractor rate, never the mean alone** — the means are separated by 0.16 across the entire vendor base and cannot support a decision.

---

## FINDING 9 — 70 chronic raters (0.53%) produce 20% of all low driver ratings, on objectively normal trips. — **MEDIUM** — transport_manager

Rater base (`7.1`): 13,258 raters, mean 38.68 submissions, median 35, max 208. No duplicate submissions — `(stwid, trip_id)` is unique across all 512,873 rows (`7.5`).

```
7.2  grp                raters  reviews  low_ratings  pct_of_all_lows  avg_reviews_per_rater
     a never_low        11706   438002   0             0.00            37.42
     b one_off (1 low)   1089    49171   1089         42.49            45.15
     c repeat (2-4)       393    21209    961         37.50            53.97
     d chronic (5+)        70     4489    513         20.02            64.13
```

**70 raters = 0.53% of the base = 20.02% of all low driver ratings.** Concentration confirmed independently (`7.3`): the top 1% of low-raters (16 people) generate 7.41% of all lows.

**Artifact check (`7.4`) — are they riding worse trips? Essentially no:**

```
grp           fb_rows  avg_delay_min  pct_on_time  avg_km
a never_low   437888   1.42           93.89        15.34
b one_off      49158   1.48           93.38        15.50
c repeat       21198   1.28           93.72        15.66
d chronic 5+    4488   1.35           91.91        16.18
```

Chronic low-raters experience **1.35 min average delay vs 1.42 for never-low-raters** — they are actually delayed *less*. On-time is 91.91% vs 93.89%, a 2.0pt gap on a slightly longer commute (16.18 vs 15.34 km), nowhere near enough to explain 5+ one-star ratings when 11,706 people on identical service never give one.

**This is a rater trait, not a service trait.** Also note the flip side: 42.49% of all lows come from 1,089 people who did it exactly once — those are the credible incident signals.

**Action:** exclude chronic raters from vendor/office scorecards (or cap one vote per rater per period), and route **one-off** lows from never-low raters to follow-up — that is where a real incident is most likely.

---

## Secondary observations (LOW, but worth knowing before building anything)

- **2.64% of feedback (13,538 rows) is timestamped BEFORE the trip it rates** (`2.5`), concentrated in the low-response BUs (`9.4`): vanta-Aus **23.85%**, vanta-Sea 12.47%, catalyst-Sac 10.63%, vs pinnacle-Slc 0.87%. Combined with the bimodal median lag (0.67–1.05h vs 6.58–9.02h), this is strong evidence that **two different feedback capture mechanisms are in play**. Don't compute "response latency" across BUs as if it were one metric.
- **Response rate is rising**: 47.04% → 48.22% → **50.03%** of trips rated (`2.1`), with responses-per-rated-trip also up 1.669 → 1.761. Any month-over-month rating comparison is contaminated by a changing sample. Marshal coverage is stable though (91.98% / 92.52% / 92.52% zero, `3.4`), so the marshal trend is clean.
- **`is_driver_nc = True` trips rate HIGHER** (`5.5`): driver 4.9107 vs 4.8874, n = 773. Small n and counterintuitive — flagging as *unexplained*, not as a finding. `is_cab_nc = True` never reaches n ≥ 500.
- **`severity` join is unusable as-is** (`6.4`): the 23,769 alert-linked feedback rows split into `NA` 13,860, the literal string `False` 6,646, `Sev-3` 3,799, `Sev-1` 76, `Sev-2` 63. Only 3,938 rows carry a real severity. Sev-1/Sev-2 are below the noise floor — do not rank by severity.
- **BUS underperforms CAB** (`4.3`): driver 4.8430 vs 4.8932, route 4.8345 vs 4.8811, n = 58,359 vs 453,861. `SPOT_2.0` n = 514, at the floor — report with caution.
- **Worst offices** (`4.2`, n ≥ 500): Denver Office (route **4.6674**, n = 6,764), Crestwood Campus (4.6845, n = 1,233), Santa Clara Office (4.6849, n = 5,081) — all in the low-response BUs, so subject to the same Finding 8 caveat. Fairview Commons shows route 4.7333 against safety 4.9218 (n = 1,125), the largest route-vs-safety gap of any office.
- **`safety_rating` vs `marshal_rating` on night trips: no meaningful gap** (`4.6`). NIGHT(22–05) escorted: safety 4.8584 vs marshal 4.8590 (difference −0.0006, n = 21,485). The only non-trivial gap is DAY/unescorted (+0.0592) and that is computed over just 740 marshal-rated rows out of 440,425 — noise. **Escorted night trips do not rate their marshal differently from their overall safety**, which is consistent with the 0.95 halo correlation in Finding 5.

---

## Recommended metric definitions

1. Join feedback→rides on **`(trip_id, business_unit)`**, never `trip_id`.
2. `marshal_rating`: filter `> 0`, report with its own n. Others: no filter needed.
3. Headline KPI = **detractor rate (ratings 1–2)**, not mean. Mean is saturated at 90% 5-star.
4. Always publish **response rate beside the score**, and prefer **trip-weighted** aggregation across BUs (0.50% → 2.21% detractor).
5. Trend **`route_rating`** — it is the lowest, most volatile, and least redundant dimension. driver/cab/safety are one number (r = 0.94–0.95).
6. Vendor and office comparisons must be **within-BU**, using **detractor rate and sd**, at n ≥ 500.
