# Timeliness & Operations — findings

**Source:** `data/raw/Ride_data*.csv` (615,546 trips, 2026-05-01 → 2026-07-31, 92 days)
**Script:** `tools/analysis/timeliness.py` (stages 0–10; every number below is pasted from a run)
**Reproduce:** `./.venv/bin/python tools/analysis/timeliness.py <0..10>` (stage 0 builds the table first)

Base table checks: 615,546 rows, 615,546 trip_ids parse, 100 distinct `shift_type`, 0 null/blank shift_type,
`planned/actual start/end epoch` non-null on all 615,546 rows.

---

## Finding 1 — `delay_minutes` measures a *different event* for LOGIN vs LOGOUT trips, and the LOGOUT definition makes the evening fleet un-auditable

**Rank: HIGH** · **Persona: facilities_head** (the SLA you sign is not the SLA you think) + **transport_manager**

The on-time metric is not one metric. Regressing `delay_minutes` against both epoch deltas
(stage 9a, SPOT_2.0 excluded):

| direction | n | % exactly = max(0, END dev) | % exactly = max(0, START dev) | corr END | corr START |
|---|---|---|---|---|---|
| LOGIN  | 282,851 | 45.62 | 36.57 | **0.81** | 0.15 |
| LOGOUT | 330,372 | 24.82 | **63.72** | 0.07 | **0.71** |

LOGIN lateness is scored on **arrival at the office**. LOGOUT lateness is scored on **departure from the
office** — it correlates with the actual-vs-planned *end* time at only **0.07**. For a LOGOUT trip, once the
cab pulls out of the campus gate on time, the trip is on-time forever, no matter how long the ride home takes.

The consequence is visible directly (stage 9b, CAB LOGOUT only):

| riders | n | reported OTA | mean END dev (min) | p50 | p90 | mean ride (min) |
|---|---|---|---|---|---|---|
| 1 | 84,231 | 95.67 | 3.77 | 3.97 | 28.77 | 46.9 |
| 2 | 94,753 | 96.98 | 14.10 | 13.63 | 39.57 | 55.8 |
| 3 | 77,321 | 97.98 | 22.40 | 19.03 | 53.35 | 65.1 |
| 4 | 33,076 | **99.66** | **38.22** | 30.50 | 88.40 | 78.5 |
| 6 | 4,655 | 99.38 | 38.34 | 30.22 | 86.02 | 71.1 |

**Reported OTA and actual arrival deviation move in opposite directions.** A 4-passenger evening drop scores
99.66% on-time while finishing 38 minutes past its planned end. The LOGIN mirror (stage 9c) shows no such
inversion — end dev stays between −0.78 and +4.87 min across 1–6 riders — which is exactly what you'd expect
if LOGIN is genuinely scored at arrival.

**Artifact check performed.** Three alternatives ruled out:
1. *Is `delay_minutes` mis-parsed?* No — for the 444 trips >240 min, `corr(delay_minutes, epoch end dev) = 1.00`
   (stage 3f). The column is internally consistent with the epochs.
2. *Is the epoch data junk?* No — 615,546/615,546 non-null, planned start range 2026-05-01 05:30 → 2026-08-01 05:15,
   0 negative actual durations, only 2–9 negative planned durations per month (stage 4a/4b).
3. *Is this just occupancy confounding?* No — held inside a single `cab_capacity=4` fleet, occupancy barely moves
   reported OTA (97.73 / 98.08 / 97.28 / 97.53 for 1/2/3/4 riders, stage 7l). The inversion is specific to the
   LOGOUT *metric*, not to crowding.

**Honest framing:** end-deviation conflates "the cab ran late" with "the roster's planned duration was
unrealistic" (mean planned duration 42.72 → 46.40 min vs mean actual 55.40 → 58.82 min across the three months,
stage 4c). Either reading lands in the same place — **employees are in the vehicle materially longer than the
published plan, and no current KPI records it.**

**Scale (stage 9d, 10e, 10f):**

