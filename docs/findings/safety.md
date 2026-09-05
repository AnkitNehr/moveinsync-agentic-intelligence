# Safety & Compliance — findings

**Area:** alerts_data + `is_driver_nc` / `is_cab_nc` + `actual_escort`
**Scripts:** `tools/analysis/safety.py`, `safety2.py`, `safety3.py`, `safety4.py`, `safety5.py`
**Data:** 51,699 alerts, 615,546 trips, 1,637,906 employee legs, 2026-05-01 → 2026-07-31.
99.09% of alerts (51,227) join to a trip. 0 unparsed alert timestamps, 0 null trip_ids.

Every number below is pasted from a query that was run. Where a number was checked
and turned out to be an artifact, both the artifact and the corrected finding are shown.

---

## Ground rules established first (these change several answers)

**Ack latency is bimodal because of a 24-hour auto-close, not because of slow humans.**

```
bucket                             | n     | pct
-----------------------------------+-------+------
a <=5m                             | 25512 | 49.35
b 6-15m                            | 5469  | 10.58
c 16-60m                           | 3464  | 6.7
d 1-10h                            | 1016  | 1.97
e 10-23.9h                         | 19    | 0.04
f 23.9-24.2h  <-- suspicious spike | 16157 | 31.25
g >24.2h                           | 8     | 0.02
never                              | 54    | 0.1
```
Proof it is a machine, not a person: of the 16,157 in the spike, 16,134 acknowledge on
the *next calendar day* and the mean absolute deviation from exactly 1440 minutes is
**4.07 minutes** (min 1438, max 1450). Only 19 alerts in the entire dataset land in the
10h–23.9h window — there is no human tail leading into it.

**`severity='NA'` is the marker for those auto-closes**, not missing data:

```
severity | n     | in_24h_cluster | pct_autoclosed
---------+-------+----------------+---------------
Sev-3    | 19086 | 0              | 0.0
NA       | 16348 | 16176          | 98.95
False    | 15037 | 0              | 0.0
Sev-1    | 656   | 0              | 0.0
Sev-2    | 572   | 0              | 0.0
```

**Timezone.** `actual_*_epoch` is UTC; `trip_date`, `shift_type` and the alerts
`start_time` string are local. Offset histogram, LOGOUT trips
(`UTC start hour − shift hour`): **5h for 69.65%, 6h for 30.29%** — Denver/Cedar
Ridge/Willow Bend/Oakmont/Lakeside/Eastgate are 5h, Clearwater/Santa Clara/Fairview/
Crestwood/Redwood City are 6h. Deriving hour-of-day from an epoch without this
*inverts* the escort curve. I made exactly that mistake in round 3 (assumed 7h) and
caught it; all escort results below are keyed on `shift_hour` (already local) or on
`end_epoch − start_epoch` (offset-free), with an explicit offset sensitivity check.

**`actual_escort` is trustworthy; `actualemployee_cnt` is not a passenger count.**
Cross-checked against `emp_Data` rows with `emp_role='escort'`:

```
actual_escort | has_escort_row | n
--------------+----------------+-------
False         | False          | 511808
True          | True           | 101662
False         | True           | 2076
```
99.66% agreement, zero `True`-with-no-escort-row. But escorted trips almost never show
`emp_actual=1` (317 of 101,158) while unescorted trips do 40.4% of the time
(166,789 of 412,422) — the escort is being counted in the headcount. Computing "escort
rate by occupancy" from that field produces a spurious *inverse* result (night,
`emp_actual=1` → 0.36% escort). All escort findings below use `emp_Data` gender/boarding
rows as ground truth instead.

---

## HIGH 1 — 31% of all alerts are auto-closed at T+24h and never seen by a human. Two BUs, one still doing it in July.

**Persona: facilities_head** (governance / SLA), secondary transport_manager.

The auto-close is not spread evenly — it is two business units:

```
business_unit | may_pct | jun_pct | jul_pct | n_autoclosed | n_alerts
--------------+---------+---------+---------+--------------+---------
vanta-Sea     | 0.0     | 0.0     | 0.0     | 0            | 20105
pinnacle-Slc  | 83.71   | 32.73   | 30.19   | 10813        | 17176
catalyst-Sac  | 66.83   | 63.34   | 68.79   | 5363         | 8074
vanta-Aus     | 0.0     | 0.0     | 0.0     | 0            | 5142
orbit-Slc     | 0.0     | 0.0     | 0.0     | 0            | 1202
```

