# Findings

Every number here came from a query run against the real extracts — 3,438,966 rows across
May–July 2026. Where a figure is produced by the running system rather than an ad-hoc query,
the endpoint is named so you can reproduce it live.

The seven per-area analyses this summarises are in [`findings/`](findings/).

---

## 1 · The five that should drive the demo

Ranked by business impact × surprise × how easily you can prove it on stage.

### ① June broke, but only in one corner

**Campus on-time arrival: 95.31% (May) → 92.46% (June) → 94.69% (July).**

A 2.86-point dip is unremarkable. Where it *didn't* happen is the finding:

| Split | Fell | Barely moved |
|---|---|---|
| Direction | **LOGIN −5.17** | LOGOUT −0.77 |
| Vehicle | **BUS −6.25** | CAB −2.20 |
| Routing | **MANUAL −6.22** | AUTO −2.20 |
| Business unit | **vanta-Sea −4.15**, pinnacle-Slc −3.12 | catalyst-Sac −0.06 |
| Office | **Denver −4.15**, Clearwater −4.07 | Fairview +0.23 |

> **Morning bus pickups on hand-planned routes, at two sites, broke in June.**
> It is not a vendor problem — and the fix is a routing conversation, not an escalation.

**Prove it:** `POST /api/runs {"period":"2026-06","priorPeriod":"2026-05"}` → the P1 incident,
which clusters 16–19 correlated slices into one alert and names `trip_direction` as the best
explanatory dimension.

**Persona:** transport manager. **Confidence:** high — 210,669 June trips.

### ② An alarm stopped ringing

| Alert type | May | June | July | Change |
|---|---|---|---|---|
| `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` | **7,670** | 46 | 20 | **−99.7%** |
| `EMPLOYEE_GEOFENCE_VIOLATION` | 2,983 | 3,711 | 4,102 | +37.5% |
| `DEVICE_NOT_REACHABLE` | 2,778 | 3,552 | 3,584 | +29.0% |
| `PANIC_DEVICE` | 230 | 276 | 280 | +21.7% |

A safety alert that fired 7,670 times in May fired 20 times in July. Either a detection rule
broke or a policy changed — and nobody was told.

> **A dashboard shows alerts that fired. It cannot show alerts that stopped firing.**

This is the clearest evidence in the submission that the system is watching rather than
displaying. **Persona:** transport & facilities head.

### ③ Cost per kilometre has been meaningless for 42% of spend

Two billing regimes are blended in one metric:

| Contract | Rows | Zero-km share |
|---|---|---|
| `4S-HYD`, `6S-HYD` | 48,475 | **100%** |
| `4S-EV-Z` | 48,295 | 99.8% |
| `4S-150ORRNEW`, `6S-150ORRNEW` | 111,237 | 99.7% |
| `4Seater`, `6Seater`, `3S_Jan2024_CNG_AC` | 225,275 | **~0%** |

Fixed-rate contracts bill a flat fee and never record distance. Divide by it anyway and you get
**₹183,506/km** for vanta-Aus and **₹2,736/km** for vanta-Sea. Those are not outliers — they are
what happens when two incompatible billing models are averaged together.

**Handled:** `cost_per_km.yaml` declares `segment_by: billing_regime`, so the metric layer
appends the regime predicate to every query. No caller — dashboard, agent or chat — can ask for
cost per km on a fixed-rate contract and receive a number.

### ④ Night escort coverage is at 48% against a 100% policy

Crestwood Campus, July: **48.00%** against a zero-tolerance target, down 4.41 points.

Escort coverage is a safety control, not a KPI — a 100% target means every qualifying trip.
Roughly half were uncovered. **Persona:** transport & facilities head. Surfaced as a CRITICAL
incident by the running pipeline.

### ⑤ No-shows improved sharply and nobody noticed

**9.44% (May) → 8.07% (June) → 5.81% (July)** — a 38% relative reduction in wasted seats.

Included because it cuts the other way: the system is not only an alarm. Occupancy also rose
(0.598 → 0.616). Worth a sentence in the leadership brief, since good news that nobody reports
is still management information.

---

## 2 · The full catalogue

### Transport manager — operational