| | May | Jun | Jul |
|---|---|---|---|
| LOGOUT employee-hours beyond planned end | 100,924 | 120,413 | 105,150 |
| LOGOUT min beyond plan per seat | 24.71 | 26.31 | 22.16 |
| LOGOUT reported OTA | 97.66 | 96.89 | 97.94 |
| LOGIN employee-hours beyond planned end | 21,204 | 34,897 | 28,292 |
| LOGIN min beyond plan per seat | 6.61 | 9.48 | 7.49 |

Across all trips ex-SPOT: **410,879 employee-hours beyond planned end in 3 months, 17.07 min per seat**
(n = 613,223 trips, 1,444,532 seats). The direction reporting the *best* OTA carries **2.8–3.7× the hidden
cost per seat** (24.71/6.61, 26.31/9.48, 22.16/7.49 by month).

**Worst single cell** — CAB / LOGOUT / 16:00–20:59 (stage 10e):

| month | n | reported OTA | epoch OTA | mean end dev | p90 end dev | emp-hrs beyond plan |
|---|---|---|---|---|---|---|
| May | 31,404 | 97.83 | 20.21 | 25.91 | 62.10 | 43,216 |
| Jun | 33,681 | 96.28 | 16.30 | 29.76 | 68.20 | 51,373 |
| Jul | 33,434 | 97.52 | 17.17 | 26.82 | 62.00 | 45,311 |

**Action:** publish a second KPI — *last-drop adherence* (`actual_end` vs `planned_end`) — alongside OTA.
Today's OTA cannot fail on the evening fleet.

---

## Finding 2 — 122,210 trips (19.9% of volume) sit on shift codes that are structurally incapable of recording lateness, inflating headline OTA by ~1.3–1.8 pts

**Rank: HIGH** · **Persona: facilities_head** (data trust / vendor scorecard integrity)

`shift_type` splits cleanly by **minute suffix** (stage 1f):

| minute suffix | distinct shifts | n | reported OTA | mean delay | max delay | % delay exactly 0 |
|---|---|---|---|---|---|---|
| `:00` | 24 | 252,173 | 91.66 | 1.47 | 1,275 | 86.37 |
| `:30` | 24 | 225,455 | 94.41 | 1.01 | 698 | 90.00 |
| **`:16`** | 24 | **87,546** | **100.00** | **0.00** | 38 | **99.99** |
| **`:15`** | 24 | **34,664** | 99.64 | 0.10 | 72 | 99.51 |
| (Non Shift / Adhoc) | 2 | 14,799 | 83.50 | 28.56 | 10,644 | 78.44 |
| `:01` | 1 | 810 | 98.02 | 0.29 | 26 | 96.67 |
| `:45` | 1 | 99 | 97.98 | 0.20 | 9 | 94.95 |

Twenty-four separate `:16` shift codes (`00:16` … `23:16`) report **exactly 100.00%** on-time across 87,546 trips.
That is not an operational result; that is a measurement gap.

**Artifact check performed — and it is a real gap, not synthetic rows.** These trips have full epoch and km data
(stage 1h/8e): 0.00% null actual_end, 0.00% null delay, mean traveled_km 16.32 (vs 15.29 for normal trips), mean
riders 2.69 (vs 2.27). They are *more* loaded than average. And by the timestamps they arrive **later** than
average (stage 8e):

| group | n | reported OTA | epoch OTA | mean END dev | mean START dev |
|---|---|---|---|---|---|
| normal | 493,336 | 92.68 | 46.32 | 10.74 | +0.65 |
| `:15`/`:16` | 122,210 | **99.89** | **37.59** | **12.21** | **−16.58** |

The mechanism connects to Finding 1: **these are 100% LOGOUT trips** (stage 8f — 76,082 CAB `:16`, 34,664 CAB `:15`,
11,464 BUS `:16`; zero LOGIN). They depart **16.6 minutes early** on average, so under the departure-based LOGOUT
rule they can never be late — while arriving 12.2 min past plan, worse than the fleet average.

**Effect on the headline number (stage 1i):**

