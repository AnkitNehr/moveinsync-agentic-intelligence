# Cost & Billing findings — `bill_data.csv`

**Analyst:** `cost` · **Scripts:** `tools/analysis/cost.py`, `cost_round2.py`, `cost_round3.py`, `cost_round4.py`
**Scope:** 620,942 billing rows, May–July 2026, 6 billing cycles.
Every number below is pasted from a query that was actually run. Where a round-1 finding
was killed by a round-2 artifact check, the kill is documented — two of them were killed.

---

## The headline number is three numbers

```
--- what the Rs834M is actually made of
┌──────────────┬───────────────┬──────────────┬────────────────┬───────────┐
│  net_billed  │ gross_charges │ credit_notes │ overhead_lines │ trip_rows │
├──────────────┼───────────────┼──────────────┼────────────────┼───────────┤
│ 833976771.29 │  849479569.03 │ -15502797.74 │      4457559.8 │    620782 │
└──────────────┴───────────────┴──────────────┴────────────────┴───────────┘
```

`sum(trip_cost)` = ₹833.98M mixes three different objects: gross trip charges,
credit notes, and non-trip overhead lines. Findings 2 and 3 are about what happens
when you don't separate them.

---

## FINDING 1 — Same contract, same office, same 12-seater: vendors are paid 30–36% differently. ₹9.15M in 3 months.
**Rank: HIGH · Persona: facilities_head**

`BUS-ORRNEW-TT` is the cleanest apples-to-apples comparison in the dataset: one office,
no slabs, fixed-rate, identical 12-seat vehicles.

```
--- contract shape (no slab => nothing else to control for but office)
┌───────┬─────────────┬─────────┬─────────┬────────┐
│   n   │ n_with_slab │ offices │ vendors │ avg_km │
├───────┼─────────────┼─────────┼─────────┼────────┤
│ 22285 │           0 │       2 │       7 │   0.07 │
└───────┴─────────────┴─────────┴─────────┴────────┘

--- DECISIVE: BUS-ORRNEW-TT cost by office x vendor (n>=500)
┌───────────────┬─────────────────────────┬───────┬──────────┬──────────┬────────────┐
│    office     │         vendor          │   n   │ avg_cost │ med_cost │   spend    │
├───────────────┼─────────────────────────┼───────┼──────────┼──────────┼────────────┤
│ Denver Office │ Sanjay Mikhailov Travel │  4976 │  1992.49 │  2075.32 │  9914610.2 │
│ Denver Office │ Anjali Mikhailov Travel │  1679 │  1936.87 │  2075.32 │ 3252002.82 │
│ Denver Office │ Aarav Mikhailov Travel  │  4443 │  1834.21 │  1925.32 │ 8149390.31 │
│ Denver Office │ Isha Mikhailov Travel   │  3791 │  1587.26 │   974.76 │ 6017310.41 │
│ Denver Office │ Aarav Petrov Travel     │  2866 │  1528.96 │  1199.89 │  4381987.7 │
│ Denver Office │ Priya Mikhailov Travel  │  4118 │   1475.0 │  1049.73 │ 6074064.82 │
└───────────────┴─────────────────────────┴───────┴──────────┴──────────┴────────────┘
```

All six at Denver Office. Sanjay ₹1,992.49 vs Priya ₹1,475.00 — a **35.1% spread**, and the
medians differ even more (₹2,075.32 vs ₹1,049.73).

**Artifact check — do the dearer vendors carry more people or drive further?** Partly, and it
matters which way you normalise:

```
--- DECISIVE: does the spread survive normalisation?
┌────────────────┬─────────────────────┬────────────────────┬───────────────────┐
│    contract    │ spread_pct_per_trip │ spread_pct_per_pax │ spread_pct_per_km │
├────────────────┼─────────────────────┼────────────────────┼───────────────────┤
│ BUS-ORRNEW-SML │                29.6 │               21.1 │              33.6 │
│ BUS-ORRNEW-TT  │                35.8 │               41.6 │              14.4 │
└────────────────┴─────────────────────┴────────────────────┴───────────────────┘
```