**Artifact check — is pinnacle's improvement real, or just the sign-off detector being
switched off?** Excluding `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` entirely, pinnacle goes
38.61 → 32.73 → 30.19 and catalyst 66.83 → 63.30 → 68.79. So pinnacle genuinely improved
a little; **catalyst-Sac has not improved at all and is worse in July than in May.**

Catalyst's problem is one detector, and it is total:

```
event_type                       | n    | autoclosed | pct
---------------------------------+------+------------+------
EMPLOYEE_GEOFENCE_VIOLATION      | 5360 | 5360       | 100.0
PANIC_DEVICE                     | 770  | 0          | 0.0
VEHICLE_STOPPAGE                 | 696  | 0          | 0.0
PANIC_FIXED_DEVICE               | 669  | 0          | 0.0
OVER_SPEEDING                    | 508  | 0          | 0.0
```

**Artifact check — is `EMPLOYEE_GEOFENCE_VIOLATION` just an un-triageable alert type?**
No. The same detector in every other BU is human-handled:

```
business_unit | n    | autoclosed | pct   | med_min
--------------+------+------------+-------+--------
catalyst-Sac  | 5360 | 5360       | 100.0 | 1444.0
pinnacle-Slc  | 4256 | 0          | 0.0   | 1.0
orbit-Slc     | 634  | 0          | 0.0   | 2.0
vanta-Sea     | 478  | 0          | 0.0   | 8.0
vanta-Aus     | 68   | 0          | 0.0   | 4.5
```
It is a per-BU alert-routing/ownership gap: nobody at catalyst-Sac owns the geofence
queue, so 5,360 alerts aged out untouched.

**The flip side is a reassuring negative finding** — once the auto-closes are removed,
human acknowledgement is genuinely good, and there is no Sev-1 backlog at all:

```
severity | n     | med  | p90  | p99     | mx   | pct_gt15m     (auto-closes excluded)
---------+-------+------+------+---------+------+----------
Sev-3    | 19084 | 2.0  | 20.0 | 90.0    | 484  | 13.35
False    | 15037 | 2.0  | 21.0 | 167.0   | 1007 | 12.64
Sev-1    | 656   | 1.0  | 3.0  | 8.45    | 31   | 0.61
Sev-2    | 572   | 1.0  | 2.0  | 16.03   | 53   | 1.05
```
**All 656 Sev-1 and all 572 Sev-2 alerts were acknowledged — zero unacknowledged.**
PANIC_* : 2,030 of 2,434 acknowledged within 5 minutes, 2 never. Unclosed backlog is
52 NEW + 1 OPEN out of 51,699 (0.10%), oldest 2026-05-05, newest 2026-06-09, **none in
July**; 40 of the 53 are from one day and 37 of those belong to the broken detector in
HIGH 2. There is no ack-SLA crisis. The crisis is the third of alerts that never enter
the queue.

---

## HIGH 2 — The sign-off "improvement" (finding B) is a detector being switched off on 2026-05-18, not a safety win.

**Persona: facilities_head.**

Clean cliff, not a decay. Daily counts:

```
start_date | n    | sev_na | autoclosed
-----------+------+--------+-----------
2026-05-12 | 1381 | 1381   | 1381
2026-05-13 | 898  | 898    | 898
2026-05-14 | 829  | 828    | 828
2026-05-15 | 408  | 408    | 408
2026-05-16 | 38   | 38     | 38
2026-05-17 | 5    | 5      | 5
2026-05-18 | 2    | 0      | 0
2026-05-26 | 1    | 0      | 0
2026-05-27 | 1    | 0      | 0
```
Weekly: 3,467 (wk 05-04) → 4,112 (wk 05-11) → **2** (wk 05-18) → 2 → 38 → …

Four artifact checks, all of which say "config change", not "data gap" or "real fix":

1. **pinnacle's other alerts never stopped**: weekly non-sign-off alerts ran
   597, 749, **750, 575, 865, 875, 714, 706, 681, 759, 832, 706, 688** straight through
   the cutover.