| month | `:15`/`:16` trips | % of month | headline OTA | OTA excluding them |
|---|---|---|---|---|
| May | 40,103 | 21.22 | 95.31 | **94.05** |
| Jun | 40,775 | 19.36 | 92.46 | **90.71** |
| Jul | 41,332 | 19.15 | 94.69 | **93.44** |

**Action:** exclude `:15`/`:16` codes from vendor OTA scorecards or re-score them on arrival. One fifth of the
fleet is currently graded on a test it cannot fail.

---

## Finding 3 — The "June dip" is a 5-week slide that starts in mid-May, and it is confined to LOGIN trips in daytime shift bands

**Rank: HIGH** · **Persona: transport_manager** (where to put crew) + **line_manager** (which shifts to warn)

Monthly reporting (95.31 / 92.46 / 94.69) hides the actual shape. By ISO week (stage 2g, 9o):

| ISO wk | week start | n | reported OTA | epoch OTA (ex-SPOT) |
|---|---|---|---|---|
| 19 | 2026-05-04 | 46,807 | 96.86 | 50.51 |
| 20 | 2026-05-11 | 48,609 | 95.74 | 47.98 |
| 21 | 2026-05-18 | 49,267 | 94.29 | 41.84 |
| 22 | 2026-05-25 | 41,141 | 94.07 | 46.18 |
| **23** | **2026-06-01** | **47,322** | **89.44** | **37.58** |
| 24 | 2026-06-08 | 48,999 | 91.36 | 38.41 |
| 25 | 2026-06-15 | 48,172 | 93.73 | 42.06 |
| 26 | 2026-06-22 | 47,719 | 94.36 | 44.97 |
| 27 | 2026-06-29 | 47,237 | 95.02 | 45.47 |
| 28–31 | Jul | ~47k/wk | 93.86–95.39 | 43.78–48.88 |

