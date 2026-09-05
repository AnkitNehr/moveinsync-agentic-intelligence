# Employee Experience (emp_Data.csv) — Findings

**Analyst:** `employees`
**Script:** `/Users/ankitnehra/Documents/ankit/moveinsync assesment/tools/analysis/employees.py`
(run `.venv/bin/python tools/analysis/employees.py <section>`; section ids below map to query ids)
**Grain:** 1 row = 1 rider-leg. 1,637,906 rows, 608,793 distinct trips, 25,192 distinct `stwid`,
2026-05-01 → 2026-07-31. `trip_id` parsed 1,637,906 / 1,637,906 (zero failures). [Q0.1]

Every number below is pasted from a query that was actually run. Section ids in `[Qx.y]`.

---

## Structural facts you must know before reading any rate

These are hard equivalences in the file, not approximations. [Q0.2, Q0.4, Q4.1–4.3, Q11.7]

| Fact | Count | Consequence |
|---|---|---|
| `boarding_status='Not Boarded'` ⟺ `signintype IS NULL` ⟺ `actual_pickup_epoch IS NULL` ⟺ `actual_drop_epoch IS NULL` ⟺ `traveled_km=0` | 190,009 (11.60%) | The "190,009 null actual pickup/drop" rows are **fully explained**: they are the not-boarded legs. Unexplained nulls (Boarded but no actual epoch) = **0**. [Q4.3] |
| `signintype IN ('Adhoc','Guest')` ⟺ `planned_pickup_epoch IS NULL` | 112,943 (6.90%) | Pickup punctuality is **structurally uncomputable** for adhoc/guest legs. `pickup_late_min` exists on exactly 1,334,954 legs = the `Planned` population. [Q3.1, Q8.2] |
| `Adhoc` legs that are actually **escorts** (`emp_role='escort'`) | 88,035 / 112,251 = **78.43%** | "Adhoc = 6.9% of travel" is wrong. True ad-hoc *employee* travel is 21,316 legs = **1.30%** of all legs. catalyst-Sac's headline 17.94% "non-planned" is 17.90% escorts and 0.05% true adhoc. [Q11.7, Q11.8, Q8.1] |
| `stwid IN ('0','0.0')` | 1,414 | All are `emp_role IS NULL` + `signintype IN ('Adhoc','Guest')` + Boarded. Placeholder for non-badged riders. Excluded from all per-rider analysis (24,191→ 25,191 real ids). [Q7.1, Q7.2] |
| `NON_COMMUNICATING` | **n = 1** | Do not report this category. It is a single July row. [Q0.2, Q2.1] |
| Trips where **all** legs were cancelled | **0** | `TRIP_CANCELLED_FROM_DASHBOARD` is never a whole-trip cancellation. Trips with ≥1 cancel still ran, at 1.56 boarded vs 2.47 avg. Zero trips in emp_data have 0 boarded riders. [Q2.5, Q2b.4, Q2b.5] |

**Join hygiene warning:** `Ride_data*.csv` has 615,546 rows but only 608,793 distinct `trip_id`.
6,753 trip_ids appear twice; **3,634 of those pairs disagree on `trip_direction`** and 579 disagree
on `delay_minutes`. A naive `emp JOIN trips` fans 1,334,954 legs out to 1,367,620 (+2.4%).
All direction-split headlines below were re-run against a deduped trip table and survive unchanged
(Q16.3 vs Q13.1). [Q11.5, Q16.1–16.3]

---

# TOP 5 FINDINGS

---

## 1. HIGH — LOGOUT ride times are planned ~11 minutes short, every day, by design. The planner assumes evening cabs move 31% faster than morning cabs. They don't.

**Persona: facilities_head (SLA credibility + vendor SLA design), line_manager (shift readiness), transport_manager**

Per-rider planned in-cab time (`planned_drop − planned_pickup`) vs actual (`actual_drop − actual_pickup`): [Q13.1]