| Finding | Numbers | Confidence |
|---|---|---|
| June dip concentrated in morning/bus/manual | see §1① | high |
| Worst single days were early June | Jun 2 **83.73%**, Jun 3 87.42%, Jun 11 87.55% | high |
| Delay causes all rose together in June | TRAFFIC 2.97→4.56, DRIVER 2.12→3.45, EMPLOYEE 3.17→3.94 (share of all trips) | high |
| Delay is rare but extreme when it happens | 90.2% of trips `NODELAY`; DRIVER delays median 9 min, p90 30 min, max **10,644 min** | high |
| Worst office in June | Clearwater Campus **89.22%** across 40,574 trips; best Fairview Commons 98.68%; median of 12 offices 96.29% | high |
| Vendor spread is real but narrow | best Sneha Mikhailov **98.35%** (6,491 trips), worst Pooja Mikhailov 90.58%, median 94.81% across 21 vendors | high |
| Shift-level degradation | shift `08:00` at **83.48%** against a 95% target | high |

### Transport & facilities head — strategic

| Finding | Numbers | Confidence |
|---|---|---|
| Alert type went silent | −99.7%, see §1② | high |
| Cost-per-km metric invalid for 42% of spend | see §1③ | high |
| Spend is rising faster than trips | ₹254.6M → ₹284.8M → ₹294.6M; trips 191,266 → 212,486 → 217,190. Cost/trip ₹1,331 → ₹1,340 → ₹1,356 | high |
| Distance-contract unit cost is falling | ₹86.60 → ₹80.24 → ₹78.51 per km (net of credit notes) | high |
| Credit notes distort every naive aggregate | 189 lines of negative `trip_cost`, largest **−₹2,233,332.99** | high |
| Escort coverage far below policy | see §1④ | high |
| Compliance rates are stable and low | driver non-compliance 0.16% → 0.11% → 0.12%; cab 0.01% | high |

### Line manager — shift readiness

| Finding | Numbers | Confidence |
|---|---|---|
| No-shows falling sharply | 9.44% → 8.07% → 5.81% | high |
| Occupancy improving | 0.598 → 0.616 → 0.616 seats filled per seat available | high |
| Morning legs are where riders feel it | LOGIN −5.17 vs LOGOUT −0.77 in June | high |
| A fifth of employee legs never completed | 190,010 of 1,637,906 rows have no actual pickup or drop time | high |

---

## 3 · Metric definitions that change the answer

The judgement calls. Each one moves the number, so each is declared in the catalog rather than
decided in a query.

| Decision | Choice | Why it matters |
|---|---|---|
| **On-time threshold** | delay ≤ 5 min | `delay_reason='NODELAY'` covers 90.2% of trips. A 0-minute rule would make OTA a proxy for "was a delay recorded", not for punctuality |
| **Cost per km segmentation** | distance-based contracts only | Blending regimes produces ₹183,506/km. This is the single most dangerous metric in the catalog |
| **Credit notes in unit cost** | excluded from the rate, retained in total spend | 189 negative lines pulled a business unit's cost/km to **−₹21.13**. A unit cost cannot be negative; total spend legitimately can fall |
| **Minimum sample** | 500 trips | `trip_nodal='SHUTTLE'` (244 trips) showed a **−26.64pt** swing that is pure noise. The gate removes it |
| **Mean delay vs on-time rate** | prefer the rate | 20 trips report delays over 24 hours, max 10,644 minutes. Any mean is hostage to them; a threshold rate is not |
| **Negative distance** | flagged, never corrected | 48 employee legs and 1 trip carry impossible distances. Silently clipping them would hide a data-pipeline fault |
| **Improvements as incidents** | suppressed unless z ≥ 8 | "On-Time Arrival rose +5.25 pts — CRITICAL" is indefensible. The exception catches detectors dying, which is finding ② |

---

## 4 · Data quality register

All handled in `ingest/DuckDbService`, counted by `QualityFlagger`, and surfaced on
`GET /api/health`. **Invariant: `rowsRead == rowsKept == 615,546`. No row is ever dropped.**