2. **Trip volume grew**: pinnacle-Slc 75,165 (May) → 88,035 → 88,574.
3. **The May alerts were never triaged**: 7,627 of 7,670 were `severity='NA'` *and*
   auto-closed at 24h. The 59 that survive in Jun+Jul are `Sev-3` and human-acked —
   a different, working detector.
4. **Different time-of-day signature**: May peaked at 15:00 (1,817) and 16:00 (1,779);
   the Jun/Jul survivors occur only at 20:00–23:00.

This one detector also explains the whole platform-level alert-rate drop. Raw:
109.56 → 71.96 → 73.34 alerts/1k trips. Excluding sign-off, pinnacle-Slc is
**35.73 → 39.43 → 37.88 — flat.** Reporting "-99.7%, safety improved" would be wrong;
7,664 alerts that were never real were simply turned off.

---

## HIGH 3 — The escort rule is keyed to shift start, not drop time. Same real-world risk, 61-point difference in coverage.

**Persona: facilities_head** (policy), **transport_manager** (daily rostering).

Escort rate for LOGOUT CAB trips whose **last employee dropped is female**
(ground truth from `emp_Data`, `arg_max(gender, actual_drop_epoch)`):

```
shift_hour | female_last_drop | pct_escort | n_unescorted | med_dur_min | p90_drop_hour
-----------+------------------+------------+--------------+-------------+--------------
16         | 5882             | 0.0        | 5882         | 43.6        | 17.41
17         | 6593             | 0.02       | 6592         | 65.7        | 18.8
18         | 4794             | 22.09      | 3735         | 66.1        | 19.82
19         | 9465             | 96.74      | 309          | 86.5        | 21.65
20         | 17306            | 92.3       | 1332         | 82.0        | 22.28
21         | 12729            | 95.11      | 622          | 67.4        | 22.98
```

The policy boundary is 19:00 and it is a cliff: 0.02% → 22.09% → 96.74%.

But **trip duration** (`end_epoch − start_epoch`, timezone-offset-free) says the
boundary is in the wrong place. A shift-18 LOGOUT runs a median 65.4 min and p90
109.8 min, so its last drop lands at a median **19:09** and p90 **19:50** —
squarely in the window the policy is meant to cover.

```
shift_hour | n    | drop_after_1900 | pct   | drop_after_2000
-----------+------+-----------------+-------+----------------
17         | 6593 | 396             | 6.01  | 34
18         | 4793 | 2829            | 59.02 | 259
```

**Apples-to-apples test.** Restrict *both* shift-18 and shift-19 trips to those whose
last drop actually falls between 19:00 and 21:00 — identical real-world exposure,
different policy bucket:

```
shift_hour | female_last_drop | pct_escort
-----------+------------------+-----------
18         | 2821             | 34.92
19         | 6988             | 95.98
```
**A 61-point coverage gap for the same clock-time risk.**

Size of the exposed population — shift 17/18, female last drop, actually ending ≥19:00:

```
business_unit | exposed_trips | no_escort | pct_no_escort
--------------+---------------+-----------+--------------
vanta-Sea     | 2604          | 1891      | 72.62
vanta-Aus     | 550           | 274       | 49.82
pinnacle-Slc  | 67            | 67        | 100.0
catalyst-Sac  | 5             | 5         | 100.0
```

**Artifact check — is escort simply rare for everyone at that hour?** No, the policy is
demonstrably gender-aware; it just uses the wrong time key. Same exposure window:

```
last_drop_gender | exposed_trips | pct_escort
-----------------+---------------+-----------
MALE             | 3645          | 1.37
FEMALE           | 3226          | 30.66
```

**Fix:** key the escort rule on projected last-drop time (shift start + planned route
duration), not shift start. That single change moves ~3,200 trips per quarter into
coverage.

---

## HIGH 4 — The WOMAN_TRAVELLING_ALONE detector is off in 3 of 5 BUs (365k trips), and where it is on, recall is 8%.

**Persona: facilities_head.**

Alerts per 1,000 trips by BU — the detector coverage matrix:

```
event_type                       | pinnacle_Slc | vanta_Sea | vanta_Aus | catalyst_Sac | orbit_Slc
---------------------------------+--------------+-----------+-----------+--------------+----------
WOMAN_TRAVELLING_ALONE           | 0.07         | 49.16     | 25.64     | 0.0          | 0.0
DEVICE_NOT_REACHABLE             | 12.68        | 24.37     | 33.23     | 0.0          | 0.0
PANIC_FIXED_DEVICE               | 0.0          | 4.04      | 0.71      | 10.26        | 0.0
PANIC_DEVICE                     | 0.04         | 0.0       | 0.0       | 11.81        | 0.14
EMPLOYEE_GEOFENCE_VIOLATION      | 16.9         | 2.65      | 0.97      | 82.19        | 13.13
EMPLOYEE_SIGN_OFF_TIME_VIOLATION | 30.44        | 0.0       | 0.0       | 0.05         | 1.43
OVER_SPEEDING                    | 2.59         | 0.16      | 0.09      | 7.79         | 1.93
VEHICLE_STOPPAGE                 | 5.31         | 30.71     | 12.31     | 10.67        | 6.29
```

**Artifact check — do those BUs simply have no women?** No:

```
business_unit | n      | female | pct_female
--------------+--------+--------+-----------
vanta-Sea     | 588712 | 284786 | 48.37
pinnacle-Slc  | 515206 | 167383 | 32.49
catalyst-Sac  | 196516 | 97534  | 49.63
vanta-Aus     | 194993 | 94913  | 48.68
orbit-Slc     | 142479 | 69579  | 48.83
```

**And they have plenty of the actual event.** Recall against ground truth
(last-drop-female LOGOUT CAB trips):

```
business_unit | last_drop_female_trips | alerted | recall_pct
--------------+------------------------+---------+-----------
pinnacle-Slc  | 38297                  | 8       | 0.02
vanta-Sea     | 33697                  | 2673    | 7.93
catalyst-Sac  | 28351                  | 0       | 0.0
vanta-Aus     | 14319                  | 801     | 5.59
orbit-Slc     | 8550                   | 35      | 0.41
```

**What the detector actually means** (I first assumed "solo female" and it was wrong).
Of 5,237 WTA-alerted trips:

```
wta_trips | pct_solo_female | pct_last_drop_female | pct_first_pickup_female | pct_any_female
----------+-----------------+----------------------+-------------------------+---------------
5237      | 31.58           | 92.3                 | 83.73                   | 98.7
```
against base rates on all 488,909 CAB trips of 17.90% solo-female and 41.74%
last-drop-female. So it fires on **"the last employee dropped is female"** (92.3% vs a
41.74% base rate), not "only one woman in the cab" (31.58% vs 17.90%).

**Consequence — a metric that must not be used as-is.** vanta-Sea looks like the worst
BU in the platform on WTA (49.16/1k, the single largest alert rate anywhere in the
data) purely because it is the only BU with the detector meaningfully enabled. On the
metric that actually matters it is the *second best*: 7.58% of its female-last-drop
night trips are unescorted, versus orbit-Slc's 23.28%. Ranking BUs by WTA alert
volume inverts the true ranking.

---

## HIGH 5 — orbit-Slc leaves 23.28% of female-last-drop night trips unescorted, 3x the next worst — and has no detector that would show it.

**Persona: facilities_head** (contract/staffing), **transport_manager**.

Female last drop, LOGOUT CAB, night shift (19:00–05:59), % with no escort:

```
business_unit | last_drop_female_night | no_escort | pct_no_escort
--------------+------------------------+-----------+--------------
catalyst-Sac  | 27749                  | 794       | 2.86
vanta-Sea     | 23405                  | 1773      | 7.58
vanta-Aus     | 9084                   | 258       | 2.84
pinnacle-Slc  | 8892                   | 66        | 0.74
orbit-Slc     | 8123                   | 1891      | 23.28
```

Improving, but from a bad base and still 20x pinnacle:

```
month      | n    | no_escort | pct_no_escort
-----------+------+-----------+--------------
2026-05-01 | 2502 | 910       | 36.37
2026-06-01 | 2765 | 542       | 19.6
2026-07-01 | 2839 | 421       | 14.83
```

**Artifact check — is it one bad vendor?** No. All three orbit-Slc vendors are the same:
Rohan Mikhailov 20.77% (n=2,976), Rahul Mikhailov 24.72% (n=2,905), Anjali Mikhailov
24.74% (n=2,239). It is a BU staffing decision, not a vendor failure — which makes it
fixable by contract rather than by enforcement.