| direction | month | n | planned min | actual min | **overrun** | median overrun |
|---|---|---:|---:|---:|---:|---:|
| LOGIN | May | 196,305 | 47.62 | 46.56 | **−1.06** | −2.47 |
| LOGIN | Jun | 217,203 | 47.82 | 49.51 | **+1.69** | +0.25 |
| LOGIN | Jul | 228,890 | 48.58 | 48.30 | **−0.28** | −1.30 |
| LOGOUT | May | 221,471 | 37.05 | 47.18 | **+10.13** | +8.67 |
| LOGOUT | Jun | 242,651 | 37.32 | 49.05 | **+11.73** | +10.35 |
| LOGOUT | Jul | 261,099 | 37.56 | 48.91 | **+11.35** | +9.70 |

LOGIN plans are accurate to ±2 min. LOGOUT plans are wrong by 10–12 min every month.

**The mechanism, in one line** [Q13.5] — for the *same* average distance the planner assumes a
different speed by direction:

| direction | n | avg planned km | avg planned min | **implied planned km/h** | **implied actual km/h** |
|---|---:|---:|---:|---:|---:|
| LOGIN | 634,831 | 13.27 | 47.93 | 16.6 | 16.2 |
| LOGOUT | 709,373 | 13.49 | 37.36 | **21.7** | **16.8** |

Actual LOGOUT speed (16.8) ≈ actual LOGIN speed (16.2). The evening speed-up the plan assumes does not exist.

### Artifact check — "isn't the overrun just riders waiting for co-passengers at the office?"
No. Control on **single-rider LOGOUT trips**, where co-passenger waiting is impossible: [Q14.1]

| direction | month | n | planned min | actual min | overrun | planned km/h | actual km/h |
|---|---|---:|---:|---:|---:|---:|---:|
| LOGIN | May | 22,238 | 47.17 | 45.01 | −2.16 | 20.0 | 20.0 |
| LOGIN | Jun | 24,175 | 48.67 | 49.03 | +0.36 | 19.4 | 18.4 |
| LOGIN | Jul | 24,280 | 49.76 | 48.37 | −1.39 | 19.0 | 18.9 |
| LOGOUT | May | 22,483 | 41.24 | 46.56 | **+5.32** | 21.7 | 19.4 |
| LOGOUT | Jun | 23,422 | 42.22 | 48.81 | **+6.58** | 21.2 | 18.5 |
| LOGOUT | Jul | 25,908 | 42.83 | 49.41 | **+6.57** | 21.2 | 18.5 |

With zero possible waiting, LOGOUT still overruns +6.5 min while LOGIN does not.
So of the ~11.4 min fleet-wide overrun, **~6.5 min is a bad ETA and ~5 min is co-passenger pickup wait**.
(Overrun is also flat across boarding position 1→6: +13.33, +11.11, +11.05, +12.12, +11.04, +8.47 — it is
not concentrated on the first-boarded rider, which is what a pure-waiting explanation would require. [Q14.2];
LOGIN by contrast is +1.40, −1.11, −1.38, −1.92, −2.95, −4.19 [Q14.3])

### It is one wrong parameter, per business unit [Q14.5, Q14.4]

| BU | direction | n | planned km/h | actual km/h | verdict |
|---|---|---:|---:|---:|---|
| vanta-Sea | LOGOUT | 229,206 | **24.7** | **14.7** | 68% optimistic — worst |
| catalyst-Sac | LOGOUT | 123,318 | 23.3 | 21.1 | 10% optimistic |
| pinnacle-Slc | LOGOUT | 203,881 | 19.9 | 15.8 | 26% optimistic |
| vanta-Aus | LOGOUT | 85,257 | 19.4 | 16.3 | 19% optimistic |
| orbit-Slc | LOGOUT | 67,711 | 19.0 | 19.9 | **accurate** |
| orbit-Slc | LOGIN | 70,206 | 15.1 | 18.4 | conservative |
| vanta-Sea | LOGIN | 228,443 | 18.7 | 15.2 | 23% optimistic |

Single-rider LOGOUT isolates vanta-Sea cleanly: planned 36.58 min / actual **54.02** min = **+17.44 min**,
planned 27.3 km/h vs actual 18.5 km/h, n=16,772. [Q14.4]

**And the gap is moving in opposite directions across BUs** (LOGOUT in-cab overrun, May→Jun→Jul): [Q13.4]
- catalyst-Sac: +4.82 → +2.91 → **+0.65** (fixed it over the quarter, n≈37k–46k/mo)
- vanta-Sea: +18.82 → +20.00 → **+22.27** (getting worse, n≈73k–80k/mo)