The spread survives every normalisation — it never drops below 14.4% and on a
per-passenger basis it **widens to 41.6%**. Sanjay drives 19% further than Priya
(8.42 vs 7.09 km) but charges 35% more. Honest read: distance explains roughly
half the gap on TT and none of it on SML.

**Size of the prize** (levelling each vendor to the cheapest on the same contract, per passenger):

```
--- pax-normalised levelling prize on the two bus contracts
┌────────────────┬─────────┬─────────────┬─────────────────────────────┬────────┐
│    contract    │ n_trips │    spend    │ saving_at_best_cost_per_pax │  pct   │
├────────────────┼─────────┼─────────────┼─────────────────────────────┼────────┤
│ BUS-ORRNEW-TT  │   21657 │ 37516480.67 │                  5947902.63 │  15.85 │
│ BUS-ORRNEW-SML │   10874 │ 30021882.56 │                  3204359.94 │  10.67 │
└────────────────┴─────────┴─────────────┴─────────────────────────────┴────────┘
```

**₹9.15M over 3 months on two contracts.** The strictest version (levelling within
contract × slab × office, cost per trip) gives ₹5,526,612.54 + ₹3,913,409.00 — the same
answer by a different route.

Across the whole book, strict contract × slab × office levelling is
**₹18,920,800.59 over 3 months (₹6.31M/month, 2.54% of the ₹745M covered spend, 553,411 trips)**.
Treat that as an upper bound — it assumes the cheapest vendor absorbs all volume at its
current price. The bus contracts are the defensible core of it because the vehicles are identical.

Supporting evidence that price gaps are real and not slab/km mix — `3S_Jan2024_CNG_AC`
within a single zone, vendors at near-identical distance:

```
│ 3S_Jan2024_CNG_AC │ Zone_B │ Vikram Mikhailov Travel │ 13448 │ 1564.61 │ 21.57 km │
│ 3S_Jan2024_CNG_AC │ Zone_B │ Sanjay Mikhailov Travel │  1726 │ 1519.97 │ 20.51 km │
```

---

## FINDING 2 — `OverHead` is not a trip. It fabricated a ₹4.08M "vendor overcharging" story that does not exist.
**Rank: HIGH · Persona: facilities_head**

This one nearly went in the report as a fraud finding. Round 1 said:

> `DV_Package` / Amit Mikhailov Travel: 5,131 rows, avg ₹2,138.72 vs contract avg ₹1,357
> — **+59.11%, ₹4,076,865.78 excess**. 71 trips at an average of ₹60,115 against a peer median of ₹1,260.87.

Pulling the actual rows killed it:

```
--- the actual rows -- do the rides exist and do they justify the cost?
┌─────────────┬─────────────┬──────────────────┬────────┬──────────┬─────────────┬────────────┐
│ trip_id_raw │ cycle_month │      office      │   km   │   cost   │ traveled_km │ emp_actual │
├─────────────┼─────────────┼──────────────────┼────────┼──────────┼─────────────┼────────────┤
│ OverHead    │ 2026-05-01  │ Pinecrest Office │    0.0 │ 96157.89 │        NULL │       NULL │
│ OverHead    │ 2026-05-01  │ Pinecrest Office │    0.0 │ 91578.94 │        NULL │       NULL │
│ OverHead    │ 2026-05-01  │ Pinecrest Office │    0.0 │  87000.0 │        NULL │       NULL │
...
```

They are the `OverHead` line items — a **separate cost object with no trip behind it**.