Concentrated in two shifts: 20:00 (n=2,975, 26.59% unescorted) and 22:00
(n=3,766, 23.00% unescorted).

**Robustness — the ranking survives every timezone assumption.** Same metric computed
with drop-hour offsets 5h, 6h and 7h, and independently by `shift_hour`:

```
business_unit | off5  | off6  | off7  | by_shift_hour
--------------+-------+-------+-------+--------------
catalyst-Sac  | 3.02  | 2.73  | 2.83  | 2.86
orbit-Slc     | 23.13 | 21.64 | 21.13 | 23.26
pinnacle-Slc  | 0.78  | 0.72  | 0.91  | 0.74
vanta-Aus     | 3.1   | 3.22  | 5.04  | 2.84
vanta-Sea     | 7.92  | 8.46  | 8.86  | 7.58
```

**Alerts will never surface this.** orbit-Slc's WTA recall is 0.41%, and across the
whole platform the alert load is identical whether or not an escort was present:

```
actual_escort | trips | alerts | alerts_per_1k
--------------+-------+--------+--------------
True          | 72461 | 5785   | 79.84
False         | 4779  | 374    | 78.26
```
The escort gap is invisible to the alerting system by construction. It has to be
measured against roster data, which is what this query does.

---

## MEDIUM 6 — `severity` is unusable for 61% of alerts, and the "False" value is not a stray.

**Persona: facilities_head.**

```
severity | c
---------+------
Sev-3    | 19086
NA       | 16348
False    | 15037
Sev-1    | 656
Sev-2    | 572
```
`False` is **29.1% of all alerts**, not a handful of bad rows. It is present in every
one of the 14 weeks (16.02% to 38.74%, never absent) and in every source
(EXTERNAL_DEVICE 56.80 / 56.36 / 52.48% in May/Jun/Jul).

**Artifact check — is `False` just `Sev-3` mislabelled?** No, they behave differently.
Within `DEVICE_NOT_REACHABLE`: Sev-3 median ack 2.0 min (n=6,038), `False` median
20.0 min (n=675), `NA` 1445.0 min (n=3,201) — three distinct populations.

**The taxonomy is also BU-specific**, so severity cannot rank work across BUs:

```
business_unit | n     | sev1 | sev2 | sev3  | na    | falsev
--------------+-------+------+------+-------+-------+-------
vanta-Sea     | 20105 | 6    | 18   | 13028 | 46    | 7007
pinnacle-Slc  | 17176 | 0    | 0    | 868   | 10859 | 5449
catalyst-Sac  | 8074  | 648  | 552  | 770   | 5363  | 741
vanta-Aus     | 5142  | 2    | 2    | 3386  | 0     | 1752
orbit-Slc     | 1202  | 0    | 0    | 1034  | 80    | 88
```
**648 of 656 Sev-1 and 552 of 572 Sev-2 alerts in the entire platform come from
catalyst-Sac.** pinnacle-Slc and orbit-Slc have literally zero Sev-1 or Sev-2 across
18,378 alerts. Any "Sev-1 count by BU" chart is measuring configuration, not risk.

---

## MEDIUM 7 — Driver non-compliance is one BU and one vendor, and it has plateaued.

**Persona: facilities_head** (vendor SLA), **transport_manager**.

Platform-wide the flags are rare: `is_driver_nc` 784 of 615,546 (0.127%),
`is_cab_nc` 32 (0.005%), 4 null, 0 trips with both. Concentration:

```
business_unit | n      | drv_nc_pct | cab_nc_pct | vendors
--------------+--------+------------+------------+--------
pinnacle-Slc  | 251774 | 0.307      | 0.011      | 17
vanta-Sea     | 180064 | 0.005      | 0.001      | 10
vanta-Aus     | 70199  | 0.004      | 0.001      | 5
catalyst-Sac  | 65214  | 0.0        | 0.002      | 8
orbit-Slc     | 48295  | 0.0        | 0.0        | 3
```
772 of the 784 flagged trips are pinnacle-Slc. **Holding BU fixed** (all these vendors
serve the same BU under the same rules), the spread is 70x:

```
business_unit | vendor_id               | n     | drv_nc_pct
--------------+-------------------------+-------+-----------
pinnacle-Slc  | Rohan Mikhailov Travel  | 36900 | 1.401
pinnacle-Slc  | Rahul Mikhailov Travel  | 18272 | 0.553
pinnacle-Slc  | Pooja Mikhailov Travel  | 17191 | 0.343
pinnacle-Slc  | Divya Mikhailov Travel  | 16226 | 0.234
pinnacle-Slc  | Sanjay Mikhailov Travel | 21705 | 0.106
pinnacle-Slc  | Divya Sokolov Travel    | 9803  | 0.02
```

Not improving — Rohan has plateaued and Pooja has regressed 6x:

```
vendor_id              | month      | trips | drv_nc | pct
-----------------------+------------+-------+--------+------
Rohan Mikhailov Travel | 2026-05-01 | 10962 | 192    | 1.752
Rohan Mikhailov Travel | 2026-06-01 | 12990 | 164    | 1.263
Rohan Mikhailov Travel | 2026-07-01 | 12948 | 161    | 1.243
Pooja Mikhailov Travel | 2026-05-01 | 5069  | 12     | 0.237
Pooja Mikhailov Travel | 2026-06-01 | 5723  | 6      | 0.105
Pooja Mikhailov Travel | 2026-07-01 | 6399  | 41     | 0.641
```

**Does the flag predict anything?** NC trips carry 156.86 alerts/1k vs 84.56 for clean
trips (n=816 NC trips, 128 alerts) — 1.85x. But on-time arrival is unaffected: 92.09%
vs 94.12% platform-wide, and 92.10% vs 92.39% within pinnacle-Slc. So `is_driver_nc`
is an alert-load predictor, not a punctuality predictor — do not fold it into an OTA
narrative.

**Sample-size caveat:** `is_cab_nc` is 32 rows platform-wide, 30 of them from one
vendor. That is far under the 500-row bar. Do not report a cab-NC vendor ranking.

---

## MEDIUM 8 — WTA alerts concentrate on ~250 employees because of route position, not travel volume.

**Persona: transport_manager** (routing), **line_manager**.

In vanta-Sea (the only BU with meaningful WTA volume, 8,852 alerts / 1,668 employees):

```
grp     | employees | wta_alerts | pct_of_bu_wta
--------+-----------+------------+--------------
a >=40  | 24        | 1213       | 13.7
b 20-39 | 64        | 1681       | 18.99
c 10-19 | 159       | 2161       | 24.41
d 5-9   | 259       | 1668       | 18.84
e 1-4   | 1162      | 2129       | 24.05
```
**247 employees (≥10 alerts) account for 57.10% of the BU's WTA alerts.**

**Artifact check — are they just heavy travellers?** Normalised by each employee's own
`emp_Data` legs, no:

```
grp     | employees | wta  | legs  | avg_legs_per_emp | wta_per_100_legs
--------+-----------+------+-------+------------------+-----------------
a >=40  | 24        | 1213 | 2740  | 114.2            | 44.27
b 20-39 | 64        | 1681 | 7060  | 110.3            | 23.81
c 10-19 | 159       | 2161 | 15978 | 100.5            | 13.52
d 5-9   | 259       | 1668 | 22719 | 87.7             | 7.34
e 1-4   | 1162      | 2129 | 98469 | 84.7             | 2.16
```
Travel volume differs **1.35x** (114.2 vs 84.7 legs/employee) while the alert rate
differs **20.5x** (44.27 vs 2.16 per 100 legs). Same story at the top level: employees
with any WTA alert average 88.1 legs, those with none 66.3 — only 1.33x.

This is drop-order sequencing, not exposure. The same ~250 people are repeatedly placed
last. Re-sequencing their position is a concrete, bounded routing action that would
remove a majority of the BU's WTA alerts — and, more to the point, the underlying risk.

---

## LOW 9 — Speeding/panic vendor league tables are measuring device fleets. Build them within BU.

**Persona: facilities_head.**

Naive platform-wide ranking puts **Vikram Mikhailov Travel at 26.94 PANIC/1k** (n=25,019),
130x the bottom vendor. But Vikram runs 24,833 of its 25,019 trips inside catalyst-Sac,
and the BUs differ enormously in device fitment:

```
business_unit | trips  | panic | speed | dnr  | panic_per1k | speed_per1k | dnr_per1k
--------------+--------+-------+-------+------+-------------+-------------+----------
pinnacle-Slc  | 251774 | 50    | 653   | 3193 | 0.199       | 2.594       | 12.682
vanta-Sea     | 180064 | 792   | 29    | 4388 | 4.398       | 0.161       | 24.369
vanta-Aus     | 70199  | 71    | 6     | 2333 | 1.011       | 0.085       | 33.234
catalyst-Sac  | 65214  | 1493  | 508   | 0    | 22.894      | 7.79        | 0.0
orbit-Slc     | 48295  | 28    | 93    | 0    | 0.58        | 1.926       | 0.0
```
catalyst-Sac and orbit-Slc emit **zero** DEVICE_NOT_REACHABLE alerts; vanta-Aus emits
33.23/1k. Different telematics stacks, not different reliability.

Holding BU fixed, the spread collapses from 130x to 2.4x and Vikram is unremarkable:

```
business_unit | vendor_id               | trips | panic | per_1k
--------------+-------------------------+-------+-------+-------
catalyst-Sac  | Vikram Mikhailov Travel | 24833 | 674   | 27.141
catalyst-Sac  | Rohan Mikhailov Travel  | 12066 | 284   | 23.537
catalyst-Sac  | Arjun Mikhailov Travel  | 4824  | 102   | 21.144
catalyst-Sac  | Divya Mikhailov Travel  | 12105 | 241   | 19.909
catalyst-Sac  | Priya Mikhailov Travel  | 3718  | 63    | 16.945
catalyst-Sac  | Sanjay Mikhailov Travel | 4023  | 46    | 11.434
```

**Within-BU speeding does survive and is worth acting on** — 3.5x spread on the same
detector and the same roads:

```
business_unit | vendor_id               | trips | speeding | per_1k
--------------+-------------------------+-------+----------+-------
catalyst-Sac  | Arjun Mikhailov Travel  | 4824  | 94       | 19.486
catalyst-Sac  | Priya Mikhailov Travel  | 3718  | 58       | 15.6
catalyst-Sac  | Rohan Mikhailov Travel  | 12066 | 100      | 8.288
catalyst-Sac  | Divya Mikhailov Travel  | 12105 | 79       | 6.526
catalyst-Sac  | Vikram Mikhailov Travel | 24833 | 137      | 5.517
```

---

## Sample sizes that are too small to report — stated so nobody uses them

- **FIRST_MALE_NO_SHOW: 130 alerts total** across 3 months (42 / 50 / 38 by month).
  Per-BU counts are orbit-Slc 74, vanta-Sea 36, catalyst-Sac 14, pinnacle-Slc 6,
  vanta-Aus 0. Every cell is far under 500. No rate should be quoted. For context, the
  underlying no-show behaviour it is meant to catch is real and large — male no-show
  12.25% vs female 14.17% in vanta-Sea (n=588,712 legs) — but the detector is not
  firing at a volume that supports analysis.
- **`is_cab_nc`: 32 trips platform-wide.** See MEDIUM 7.
- **SUPPLEMENTARY_ALERT: 1 row.** Ignore.
- **state_text OPEN: 1 row**, NEW: 52. Reported as a count, never as a rate.

## Data-quality notes worth carrying into the product

- `stwid=0` is not a placeholder failure — it is structural. It is **100%** for every
  vehicle-sourced alert (DEVICE_NOT_REACHABLE, VEHICLE_STOPPAGE, OVER_SPEEDING,
  PANIC_DEVICE, PANIC_FIXED_DEVICE) and **0%** for every employee-sourced one
  (GEOFENCE, WTA, SIGN_OFF, PANIC_MOBILE, FIRST_MALE_NO_SHOW). Employee attribution is
  only possible for 5 of the 10 alert types.
- Alert `start_time` / `acknowledge_time` parse cleanly with `'%B %d, %Y, %I:%M %p'`;
  0 failures on 51,699 rows. `trip_id` needs `replace(...,',','')` in alerts.
- Alert concentration is mild, not a long tail: the top 1% of alerting trips (335 trips)
  carry 9.07% of alerts, top 10% carry 30.48%. There is no small set of trips to blame.