Degradation begins **week 20 (11 May)**, three weeks before June, and troughs in week 23 at 89.44% — a **7.42 pt
fall from week 19**. Recovery takes four weeks and never fully returns (July oscillates 93.86–95.39%, below
week 19's 96.86%). Worst single day: **2026-06-02, 83.73% on 8,919 trips** (stage 2d).

**Artifact checks performed — the dip is real and not compositional:**
- *Shift-mix shift?* No. Reweighting every month to May's `shift_band` mix moves June from 92.46 → 92.54; on the
  full 100-cell `shift_type` mix, 92.46 → 92.47 (stage 7j/7k). Mix explains ~0.08 pts of a 2.85 pt drop.
- *Metric artifact?* No. The independent epoch-based OTA reproduces it: 46.98 → 41.14 → 46.13 (stage 9n).
- *Denominator change?* Volume rose (188,992 → 210,669) but offices 17→18, vendors 23→23, cabs 3,497→3,563 (stage 7h).

**Localization (stage 9i) — it is a LOGIN-side event:**

| shift_band | direction | n May | n Jun | May | Jun | Jul | Δ Jun |
|---|---|---|---|---|---|---|---|
| 10:00-15:59 | LOGIN | 38,590 | 41,869 | 91.42 | 85.03 | 89.50 | **−6.39** |
| 06:00-09:59 | LOGIN | 38,123 | 45,491 | 94.64 | 89.56 | 93.05 | **−5.08** |
| 16:00-20:59 | LOGIN | 6,389 | 7,034 | 90.55 | 88.48 | 90.79 | −2.06 |
| 16:00-20:59 | LOGOUT | 34,433 | 37,000 | 98.01 | 96.60 | 97.74 | −1.41 |
| 10:00-15:59 | LOGOUT | 27,130 | 31,489 | 97.38 | 96.51 | 97.99 | −0.86 |
| 21:00-23:59 | LOGOUT | 23,074 | 25,252 | 99.12 | 99.09 | 99.53 | −0.03 |
| 00:00-05:59 | LOGOUT | 12,629 | 13,538 | 95.95 | 96.05 | 96.71 | +0.09 |

Night bands are untouched. Per Finding 1, the LOGOUT rows *cannot* move much — their metric is departure-based —
so the honest statement is: **the dip is a morning/midday inbound problem.**

**Worst office × band in week 23 vs weeks 19–20 (stage 9j, all n≥500 in wk23):**

| office | band | wk23 OTA | n wk23 | wk19–20 OTA | n wk19–20 |
|---|---|---|---|---|---|
| Denver Office | 10:00-15:59 | **70.46** | 4,994 | 89.05 | 9,794 |
| Clearwater Campus | 16:00-20:59 | 78.70 | 1,014 | 94.27 | 1,953 |
| Clearwater Campus | 06:00-09:59 | 83.15 | 3,993 | 96.46 | 7,618 |
| Willow Bend Campus | 16:00-20:59 | 82.78 | 633 | 93.87 | 1,256 |
| Oakmont Office | 16:00-20:59 | 84.00 | 981 | 96.63 | 2,314 |

Denver Office daytime LOGIN collapsed 18.6 points in one week.

**Delay grew in frequency, not severity** (stage 3i/3j): late trips (>5 min) 8,856 → 15,894 → 11,470 (+79% in
June), while mean delay *given* lateness fell 36.28 → 22.87 min. June was a many-small-delays month.

---

## Finding 4 — 2,323 SPOT_2.0 trips (0.38% of volume) carry 38.9% of all delay minutes; ignoring this makes every minutes-based metric wrong, including the sign of June's trend

**Rank: HIGH** · **Persona: facilities_head** (governance of an unmanaged product line)

Stage 8g/8h:

| product | n | OTA | mean delay | mean planned dur | mean actual dur | delay minutes | % of all delay min |
|---|---|---|---|---|---|---|---|
| CAB | 513,580 | 95.40 | 0.8 | 42.7 | 55.2 | 433,848 | 42.26 |
| BUS | 99,643 | 88.84 | 1.9 | 53.0 | 70.0 | 193,261 | 18.82 |
| **SPOT_2.0** | **2,323** | **37.67** | **172.0** | **71.0** | **239.5** | **399,520** | **38.92** |

SPOT_2.0 is `route_source = RENTLZ`, `shift_type = 'Non Shift'`, 1.45 mean riders, and runs **3.4× its planned
duration**. Max delay 10,644 min (7.4 days) in May, 9,197 in June. These are open-ended rental bookings whose trip
record stays open, not late commutes.

**This is the artifact that would have produced a false headline.** The obvious finding —
*"the worst 1% of trips carry 37% of all delay minutes"* — does not survive (stage 10i):

| population | n (delay>0) | total delay min | % from worst 1% | % from worst 5% |
|---|---|---|---|---|
| ALL trips | 60,309 | 1,026,629 | **37.43** | 49.11 |
| EXCL SPOT_2.0 | 58,748 | 627,109 | **7.80** | 22.48 |

Removing 0.38% of trips collapses the concentration from 37.43% to 7.80%. **Delay in the real commute fleet is
diffuse, not concentrated** — there is no "fix 600 trips and you're done" lever. The correct finding is the
inverse of the tempting one.

**It also flips the sign of June's minutes trend** (stage 8q/8r):

| month | OTA | SLA-min lost/trip (ALL) | SLA-min lost/trip (ex-SPOT) | emp-min lost/seat (ex-SPOT) |
|---|---|---|---|---|
| May | 95.31 | 1.47 | **0.47** | 0.44 |
| Jun | 92.46 | **1.35** | **0.89** | 0.86 |
| Jul | 94.69 | 1.01 | **0.52** | 0.49 |

On raw data June looks *better* than May on minutes-per-trip (1.35 vs 1.47) — purely because May's single
10,644-minute SPOT booking dominates the sum. Excluding SPOT_2.0, June is **1.9× worse than May**, a bigger
relative deterioration than OTA (−2.85 pts) implies.

**Action:** exclude `product_type='SPOT_2.0'` from every delay/SLA aggregate, and govern it separately as a
rental-utilisation line, not a punctuality line.

---

## Finding 5 — Punctuality is a load problem: OTA falls monotonically with daily volume, and Tuesday runs 25% heavier than Friday for a 6.4-point OTA penalty every single week

**Rank: HIGH** · **Persona: transport_manager** (capacity planning) + **line_manager** (shift readiness)

Ranking each office's weekdays into within-office load quintiles (stage 9f) — this controls for office entirely:

| load quintile (within office) | office-days | mean trips/day | OTA |
|---|---|---|---|
| 1 (lightest) | 213 | 467 | **96.61** |
| 2 | 199 | 562 | 95.39 |
| 3 | 197 | 617 | 93.63 |
| 4 | 197 | 650 | 93.21 |
| 5 (heaviest) | 194 | 698 | **92.21** |

Perfectly monotonic, −4.40 pts from lightest to heaviest. Per-office correlation of daily trips vs daily OTA
(weekdays, 66 days each, stage 9e) is negative in 12 of 15 offices: Clearwater −0.50, Ashford −0.47,
Eastgate −0.45, Crestwood −0.40, Denver −0.39, Lakeside −0.38, Willow Bend −0.29.
**Not universal** — Cedar Ridge +0.10 and Santa Clara +0.01 are flat, and both are high-OTA sites, so load
tolerance is achievable.

**The day-of-week signature (stage 9g, weekdays only):**

| day | n | trips/day | seats/day | mean riders | OTA |
|---|---|---|---|---|---|
| Wednesday | 129,105 | 9,931 | 24,285 | 2.44 | 92.91 |
| Tuesday | 127,009 | 9,770 | 24,047 | 2.46 | **91.25** |
| Thursday | 121,344 | 9,334 | 22,378 | 2.40 | 94.25 |
| Monday | 109,656 | 8,435 | 19,831 | 2.35 | 94.77 |
| Friday | 109,360 | 7,811 | 17,044 | 2.18 | **97.66** |

Friday carries **29% fewer seats/day** than Tuesday and scores **6.41 pts better**. This is a
return-to-office pattern (Tue/Wed peak, Friday light), and punctuality tracks it exactly.

**Artifact checks performed:**
- *Is it a June effect?* No — stable in all three months (stage 10g): Tuesday 92.27 / 89.82 / 92.00 vs
  Friday 97.97 / 97.08 / 97.88.
- *Is it one bad office?* No — the Tuesday<Friday gap holds in **all 11 offices with n≥500** (stage 8v), e.g.
  Denver 87.92 vs 98.01, Clearwater 87.93 vs 96.73, Willow Bend 91.91 vs 96.78, Cedar Ridge 96.68 vs 99.71.
- *Is it a shift-mix effect?* No — it concentrates exactly where load concentrates (stage 8x):
  10:00-15:59 Tuesday 3,392 trips/day → 87.78% vs Friday 2,792/day → 98.19%.
- *Weekend?* Weekend OTA is flat and unaffected across all three months: 96.04 / 96.62 / 96.61 (n = 7,194 /
  6,096 / 5,782, stage 2e). Only weekdays degrade: 95.29 / 92.33 / 94.63.

**Sharpest cell** (stage 9h, LOGIN 10:00-15:59): Friday 1,625 trips/day → **97.80%**;
Tuesday 1,927/day → **81.93%**. An 18.6% load increase costs **15.87 OTA points**.

**Action:** the Tuesday/Wednesday daytime inbound peak is the single controllable driver. Flattening RTO demand
across the week, or pre-staging capacity for Tue/Wed 10:00–16:00 LOGIN, is worth more than any vendor action.

---

## Secondary findings (MEDIUM / LOW)

### M1 — Structural shift-band ranking: daytime is 5.7 pts worse than night (MEDIUM, transport_manager)
Clean table, SPOT_2.0 and `:15`/`:16` removed (stage 10j):

| shift_band | n | OTA | epoch OTA | SLA min/trip |
|---|---|---|---|---|
| 10:00-15:59 | 203,383 | **91.86** | 43.70 | 0.84 |
| Non Shift/Adhoc | 12,476 | 92.03 | 85.79 | 1.32 |
| 06:00-09:59 | 130,159 | 92.35 | 58.47 | 0.89 |
| 16:00-20:59 | 73,344 | 93.51 | 35.47 | 0.90 |
| 00:00-05:59 | 37,845 | 95.85 | 36.02 | 0.22 |
| 21:00-23:59 | 33,806 | **97.60** | 37.66 | 0.23 |

Worst individual shifts (n≥500, stage 1m): `10:30` 82.53% (n=11,540), `03:00` 83.14% (n=3,256),
`09:30` 84.85% (n=17,780), `10:00` 85.17% (n=16,571), `11:00` 85.74% (n=30,175).
Note `Non Shift` scores 80.38% with mean delay 34.0 min (n=12,446) — it holds the 10,644-min outlier.

### M2 — Rostering, not fleet, drives 24% solo trips: same BU + same fleet, 2.3× the solo rate (MEDIUM, facilities_head)
194,340 trips (31.6%) carry one passenger. Split by cause (stage 8t): **148,893 planned solo (24.19%,
2,308,947 km)** vs 45,436 became-solo-via-noshow (7.38%). So it is overwhelmingly a *planning* choice.

**Artifact check — is it a small-cab constraint?** No. Controlled comparison inside `pinnacle-Slc`, all three
offices running a ~98% capacity-3 fleet (stage 10a):

| BU | office | n | % cap-3 fleet | % planned solo | mean planned riders | seat fill | solo km |
|---|---|---|---|---|---|---|---|
| pinnacle-Slc | Oakmont Office | 64,667 | 98.72 | **44.79** | 1.73 | 52.61 | 419,091 |
| pinnacle-Slc | Willow Bend Campus | 69,868 | 98.59 | **41.87** | 1.83 | 54.18 | 425,614 |
| pinnacle-Slc | Clearwater Campus | 114,174 | 98.24 | **19.29** | 2.37 | 62.19 | 294,759 |

Identical fleet, identical business unit, 2.3× the solo rate. Clearwater proves 19.29% is achievable on a
3-seat fleet. Solo trips are not longer-distance either (Oakmont solo 14.46 km vs office mean 14.11 km), so the
"remote employee" explanation does not hold.
**Sizing (stage 10b):** Oakmont + Willow Bend ran 58,590 solo trips of 136,011 (43.08%). At Clearwater's 19.29%
that is **32,353 excess solo trips and 469,306 excess km over 3 months.**
Fleet-wide seat fill is only 57.93 / 59.72 / 59.65% (stage 6c).

### M3 — No-shows fell 38% in 3 months; the residual is one cell (MEDIUM, line_manager)
Stage 6i: 9.44% → 8.07% → **5.81%** (44,507 → 42,888 → 30,637 no-shows on 471,575 → 531,387 → 527,574 planned seats).
Wasted seat-km fell 543,776 → 544,893 → 396,587 (stage 10l).
Concentrated in **LOGIN 10:00-15:59: 16.07% → 14.33% → 11.23%** (n = 38,590/41,869/43,050 trips, stage 10k) —
still ~2× the fleet rate. Next worst: LOGOUT 21:00-23:59 at 10.41% (n=75,216). Best: LOGOUT 10:00-15:59 at
1.53% (n=90,720). By office, Denver 17.80 → 10.05% and Cedar Ridge 13.39 → 8.61% (stage 6m).

### M4 — Schedules are systematically optimistic by ~13 min, and the morning band is the only one calibrated (MEDIUM, transport_manager)
Stage 4c: mean planned duration 42.72 / 43.96 / 46.40 min vs mean actual 55.40 / 58.83 / 58.82 min.
**67.3–70.8% of trips exceed their planned duration** every month; p90 overrun 44.5–48.7 min.
Decomposed by band (stage 4f, mean minutes):

| shift_band | start dev (May/Jun/Jul) | duration dev (May/Jun/Jul) |
|---|---|---|
| 06:00-09:59 | +2.47 / +3.16 / +2.65 | **−0.30 / +2.70 / +0.34** |
| 10:00-15:59 | −2.44 / −1.81 / −2.42 | +8.40 / +12.17 / +9.88 |
| 16:00-20:59 | −7.60 / −6.34 / −6.67 | **+28.37 / +30.40 / +27.84** |
| 21:00-23:59 | −9.88 / −9.21 / −9.50 | +21.22 / +21.55 / +19.37 |

Morning trips are planned accurately but **start late**; evening trips start ~7–10 min early but **run ~28 min
over plan**. Two different fixes: morning = dispatch discipline; evening = re-baseline the route timings.
Among late trips (stage 4e), 44.6–49.7% started on time and still finished late — a slow run, not a late start.

### M5 — Route inefficiency is real but small, and does NOT cause lateness (LOW→MEDIUM, facilities_head)
Fleet km drift is only +0.55 / +1.04 / +0.66% (stage 5b). Concentrated by site (stage 5c):
**Eastgate Office +13.55 / +12.69 / +13.05%** (n≈4.8–6.3k/mo), Lakeside Commons +6.5%,
Cedar Ridge +5.29 → +6.93% (worsening); Denver Office is *negative* at −3.53 → −4.56%.
Worst vendor: Meera Pavlov Travel +4.59 → +6.99% (n≈4.9–5.4k/mo), Rahul Mikhailov +5.24% (n≈10.7–13.0k/mo).
**Artifact check:** excess km does **not** predict delay (stage 5e) — OTA by excess-km bucket is
93.92 / 94.93 / 94.39 / 94.32 / 94.43 across ≤0 / 0–2 / 2–5 / 5–10 / >10 km (n = 318,877 / 214,738 / 60,988 /
16,365 / 2,047). Route drift is a fuel/cost story, not a punctuality story — do not bundle them.

---

## Data-quality warnings for anyone building on this

1. **`is_driver_nc` and `is_cab_nc` are dead columns** — 0 on all 615,546 rows (stage 7f). Any NC dashboard
   built on them will read 0% forever.
2. **`route_source` breaks across July.** SHUTTLE_SERVICE is 169 / 196 / **8,274** by month (stage 8o). It is a
   *reclassification*, not a new service: within Denver Office, MANUAL BUS falls 26,539 → 18,686 (−7,853) while
   SHUTTLE_SERVICE BUS appears at 8,054 (stage 10d). Combine MANUAL+SHUTTLE_SERVICE for any trend across July,
   or you will report a fake −5 pt MANUAL improvement and a fake new offender.
3. **`emp_planned = emp_actual + noshow` holds only 73.93% of the time** (stage 8p): 16.17% have
   actual+noshow > planned (unrostered riders boarding), 9.90% have actual+noshow < planned. Do not derive
   no-shows arithmetically; use the `noshow_cnt` column.
4. **Beware `HAVING count(*)>=500` on cross-tabs.** It made cab-swaps look July-only; without the filter they
   exist in all three months (370 / 379 / 545) and are 100% SPOT_2.0 `Non Shift` trips (stage 8n).
5. **Escort does not survive controls.** Raw, escort trips look +4.8 pts better (98.14 vs 93.32, n=101,662 vs
   513,884) — but escort trips are 83.73% LOGOUT vs 47.73%, and 34.35% are `:15`/`:16` codes vs 16.99%
   (stage 8l). Controlled for band × direction (stage 8m) the effect vanishes in 4 of 7 comparable cells
   (e.g. 16:00-20:59 LOGIN: 89.68 escort vs 90.31 non-escort; 21:00-23:59 LOGOUT: 99.20 vs 99.28).
   **Do not report an escort punctuality effect.**
6. `shift_type` has 100 values but only 2 non-time codes (`Non Shift` 12,446, `Adhoc` 2,353). `Adhoc` reports
   100.00% OTA in all three months (677 / 1,071 / 605) — same un-scoreable pattern as Finding 2.
7. Negative `planned_km` exists but is trivial: 1 row in June (−2.00). `traveled_km` is never negative;
   zero `planned_km` on 717 / 765 / 1,047 rows per month (stage 5a).