```
--- OverHead scale
┌───────┬───────────┬──────────┬────────────┬───────────┬────────────────────┬────────┐
│   n   │   spend   │ avg_cost │  min_cost  │ max_cost  │ pct_of_total_spend │ avg_km │
├───────┼───────────┼──────────┼────────────┼───────────┼────────────────────┼────────┤
│   160 │ 4457559.8 │ 27859.75 │ -363695.55 │ 104447.37 │              0.534 │    0.0 │
└───────┴───────────┴──────────┴────────────┴───────────┴────────────────────┴────────┘

--- why it matters: Amit Mikhailov on DV_Package
┌────────────────────┬───────────────────┬─────────────────────────────────┐
│ avg_real_trip_cost │ avg_overhead_line │ avg_if_you_do_not_separate_them │
├────────────────────┼───────────────────┼─────────────────────────────────┤
│            1329.55 │          66201.88 │                         2138.72 │
└────────────────────┴───────────────────┴─────────────────────────────────┘
```

Strip 63 overhead lines out of 5,131 rows and the vendor goes from **+59.11% / ₹4.08M excess**
to **+2.97% / ₹194,429.79** — inside the normal vendor band. There is no overcharging.

Two more things worth knowing:
- **Maple Grove Office is 100% OverHead** — 30 rows, ₹38,795.44 net, and *no trips at all*.
  Any per-trip metric for that office divides by zero.
- Positive OverHead is billed by exactly one vendor (Amit Mikhailov Travel) across 5 BUs.
- `CAST(trip_id AS BIGINT)` crashes on these 160 rows. `TRY_CAST` is mandatory.

**Recommendation:** the demo must treat `trip_id = 'OverHead'` as a distinct line-item type,
never as a trip. Cost-per-trip and cost-outlier panels must exclude it.

---

## FINDING 3 — A single May credit-note event of −₹15.48M hides inside "total spend" and makes one office's spend negative.
**Rank: HIGH · Persona: facilities_head**

```
--- negative / zero / positive cost
┌───────────┬────────┬──────────────┐
│ cost_sign │   n    │    spend     │
├───────────┼────────┼──────────────┤
│        -1 │    189 │ -15502797.74 │
│         0 │    715 │          0.0 │
│         1 │ 620038 │ 849479569.03 │
└───────────┴────────┴──────────────┘

--- credits by month
┌─────────────┬───────┬──────────────┐
│ cycle_month │   n   │ credit_value │
├─────────────┼───────┼──────────────┤
│ 2026-05-01  │   169 │ -15480950.24 │
│ 2026-07-01  │    20 │     -21847.5 │
└─────────────┴───────┴──────────────┘
```

99.86% of all credits land in May. Almost all of it is one vendor at one office:

```
--- credit notes by office+vendor
┌────────────────────┬─────────────────────────┬───────┬──────────────┬───────────────────────┐
│       office       │         vendor          │   n   │ credit_value │ biggest_single_credit │
├────────────────────┼─────────────────────────┼───────┼──────────────┼───────────────────────┤
│ Pinecrest Office   │ Meera Lebedev Travel    │   109 │ -12979190.74 │           -2233332.99 │
│ Denver Office      │ Meera Lebedev Travel    │    43 │  -1681036.72 │             -92070.42 │
│ Pinecrest Office   │ Amit Mikhailov Travel   │     6 │   -803472.78 │            -363695.55 │
└────────────────────┴─────────────────────────┴───────┴──────────────┴───────────────────────┘

--- Pinecrest Office: credits vs its own gross spend
┌──────────────────┬───────┬─────────────┬───────────────┬──────────────┐
│      office      │   n   │  net_spend  │ gross_charges │   credits    │
├──────────────────┼───────┼─────────────┼───────────────┼──────────────┤
│ Pinecrest Office │  1882 │ -3979446.89 │    9803216.63 │ -13782663.52 │
└──────────────────┴───────┴─────────────┴───────────────┴──────────────┘
```

**Pinecrest Office has negative net spend.** Any dashboard tile, ranking or per-trip
average for that office is nonsense unless credits are shown separately. Credits are
**1.825% of gross charges** overall — small in aggregate, catastrophic locally.