| Issue | Count | Impact | Handling |
|---|---|---|---|
| `trip_id` in three formats | all 5 files | joins fail silently | `TRY_CAST(replace(trip_id,',',''))` everywhere |
| 🆕 **`'OverHead'` in `bill_data.trip_id`** | **160 lines** | plain `CAST` **crashes** | `TRY_CAST`; kept in spend, joins to no trip |
| 🆕 **Negative `trip_cost`** | **189 lines**, min −2,233,332.99 | drove a BU's cost/km negative | excluded from unit cost, retained in spend |
| 🆕 **`severity = 'False'`** | **15,037 rows (29%)** | dictionary implied a single stray value | nulled; with 31,385 nulls, severity unusable on **89.8%** of alerts |
| Fixed-rate contracts report 0 km | 248,191 lines (40%) | cost/km meaningless | segmented by `billing_regime`, not filtered |
| `slab_name` absent | 121,111 lines (19.5%) | partial slab analysis | flagged |
| Schema drift across months | `is_driver_nc`, `is_cab_nc`, `planned_km` | concat fails | `all_varchar` + `union_by_name` + `TRY_CAST` |
| Non-compliance flags unparseable | 8 rows | counted as compliant if coerced | counted as unknown |
| Negative distance | 48 emp legs, 1 trip, min −6.63 km | distorts distance aggregates | flagged, not corrected |
| Delay beyond 24h | 20 trips, max 10,644 min | destroys any mean | flagged; prefer rate metrics |
| `stwid = 0` placeholder | 23,579 rows | fake employee | nulled per-rider, kept trip-level |
| Legs with no actual times | 190,010 | boarding rate → 100% if dropped | retained |
| `trip_nodal` null | 292,644 (47.5%) | expected for home trips | explicit `'NA'` category |
| No marshal rating | 473,692 | ratings skew | excluded from marshal averages |

🆕 = **not in the supplied data dictionary.** We found three quirks their own documentation missed.

---

## 5 · What we deliberately did NOT conclude

The rejected findings. Every one looked strong and failed a check — which is the point.

### ✗ "₹127M/month is billed against trips with zero distance"

**Nearly reported as unjustified spend.** One query killed it: `4S-HYD` and `6S-HYD` are 100%
zero-km, `4S-EV-Z` is 99.8%, `*-ORRNEW` 99.7% — while `4Seater` and `6Seater` are ~0%.

Those are **fixed-rate contracts that never bill by distance.** Not leakage — contract structure.
The correct finding (§1③) is stronger, and would have been missed by stopping at the first one.

### ✗ "Vendor mix shifted and dragged on-time arrival down"

The original hypothesis, and the data refuses it. **Largest vendor share shift May→July: 0.79
points. Mix effect across all 23 vendors: ≈ 0.00.**

The running system reaches the same conclusion independently and says so out loud:

> *"Mix effects account for only 1% of the gross movement, so this is a rate change, not a
> redistribution of volume. An explanation blaming a shift of volume between entities is not
> supported by these numbers."*

### ✗ "Shuttle on-time collapsed 26.6 points"

True and meaningless — **244 trips.** Suppressed by the volume gate. The same gate removes
`SPOT_2.0` (702 trips).

### ✗ "Electric vehicles are less reliable"

Electric fell 3.15 points in June against diesel 2.87 and petrol 2.75. Within noise, and all
three moved together — this is the June effect, not a fuel-type effect.

### ✗ "Driver non-compliance is spiking"

Flagged MAJOR at **z = 6.6** — on a **+0.06 point** move. A very stable series has a tiny MAD, so
trivial changes score enormous z-scores. Statistically loud, operationally irrelevant. Now gated.

---

## 6 · Demo script inputs

### Beat 1 — the run

```
POST /api/runs {"period":"2026-06","priorPeriod":"2026-05"}
615,546 trips → 1,021 series → 20 candidates → 2 incidents, ~8 seconds
```

> *"Three and a half million rows, eight seconds, two things worth your morning."*

### Beat 2 — the incident (the money screen)

```
P1 CRITICAL — On-Time Arrival fell -4.07 pts on office = Clearwater Campus
Now at 89.22% against a 95.00% target, across 40,574 trips.
The same movement appears on 16 correlated slices, reported here once.
```

> *"Sixteen alerts about one problem is how you get a dashboard nobody reads. This is one."*

Then the attribution:

> *"It found that morning pickups explain it — and that it's a performance change, not a volume
> shift. It ruled out the vendor story we assumed."*

### Beat 3 — the alarm that stopped

```
EMPLOYEE_SIGN_OFF_TIME_VIOLATION:  7,670 → 46 → 20     (-99.7%)
```

> *"A dashboard can only show you alerts that fired. It cannot show you the one that stopped."*

### Beat 4 — the chat declining

```
Q: what is the weather in Bangalore tomorrow?
A: That question is outside the metric catalog, so I will not answer it — guessing
   here would produce a number the dashboard disagrees with.
```

> *"A chatbot that refuses is worth more than one that always has an answer."*

### Beat 5 — resilience

> *"Our API credits ran out mid-build. Every model call failed. The run still completed with both
> incidents, because the deterministic core computes every number and the model only judges. Then
> we added a second provider in one class."*