**Demo line:** *"catalyst-Sac fixed its evening ETA in one quarter. vanta-Sea's got worse. It is a single
speed parameter, and it is costing vanta-Sea riders 22 extra minutes a day they were never told about."*

---

## 2. HIGH — Campus OTA measures when the *cab* finished, not when the *rider* was served. Rider-level OTA is 70%, not 94%. The metric is also clipped at zero, so its median is literally 0.

**Persona: facilities_head (the SLA number being reported is not the rider's experience), transport_manager**

`trips.delay_minutes` — the field behind the 92–95% "Campus OTA" — has **min 0.0, median 0.0, p90 0.0,
zero negative values**, n=615,546. It is `max(0, lateness)`, so half of all trips score a perfect 0
before anything is measured. [QD4]

What it actually measures: [QD3, Q3b.3]

| comparison | n | correlation |
|---|---:|---:|
| `delay_minutes` vs rider **drop** lateness | 1,676,293 legs | **0.8485** |
| `delay_minutes` vs rider **pickup** lateness | 1,676,293 legs | **0.0507** |
| `delay_minutes` vs **last-leg drop** lateness, LOGIN | 283,251 | **0.9807** (mean gap 1.42 min) |
| `delay_minutes` vs **last-leg drop** lateness, LOGOUT | 327,092 | **0.1136** (mean gap 7.15 min) |

So `delay_minutes` is *arrival at the office*. It is a good LOGIN metric and it is close to meaningless
for LOGOUT — LOGOUT trips average `delay_minutes` = **0.43 min** while their last rider is dropped
**7.57 min** past plan. [QD3]

**The rider-vs-trip gap** (same legs, paired): [Q3.3]

| month | legs | **rider pickup OTA ≤5 min** | trip OTA ≤5 min |
|---|---:|---:|---:|
| May | 417,776 | **71.56%** | 95.38% |
| Jun | 459,855 | **69.21%** | 92.11% |
| Jul | 489,989 | **71.53%** | 94.66% |

A ~24-point gap that is stable month to month. And **on trips the trip-metric calls on time**
(`delay_minutes ≤ 5`), 3.89% / 4.27% / 3.64% of riders were still picked up more than 15 minutes late
(15,486 / 18,100 / 16,902 legs). [Q3.4]

**Where the rider actually gets hurt is the drop end** [Q12.3]:

| direction | month | n | drop ≤5 min | **drop >15 min** | drop >30 min | p90 drop late |
|---|---|---:|---:|---:|---:|---:|
| LOGIN | May | 196,305 | 60.95 | 16.18 | 3.65 | 20.2 |
| LOGIN | Jun | 217,203 | 50.67 | **25.08** | 7.49 | 26.8 |
| LOGIN | Jul | 228,890 | 57.15 | 19.22 | 4.54 | 22.1 |
| LOGOUT | May | 221,471 | 44.60 | 28.20 | 8.26 | 27.6 |
| LOGOUT | Jun | 242,651 | 41.56 | **34.06** | 11.77 | 32.2 |
| LOGOUT | Jul | 261,099 | 43.79 | 31.99 | 10.45 | 30.6 |

**~1 in 3 LOGOUT riders reaches home more than 15 minutes after their promised drop, while the LOGOUT
trip OTA reads 98%.** And it is not the driver being late: 20.87% of July LOGOUT riders were >15 min
late to drop **despite being picked up within 5 min of plan** (17.02% May, 20.30% Jun). [Q13.2]

### Artifact check — "is LOGOUT `actual_pickup` just a copy of `planned_pickup`?"
No. LOGOUT `pickup_late_min` has sd 11.61, p10 −18.27, p50 −1.77, p90 +9.43, and only 0.10% of legs are
exactly zero (n=725,221). It is a real per-rider boarding timestamp. [Q12.1]

**Proposed replacement metric** — direction-aware rider SLA (LOGIN: pickup ≤5 min; LOGOUT: drop ≤15 min): [Q12.4]
May **68.18%** → Jun **63.20%** → Jul **65.72%** (n = 417,776 / 459,854 / 489,989).
Same shape as Campus OTA, honest level, and it moves for reasons you can act on.

Worst LOGOUT drop-lateness by BU (>15 min late, May/Jun/Jul): pinnacle-Slc 44.17 / **53.99** / 46.42
(n=215,494); vanta-Sea 31.99 / 34.68 / 38.40 (n=230,902); orbit-Slc 17.75 / 26.80 / 25.00 (n=68,320);
catalyst-Sac 12.44 / 13.08 / 12.54 (n=125,116). [Q12.5]

---

## 3. HIGH — "No-show rate" is not comparable across business units. It is a labelling setting. pinnacle-Slc looks 12× better than vanta-Sea and is actually slightly worse.

**Persona: facilities_head (BU league tables are wrong), line_manager**

Naive no-show (`is_no_show='True'`) by BU: [Q1.4]

| BU | May | Jun | Jul | n | overall |
|---|---:|---:|---:|---:|---:|
| vanta-Sea | 16.34 | 13.95 | 9.24 | 588,712 | 13.18 |
| vanta-Aus | 12.99 | 12.51 | 8.03 | 194,993 | 11.16 |
| orbit-Slc | 7.70 | 7.80 | 7.93 | 142,479 | 7.82 |
| **pinnacle-Slc** | 0.78 | 1.04 | 1.42 | 515,206 | **1.09** |
| catalyst-Sac | 0.98 | 0.97 | 0.98 | 196,516 | 0.98 |

But `TRIP_CANCELLED_FROM_DASHBOARD` is **98.6% pinnacle-Slc** (70,994 of 71,976 total). [Q2.3]
Within each BU's not-boarded population the two labels are almost perfectly mutually exclusive: [Q2b.2]

| BU | not-boarded legs | % labelled NO_SHOW | % labelled CANCELLED_FROM_DASHBOARD |
|---|---:|---:|---:|
| vanta-Sea | 78,121 | **99.31** | 0.69 |
| orbit-Slc | 11,148 | **99.91** | 0.09 |
| vanta-Aus | 22,038 | **98.74** | 1.26 |
| catalyst-Sac | 2,070 | 92.61 | 7.39 |
| **pinnacle-Slc** | 76,632 | **7.36** | **92.64** |

Taxonomy-neutral metric = `boarding_status='Not Boarded'`: [Q2b.1]

| BU | May | Jun | Jul | **combined** | noshow label | cancel label | n |
|---|---:|---:|---:|---:|---:|---:|---:|
| **pinnacle-Slc** | 15.56 | 16.05 | 13.11 | **14.87** | 1.09 | 13.78 | 515,206 |
| **vanta-Sea** | 16.42 | 14.00 | 9.39 | **13.27** | 13.18 | 0.09 | 588,712 |
| vanta-Aus | 13.13 | 12.65 | 8.19 | 11.30 | 11.16 | 0.14 | 194,993 |
| orbit-Slc | 7.70 | 7.81 | 7.93 | 7.82 | 7.82 | 0.01 | 142,479 |
| catalyst-Sac | 1.05 | 1.05 | 1.06 | 1.05 | 0.98 | 0.08 | 196,516 |

**pinnacle-Slc (14.87%) is worse than vanta-Sea (13.27%), not 12× better.** Reporting "no-show rate"
across BUs is reporting a config flag.

### Artifact check — "aren't cancellations genuinely a different event from no-shows?"
Partly, and it should be stated honestly. Of not-boarded riders, the share who rode *some* trip the
same day: NO_SHOW **59.47%** (n=118,032) vs CANCELLED **26.20%** (n=71,976). [Q2b.3] So dashboard-cancelled
riders more often didn't travel at all that day. But the labels are assigned by **site**, not by
behaviour — no BU meaningfully uses both — so the two rates cannot be compared and the combined
not-boarded rate is the only defensible cross-BU number.

### The real, comparable story is a large improvement
Combined not-boarded: **13.29% (May) → 12.45% (Jun) → 9.24% (Jul)** on 505,593 / 567,210 / 565,103 legs.
Trips carrying at least one no-boarding rider: **26.34% → 25.64% → 19.56%** of 188,992 / 210,669 / 215,885 trips. [Q15.4]
Seats booked-but-empty fell from 67,181 (May) to 52,207 (Jul) despite 11.8% more legs — driven almost
entirely by vanta-Sea (31,571 → 18,236) and vanta-Aus (8,302 → 5,374); pinnacle-Slc barely moved
(23,570 → 23,672 on 151,511 → 180,569 legs, i.e. rate 15.56% → 13.11%) and orbit-Slc did not improve at
all (3,128 → 4,159 on 40,611 → 52,422 legs; rate 7.70% → 7.93%, flat/slightly worse). [Q15.5, Q2b.1]

---

## 4. HIGH — Rider pain is extremely concentrated: 1,194 riders (5%) absorb 35% of all >15-min late pickups, while 30% of regular riders have never had one. And it is not just "bad offices".

**Persona: line_manager (these are your named people), transport_manager**

Population: 23,863 riders with ≥1 measurable pickup; 73,025 total >15-min-late pickup events. [Q15.3]

| slice | riders | share of >15-min-late events | share of all positive delay minutes |
|---|---:|---:|---:|
| Top 5% by late-count | **1,194** | **35.10%** | 19.13% |
| Top decile | 2,387 | **52.50%** | 31.77% |
| Top 3 deciles | 7,161 | 85.68% | 65.12% |
| Bottom 4 deciles | 9,544 | **0.00%** | 10.82% |

[Q15.3, Q7.4]

Rate-normalised (riders with ≥20 measurable legs, so it is not just "they ride more"): [Q7.5]

| decile by late>15 **rate** | riders | legs | late>15 | **rate** | share of all late>15 |
|---|---:|---:|---:|---:|---:|
| 1 | 1,850 | 113,923 | 30,038 | **26.37%** | 42.42% |
| 2 | 1,850 | 122,789 | 15,046 | 12.25% | 21.25% |
| 5 | 1,849 | 132,929 | 4,307 | 3.24% | 6.08% |
| 8–10 | 5,547 | 334,667 | **0** | **0.00%** | 0.00% |

**30.31%** of riders with ≥20 legs (5,605 of 18,494) have *never* had a >15-min-late pickup. [Q7.7]
Worst individuals (≥20 legs): stwid 2050, pinnacle-Slc / Willow Bend, 110 legs, 87 late>15 = **79.1%**,
avg +21.2 min; stwid 24225, vanta-Sea / Denver, 51 legs, 39 late = 76.5%, avg **+33.1 min**. [Q7.6]

### Artifact check — "is this a person effect or just an office effect?"
Both, and the person effect survives. Share of an office's regular riders that land in the worst
rate-decile: Eastgate **44.0%** (743 riders), Lakeside Commons 34.7% (976), Oakmont 25.6% (1,395),
Clearwater 12.6% (2,959), Denver **0.9%** (5,548). Strong office effect. [Q15.1]

But *inside a single office* — Clearwater Campus, 3,113 riders with ≥20 measurable legs at that office
(Q15.2 filters `office=` directly; Q15.1's 2,959 assigns each rider one office via `any_value`, so the
two counts differ slightly by design) — one campus, one shift catalogue: [Q15.2]

| quintile | riders | legs | late>15 | rate |
|---|---:|---:|---:|---:|
| 1 | 623 | 38,863 | 7,554 | **19.44%** |
| 3 | 623 | 43,672 | 2,649 | 6.07% |
| 5 | 622 | 40,842 | 361 | **0.88%** |

A **22× spread between riders at the same office.** This is a routable, nameable list, not a site-level average.

Same concentration on the no-show side: 14,903 of 25,191 riders had ≥1 no-show, but the
6,331 riders with **≥5** no-shows account for **86.4%** of all 118,032 no-shows. [Q7.8]

---

## 5. HIGH — The lone-female-at-night escort rule is enforced at 99.6% and improving (220 → 44 → 4 breaches). The entire residual risk is three orbit-Slc offices.

**Persona: facilities_head (auditable compliance number), transport_manager (today's exception list)**

Gender split: MALE 922,152 (56.30%, 14,413 riders), FEMALE 714,195 (43.60%, 11,802 riders),
NULL 1,559 (0.10%). [Q6.1]

### Artifact trap that must be avoided
A naive "trip gender composition" reads escort coverage backwards, because the **escort is himself a
leg**: `emp_role='escort'` = 101,802 legs, of which **101,682 are MALE** and 55.86% are night legs. [Q6b.1]
Include escorts and a female-only trip is reclassified as "mixed", producing the nonsense result
"female-only night trips: 100% escorted, n=**37**" — a 37-row cell that must not be reported. [Q6.6]
(`emp_role='escort'` legs and `trips.actual_escort` agree on 613,470 of 615,546 trips; 2,076 disagree. [Q6b.2])

Excluding escort legs from the composition: [Q6b.3]

| rider composition | night | trips | escorted | escort % |
|---|---|---:|---:|---:|
| female-only riders | yes | 35,150 | 35,045 | **99.70** |
| female-only riders | no | 105,037 | 30,245 | 28.79 |
| mixed riders | yes | 60,119 | 21,857 | 36.36 |
| male-only riders | yes | 32,023 | 54 | **0.17** |
| male-only riders | no | 166,069 | 291 | 0.18 |

So the operating rule is clearly **"a female travelling alone at night gets an escort"**, not
"any trip with a female gets an escort" — 40.3% / 39.6% / 40.8% of night trips carrying ≥1 female
employee run unescorted [Q6b.4], which is *not* by itself a violation.

### The right test: who is the LAST person left in the cab?
On a night LOGOUT, a trip that starts mixed ends with one person alone. Testing the last drop: [Q11.3]

| night LOGOUT trips | trips | last drop is female | % |
|---|---:|---:|---:|
| **escorted** | 52,257 | 48,620 | **93.04%** |
| **unescorted** | 63,352 | 270 | **0.43%** |

The escort is deployed almost exactly when the last drop is female. That is the policy, executed.

**And the residual is collapsing** — unescorted night-LOGOUT trips whose last drop was female: [Q11.2]

| month | unescorted night LOGOUT trips | last drop female | % |
|---|---:|---:|---:|
| May | 18,987 | **220** | 1.16 |
| Jun | 21,360 | **44** | 0.21 |
| Jul | 23,005 | **4** | **0.02** |

**Where the 270 breaches live** — 254 of 267 attributable ones (94%) are orbit-Slc: [Q11.4]
Lakeside Commons 121/3,797 (**3.19%**), Cedar Ridge 70/1,307 (**5.36%**), Eastgate 63/2,822 (**2.23%**).
vanta-Sea Denver: 12 of 24,177 (0.05%). vanta-Aus, pinnacle-Slc, catalyst-Sac: **0**.

### Other gender differences — factual, small, and stated with n
- **No-show:** FEMALE 8.663% vs MALE 6.09% overall. Not a BU-composition artifact — the gap holds
  *within every BU*: orbit-Slc +3.70pt (69,579 F / 72,900 M), vanta-Sea +1.92pt (284,786 / 303,730),
  vanta-Aus +1.76pt (94,913 / 100,079), catalyst-Sac +0.64pt, pinnacle-Slc +0.18pt. [Q6.2, Q6b.6]
  Real, consistent, worth asking about — not explainable from this file.
- **Pickup punctuality:** essentially no difference. Late>15 within BU: pinnacle 9.77 F / 8.52 M,
  orbit 15.35 / 13.63, catalyst 3.39 / 3.22, vanta-Aus 2.81 / 2.66, vanta-Sea **1.33 / 1.62 (reversed)**.
  Max gap 1.72pt on n≥62k per cell. **No material service gap by gender.** [Q6b.7]
- The `gender IS NULL` row shows avg_late +8.83 and 38.46% late>15 — **n=1,559, 13 riders.** Noise. Do not report. [Q6.2]

---

# MEDIUM findings

## 6. MEDIUM — Friday is systematically the worst day for turn-up, in every business unit.
**Persona: line_manager**
Not-boarded rate, Friday vs Tue+Wed, within BU: [Q11.6]

| BU | Friday | n(Fri) | Tue+Wed | n(Tue+Wed) | gap |
|---|---:|---:|---:|---:|---:|
| **pinnacle-Slc** | **21.49%** | 86,395 | 13.03% | 225,170 | **+8.46pt** |
| vanta-Sea | 15.67% | 107,109 | 12.75% | 239,854 | +2.92pt |
| vanta-Aus | 13.41% | 36,670 | 11.09% | 75,850 | +2.32pt |
| orbit-Slc | 8.55% | 21,805 | 7.01% | 66,723 | +1.54pt |
| catalyst-Sac | 1.17% | 29,109 | 0.95% | 94,622 | +0.22pt |

Fleet-wide: Friday no-show 8.833% + cancel 6.278% (n=281,088) vs Tuesday 6.446% + 3.753% (n=348,118). [Q10.4]
Sunday (n=7,239) and Saturday (n=26,115) are small-n and excluded from the comparison.
**Actionable:** Friday LOGOUT rosters are over-provisioned by ~1 seat in 5 at pinnacle-Slc.

## 7. MEDIUM — Chronic no-show shifts are the midday LOGIN block, and it is not one BU's artifact.
**Persona: line_manager**
By shift hour, fleet-wide: 11:00 **15.48%** (n=122,473), 12:00 **17.35%** (n=90,577), 10:00 10.92%
(n=80,901), 13:00 10.38% (n=86,513) — versus 04:00 0.33% (n=28,708) and 15:00 1.97% (n=127,075). [Q1.6]

*Artifact check:* the midday peak is present independently in two BUs — vanta-Sea 11:00 = 17.49%
(n=73,107), orbit-Slc 11:00 = 10.68% (n=19,323) and 13:00 = 12.54% (n=36,791). pinnacle-Slc peaks
elsewhere (15:00, 13.56% not-boarded, n=99,851), so the shift curve is BU-specific but the midday
effect is not a single-site artifact. [Q11.1]
The midday peak is **LOGIN**: 12:00 LOGIN 17.51% (n=91,330) vs 12:00 LOGOUT 7.19% (n=2,379);
21:00 flips — LOGOUT 10.48% (n=102,408) vs LOGIN 2.49% (n=5,533). [Q15.6]
Worst chronic cells (n≥1,000): vanta-Sea 12:00 **19.0%** (n=68,190), vanta-Sea 11:00 17.5% (n=73,048),
vanta-Sea 10:00 16.82% (n=40,211), vanta-Aus 11:00 14.41% (n=28,460). [Q1.7]

## 8. MEDIUM — The June dip is worse and differently distributed at rider level than at trip level, and it lands on orbit-Slc LOGIN, which trip-level analysis never flagged.
**Persona: transport_manager**
Rider pickup OTA (≤5 min) by BU × direction, May → Jun → Jul, June swing vs May: [Q11.9]

| BU | direction | n | May | Jun | Jul | **Jun swing** |
|---|---|---:|---:|---:|---:|---:|
| **orbit-Slc** | LOGIN | 70,601 | 41.10 | 31.97 | 31.89 | **−9.13** |
| catalyst-Sac | LOGIN | 34,069 | 66.87 | 60.68 | 61.65 | −6.19 |
| vanta-Aus | LOGIN | 86,259 | 73.14 | 67.18 | 68.40 | −5.96 |
| pinnacle-Slc | LOGIN | 221,657 | 52.09 | 48.48 | 54.16 | −3.61 |
| vanta-Sea | LOGIN | 229,813 | 79.83 | 77.30 | 78.58 | −2.52 |
| orbit-Slc | LOGOUT | 68,320 | 70.01 | 75.03 | 76.06 | **+5.02** |
| catalyst-Sac | LOGOUT | 125,116 | 84.06 | 86.09 | 86.42 | +2.03 |

Two things the trip-level work missed: (a) **every** BU's LOGIN degraded in June while three BUs' LOGOUT
*improved* — LOGIN/LOGOUT is the primary axis, not BU; (b) **orbit-Slc is the worst-hit and never
recovered** (41.10 → 31.97 → 31.89), yet it does not appear in the trip-level June attribution at all,
because orbit's rider pain is at pickup and `delay_minutes` does not measure pickup (see Finding 2).

Worst single days by rider late>15 rate: 2026-06-02 **11.03%** (n=18,773), 06-03 8.10% (n=22,668),
06-10 7.61%, 06-23 7.51%, 06-11 7.28%; monthly daily means 4.70 / **5.54** / 4.73. [Q10.2, Q10.3]
Cost of the June dip in rider time: total positive pickup-lateness **25,515 h (May) → 33,001 h (Jun)
→ 31,161 h (Jul)** — +29.3% in June, and July only recovered a third of it. [Q3b.5]

## 9. MEDIUM — Cabs with a dashboard cancellation still run, 37% emptier.
**Persona: facilities_head (cost), transport_manager**
61,075 of 608,793 trips (10.03%) contain ≥1 dashboard-cancelled leg. Those trips average **2.77 legs
but only 1.56 boarded**, vs 2.68 / **2.47** for trips without one. [Q2b.4, Q2.5]
No trip in emp_data ends with zero boarded riders in any BU or month, so this is dilution, not waste
of a whole vehicle. [Q2b.5]
Fleet occupancy is flat and low: legs/trip 2.717 → 2.698 → 2.659; 23.96% of trips are single-leg;
capacity utilisation 67.8% / 67.8% / 68.5% on 3-seaters and **44.2% / 44.4% / 44.4% on 12-seaters**
(n≈11.3k–12.8k trips/month). [Q9.1, Q9.2, Q9.3, Q9.4]

---

# LOW findings / traps to avoid

## 10. LOW — Negative km is 47 rows. It is not a data-quality exposure; the real gap is zero-km.
**Persona: none — this is a "don't chase it" note.**
`traveled_km < 0`: **47 legs of 1,637,906 (0.0029%)**, range −6.63 to −0.003, median −0.266, total
**−56.58 km**. All 47 are Denver Office / vanta-Sea, 46 of them BUS + Boarded; 1 `planned_km<0` leg at
catalyst-Sac / Redwood City. 37 trips affected, never a whole trip. [Q5.1–5.6]
This is float noise on a rounding boundary, not a systemic issue. Do not build a "data quality" slide on it.
The materially larger gaps are `traveled_km=0` on **199,009** legs (190,009 = not-boarded, correct;
**9,000 boarded legs genuinely have 0 km**, 0.62%) and `planned_km=0` on **123,303 boarded legs (8.5%)**. [QD6, QD7]

## 11. LOW — SPOT_2.0 looks catastrophic and is too small to report.
Rider late>15: 35.27% / 34.43% / 38.15% — but n = 550 / 549 / 747 legs per month, 2,323 trips,
669 riders total. [Q10.1, Q11.10] Above the 500 threshold but only just, single-product, and the
effect would need a per-office breakdown that would be pure noise. Flag as "watch", do not headline.

## 12. LOW — emp_role is 99.9% operational people; "guests" are a rounding error.
employee 85.499%, projectmgr 7.155%, escort 6.215%, vendormgr 0.432% — everything else <0.16%.
`signintype='Guest'` = 692 legs (0.042%). Riders average 65.0 legs over the quarter (p50 62, p90 120,
p99 190, max 960 across 25,191 riders). [Q0.2, Q7.3]

## 13. LOW — emp_data and ride_data disagree on headcount for 1 trip in 8.
`boarded legs` in emp_data equals `actualemployee_cnt` in ride_data on 540,994 of 615,546 joined rows
= **87.89%**. [Q9.5] Use emp_data as the source of truth for occupancy; ride_data counts are
approximate (and see the duplicate-row warning at the top).

---

## Suggested demo narrative (3 slides)

1. **"Your 94% OTA is measuring the cab, not the person."** Finding 2 — 94% → 70%, and the metric's
   median is literally 0 because it is clipped.
2. **"Here is why, and it's one number."** Finding 1 — LOGOUT plans assume 21.7 km/h and deliver 16.8;
   proved on single-rider control trips; catalyst-Sac already fixed theirs, vanta-Sea's got worse.
3. **"And here is who it lands on."** Finding 4 — 1,194 named riders absorb 35% of it, while 30% of
   regular riders have never been late once; 22× spread inside a single campus.
   Closer: Finding 3 — stop ranking BUs on no-show rate; it's a config flag (pinnacle 14.87% vs vanta-Sea 13.27%).