**Artifact check — do the credits point at real trips?** 46 of 189 have no ride record, and
13 orphan credit rows worth **−₹4,291,209.03** are large enough to flip a whole month's
orphan-billing figure negative:

```
--- orphan billing by month
┌─────────────┬───────┬──────────────┐
│ cycle_month │   n   │ orphan_spend │
├─────────────┼───────┼──────────────┤
│ 2026-05-01  │  2010 │  -1702267.76 │
│ 2026-06-01  │  2045 │    2531421.2 │
│ 2026-07-01  │  1682 │   1996551.69 │
└─────────────┴───────┴──────────────┘
```

Without this check, "May had −₹1.7M of orphan billing" would have been reported as a
finding. It is one vendor's credit notes.

**Recommendation:** report spend as gross / credits / net, never net alone.

---

## FINDING 4 — The "3 vendors inflating km" story is a business-unit billing rule. orbit-Slc adds a flat +0.3 km to every trip.
**Rank: HIGH · Persona: facilities_head**

Billed km matches GPS traveled km on **94.17%** of the 377,344 joinable distance rows
(overall +0.88%). But at vendor level the picture looked damning — 3 vendors deviate and
**15 are exactly 0.00%**:

```
--- per-vendor share of trips where billed km EXCEEDS traveled km
┌─────────────────────────┬───────┬─────────────────┬───────────────┐
│         vendor          │   n   │ pct_billed_more │ avg_uplift_km │
├─────────────────────────┼───────┼─────────────────┼───────────────┤
│ Anjali Mikhailov Travel │ 15584 │           49.01 │          2.61 │
│ Rahul Mikhailov Travel  │ 39035 │            27.5 │          2.76 │
│ Rohan Mikhailov Travel  │ 68290 │            2.36 │         12.94 │
│ Meera Lebedev Travel    │  1169 │             0.0 │          NULL │
│ ... 14 more vendors all │       │             0.0 │          NULL │
```

**Artifact check — is it the vendor or the contract?** Decisive:

```
--- DECISIVE: km uplift by BUSINESS UNIT
┌───────────────┬────────┬──────────────┬──────────┐
│ business_unit │   n    │ pct_uplifted │ extra_km │
├───────────────┼────────┼──────────────┼──────────┤
│ orbit-Slc     │  55196 │         36.2 │  51570.0 │
│ vanta-Aus     │     23 │          0.0 │      0.0 │
│ pinnacle-Slc  │ 251034 │          0.0 │      0.0 │
│ catalyst-Sac  │  65214 │          0.0 │      0.0 │
│ vanta-Sea     │   5877 │          0.0 │    -72.0 │
└───────────────┴────────┴──────────────┴──────────┘

--- km uplift by contract + how many vendors serve that contract
│ 12SEATER_LVT        │ 1 vendor │  1125 │ 75.64% │ orbit-Slc │
│ 8SEATER_BTT_2025    │ 1 vendor │  4686 │ 52.67% │ orbit-Slc │
│ 4Seater-LVT-July    │ 1 vendor │ 11860 │ 51.16% │ orbit-Slc │
│ NPT_4_SEATER        │ 1 vendor │ 11318 │  8.54% │ orbit-Slc │
│ 4Seater             │ 15 vendors │ 150834 │ 0.0% │ pinnacle-Slc │
│ DV_Package          │ 13 vendors │  77769 │ 0.0% │ pinnacle-Slc │
```

Every uplifting contract belongs to orbit-Slc **and is single-sourced** — vendor and
contract are perfectly confounded. The clincher: the same "guilty" vendors bill
**exactly 0.0% uplift** on their pinnacle-Slc contracts (Rohan: 4Seater n=22,871 → 0.0%,
DV_Package n=11,924 → 0.0%, 3S_Jan2024_CNG_AC n=10,450 → 0.0%). It is not vendor behaviour.

The shape confirms it is a rule, not drift — **75.64% of all uplifts are exactly +0.30 km**:

```
--- the uplift is a FIXED add-on, not a percentage
┌───────────┬───────┬────────┐
│ uplift_km │   n   │  pct   │
├───────────┼───────┼────────┤
│       0.3 │ 15115 │  75.64 │
│       7.3 │    26 │   0.13 │
└───────────┴───────┴────────┘
```

The `NPT_*` family behaves differently again — median uplift 10.8–11.9 km, i.e. a
**minimum-km floor** rather than an add-on.

**Money:** 70,400.9 extra km = **₹3,715,328.32** (0.448% of spend) across 19,983 trips.
That is a contract-terms question for orbit-Slc, not a vendor-audit question.

---

## FINDING 5 — 707 completed trips were invoiced ₹0 because `slab_name` was missing. The other 124,205 slab nulls are structural.
**Rank: HIGH · Persona: facilities_head**

`slab_name` is the literal **string** `'null'` (121,111 rows), not SQL NULL — plus `'NA'` (3,801).
Together 20.12% of rows / **22.17% of spend (₹184.9M)**. That looks like a data-quality
crisis. It isn't:

```
--- ARTIFACT CHECK: structural (no slab concept) vs genuinely missing
┌─────────────────────────────────┬─────────────┬─────────┬──────────────┬─────────────────┐
│             pattern             │ n_contracts │ n_trips │    spend     │ null_slab_spend │
├─────────────────────────────────┼─────────────┼─────────┼──────────────┼─────────────────┤
│ contract SOMETIMES missing slab │          15 │  260918 │ 364171659.88 │        -13072.5 │
│ contract ALWAYS has a slab      │          17 │  235835 │ 284871179.36 │             0.0 │
│ contract NEVER has a slab       │          16 │  124189 │ 184933932.05 │    184933932.05 │
└─────────────────────────────────┴─────────────┴─────────┴──────────────┴─────────────────┘
```

16 contracts (`DV_Package`, `BUS-ORRNEW-TT`/`SML`, `EV_Package`, `NPT_8_SEATER`,
`4S-WOW150ORRNEW`, `6S-PREMIUMNEW`) have **no slab concept at all** — 100% null by design.
That accounts for essentially all ₹184.9M. Only **723 rows** are genuinely missing a slab.

And those 723 are the interesting ones:

```
--- VERDICT: on slab-based contracts, does a missing slab mean a Rs0 bill?
┌─────────────────────────────┬──────────────────────┐
│ genuinely_missing_slab_rows │ of_which_billed_zero │
├─────────────────────────────┼──────────────────────┤
│                         723 │                  707 │
└─────────────────────────────┴──────────────────────┘

--- do zero-cost rows coincide with missing slab?
┌────────────────┬────────────────┬───────────────┐
│ zero_cost_rows │ with_null_slab │ pct_null_slab │
├────────────────┼────────────────┼───────────────┤
│            715 │            707 │         98.88 │
└────────────────┴────────────────┴───────────────┘
```

**A missing slab on a slab-priced contract produces a ₹0 invoice, 97.8% of the time.**
The trips ran — ride_data has the distance:

```
--- the un-billed trips: who ran them and what should they have cost?
│ 4Seater-LVT-July │ Rahul Mikhailov  │ 95 │ billed 0.0 km │ traveled 16.03 km │ ~Rs108,730.72 │
│ 4SEATER_BTT_2025 │ Anjali Mikhailov │ 66 │ billed 0.0 km │ traveled 12.79 km │  ~Rs77,340.27 │
│ 4S-150ORRNEW     │ Isha Mikhailov   │ 63 │ billed 21.28  │ traveled 21.58 km │  ~Rs89,037.11 │
```

Total un-billed value ≈ **₹0.8M**, and it is **not shrinking**: 181 (May) → 283 (Jun) → 251 (Jul).

This currently favours the client, but it is an uncontrolled failure in the billing
pipeline — the same gap can fail in the opposite direction. It is also a clean,
demo-able data-quality alert: *"707 trips ran and were never invoiced."*

---

## Supporting analysis

### Contract segmentation — the correct way to read cost per km
```
┌────────────────┬─────────────┬─────────┬──────────────┬───────────┐
│ contract_type  │ n_contracts │ n_trips │    spend     │ pct_spend │
├────────────────┼─────────────┼─────────┼──────────────┼───────────┤
│ DISTANCE_BASED │          36 │  368745 │ 450719289.69 │     54.04 │
│ FIXED_RATE     │          10 │  245265 │  370297481.6 │      44.4 │
│ MIXED          │           2 │    6932 │   12960000.0 │      1.55 │
└────────────────┴─────────────┴─────────┴──────────────┴───────────┘

blended CPK (all contracts) = Rs146.70   <- meaningless
DISTANCE_BASED only         = Rs 80.49   <- the real number
```
Classification rule: ≥95% zero-km rows ⇒ FIXED_RATE, ≤20% ⇒ DISTANCE_BASED.
The `MIXED` bucket is a single contract, `6S-EV-HTK` (41.3% zero-km) — and it is really
fixed-rate: km=0 rows average ₹1,875.00 and km>0 rows average ₹1,866.70. The km column
is simply populated inconsistently. Only 2 rows (`WOW`) are genuinely ambiguous.

**Distance-only CPK is falling:** ₹86.138 (May) → ₹82.432 (Jun) → ₹80.618 (Jul), **−6.4%**.

### Contract-type mix IS shifting (unlike vendor mix)
```
│ 2026-05-01 │ DISTANCE_BASED │ 51.06% of spend │ 57.18% of trips │
│ 2026-06-01 │ DISTANCE_BASED │ 55.39%          │ 60.07%          │
│ 2026-07-01 │ DISTANCE_BASED │ 55.33%          │ 60.66%          │
│ 2026-05-01 │ FIXED_RATE     │ 47.66%          │ 41.90%          │
│ 2026-07-01 │ FIXED_RATE     │ 42.68%          │ 37.90%          │
```
A **5-point migration** from fixed-rate to distance-based spend in two months. Contrast
with the known result that vendor mix barely moves (max 0.79pt) — contract mix is where
the movement is. Biggest single mover: `DV_Package` 15.79% → 11.85% → 10.68% of monthly spend.

### Spend trend and cost per employee-trip
```
│ 2026-05-01 │ 191266 trips │ Rs254,608,547.76 │            │
│ 2026-06-01 │ 212486 trips │ Rs284,809,881.83 │ +11.86% MoM│
│ 2026-07-01 │ 217190 trips │ Rs294,558,341.70 │  +3.42% MoM│

cost per employee-trip: 573.73 -> 568.13 -> 568.06  (-0.99%)
```
Spend growth is **volume, not price** — trips +11.09% / +2.21% MoM. A mix-vs-rate
decomposition confirms the blended decline is pure rate (**rate effect −5.761,
mix effect +0.003**), so contract mix does *not* distort this metric.

But the flat blend hides two segments moving in opposite directions:
```
┌────────────────┬──────────┬──────────┬────────────┐
│ contract_type  │ may_cpet │ jul_cpet │ pct_change │
├────────────────┼──────────┼──────────┼────────────┤
│ DISTANCE_BASED │   576.04 │   585.87 │      +1.71 │
│ FIXED_RATE     │   570.99 │   547.46 │      -4.12 │
└────────────────┴──────────┴──────────┴────────────┘
```
Distance-based unit cost is **rising**. Reporting only the blended −1% conceals it.

Occupancy improved 2.325 → 2.359 → 2.388 pax/trip; seat fill 59.6% → 61.5% (distance),
56.3% → 57.7% (fixed). **No trip in the dataset has zero passengers** — `emp_actual`
minimum is 1 — so "empty buses" is not a story here.

### Spend concentration — moderate overall, acute locally
```
top-5 vendors = 51.63% of gross charges;  HHI = 715.7 (unconcentrated, 24 vendors)
```
The aggregate looks healthy. The risk is at BU and office level:
```
│ catalyst-Sac │  8 vendors │ top vendor 38.51% │ Vikram Mikhailov Travel │
│ orbit-Slc    │  3 vendors │ top vendor 36.90% │ Rohan Mikhailov Travel  │
│ Eastgate Office     │  1 vendor  │ 100.00% │ n=17,156 trips │
│ Lakeside Commons    │  2 vendors │  58.66% │ n=21,691       │
```
**29 contracts are single-sourced = ₹80.24M = 9.51% of spend** (`NPT_4_SEATER`,
`4Seater-LVT-July`, `4SEATER_BTT_2025`, `8SEATER_BTT_2025` …). These are exactly the
contracts with no price benchmark — and, per Finding 4, exactly the ones with
unusual billing rules.

### Cost outliers — small, and mostly explainable
After excluding OverHead: **565 trips >3× their contract+slab median, ₹2,032,205.26 excess
(0.091% of trips, 0.245% of spend)**, across 17 vendors and 6 offices.

Two artifact checks reduce this further:
- **`DV_Package` (329 of the 565) is a rate-card tier, not an anomaly.** The outlier costs
  take exactly three values — ₹4,578.94 (×161), ₹3,954.54 (×78), ₹3,782.61 (×73) — one per
  billing month. That is a second published price point, not erratic billing.
- **Bus outliers are partly justified:** they carry more passengers (6.23 vs 5.22) and
  travel 63% further (12.37 vs 7.61 km) than normal trips on the same contract. The 3–4×
  price multiple still exceeds the 1.2×/1.6× operational multiple, so a sample is worth
  auditing — but this is not ₹2M of recoverable money.

The multiples cluster at exactly 3.0× (n=334) and 4.0× (n=208), which is further evidence
of tiered pricing rather than error.

### Billing/ride reconciliation
```
bill rows with no ride:   5,737  (Rs2,825,705.13 net, 0.339% of spend)
rides never billed:         746  (0.12% of rides)
```
Unbilled rides are **rising sharply**: 21 (May) → 263 (Jun) → 462 (Jul), and are
concentrated in pinnacle-Slc — San Jose Commons alone accounts for 367. Billing coverage
99.99% → 99.88% → 99.79%. Small money, but a clean degrading-trend alert for a dashboard.

---

## Data-handling warnings for anyone building on `bill_data`

1. **`trip_id` is NOT unique — not in bill, not in ride.** 6,999 ids appear twice in bill;
   6,753 of those also appear twice in ride_data. They are **reused across months and BUs**:
   ```
   │ 1208678 │ 2026-05-01 │ Eastgate Office    │ Rohan Mikhailov  │ NPT_4_SEATER │ 1873.50 │
   │ 1208678 │ 2026-07-01 │ Cedar Ridge Office │ Sneha Mikhailov  │ 6S-HYD       │ 1254.43 │
   ```
   A naive `JOIN USING (trip_id)` fans out: 620,782 bill rows + 615,546 ride rows →
   **628,551 matched rows**. Join on `(trip_id, month)` or dedupe first.
2. **`trip_id = 'OverHead'`** (160 rows) breaks `CAST`. Use `TRY_CAST(replace(trip_id,',',''))`.
3. **`slab_name` uses the literal string `'null'`**, not SQL NULL. `IS NULL` finds nothing.
4. **`trip_cost` and `total_trip_km` are comma-formatted**; cost ranges
   −2,233,332.99 to 104,447.37.
5. **The mid-month billing cycle is not a cost signal.** Cycles starting on the 16th show
   CPK ₹58.5 vs ₹80–86 for the 1st. Reason: **the mid-month cycle is 100% orbit-Slc**, a
   single cheaper BU that bills semi-monthly. It is a BU effect wearing a cycle costume.
   (Checked and discarded — do not report it.)
