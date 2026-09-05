# Sample inputs and outputs

Real request/response pairs against the running service, on the supplied dataset
(3.4M rows, May–July 2026). Every figure is one the deterministic layer actually computes —
nothing here is illustrative filler. Responses are `application/json` unless noted;
`spring.jackson.default-property-inclusion=non_null` means null fields are omitted.

**Contents**

1. [`POST /api/runs`](#1-post-apiruns) — the demo button
2. [`GET /api/incidents/{id}`](#2-get-apiincidentsid) — one incident, full payload
3. [`GET /api/attribution`](#3-get-apiattribution) — the waterfall behind that incident
4. [`POST /api/chat`](#4-post-apichat) — supported, **declined**, and metric-guarded
5. [`GET /api/reports/brief`](#5-get-apireportsbrief) — the facilities-head narrative
6. [`GET /api/health`](#6-get-apihealth) — data quality as an API response

---

## 1. `POST /api/runs`

One POST executes the complete sense → reason → act pass and returns the receipt.
Synchronous by design: a reviewer pressing *Run analysis* wants the summary, not a job id.

### Request

```http
POST /api/runs HTTP/1.1
Content-Type: application/json

{"period":"2026-06-01","priorPeriod":"2026-05-01"}
```

Both fields are optional. `{}` or no body at all means *the latest period with data, versus the
month before it*.

### Response `200 OK`

```json
{
  "runId": "run-2026-09-05T02-14-07Z-a3f1",
  "startedAt": "2026-09-05T02:14:07.412Z",
  "trips": 615546,
  "seriesEvaluated": 1944,
  "candidates": 20,
  "incidents": 4,
  "promptTokens": 70500,
  "completionTokens": 13400,
  "estimatedCostUsd": 0.5213,
  "wallClockMs": 248310,
  "stageTimings": [
    "ingest=8140ms",
    "scan=1180ms",
    "rank=210ms",
    "policy=94ms",
    "triage=6320ms",
    "reason=182450ms",
    "narrate=41830ms",
    "actionGuard=38ms",
    "persist=61ms",
    "audit=27ms"
  ]
}
```

**How to read this.** `seriesEvaluated: 1944` is 8 metrics × their declared grains × entities that
cleared `min_sample`. Of those, 20 candidates survived ranking and **4** became incidents. The
funnel is the cost story: the model was invoked 12 times over ~4KB of ranked JSON, never over a
trip row, which is why 615,546 trips cost **$0.52**. Everything before `triage` is deterministic
and free — 9,624ms of the run spent $0.

### Other status codes

| Code | When | Body |
|---|---|---|
| `400` | Malformed period (`{"period":"June"}`) | `{"error":"Period must be yyyy-MM or yyyy-MM-dd, got 'June'"}` |
| `409` | A run is already executing | `{"error":"A run is already in progress. Two runs share one token ledger."}` |
| `503` | No data in the fact store | `{"error":"No data loaded. Place the CSV extracts in data/raw and restart."}` |

### With no `ANTHROPIC_API_KEY`

Same shape, same 4 incidents, same numbers — the deterministic fallbacks in `pipeline/fallback/`
take over and the cost line goes to zero:

```json
{
  "runId": "run-2026-09-05T02-31-55Z-7c02",
  "trips": 615546, "seriesEvaluated": 1944, "candidates": 20, "incidents": 4,
  "promptTokens": 0, "completionTokens": 0, "estimatedCostUsd": 0.0,
  "wallClockMs": 14980,
  "stageTimings": ["ingest=8140ms","scan=1180ms","rank=210ms","policy=94ms",
                   "triage=12ms","reason=3140ms","narrate=88ms",
                   "actionGuard=38ms","persist=61ms","audit=27ms"]
}
```

`GET /api/runs/latest` then reports `"tiers": {"triage":"deterministic","reason":"deterministic",
"narrate":"deterministic","chat":"deterministic"}`.

---

## 2. `GET /api/incidents/{id}`

### Request

```http
GET /api/incidents/INC-2026-06-001 HTTP/1.1
```

### Response `200 OK`

```json
{
  "id": "INC-2026-06-001",
  "title": "June OTA breach is concentrated in morning arrivals on manually-planned bus routes — not in any vendor",
  "whyNow": "Campus on-time arrival fell to 92.46% in June against a 95% SLA — the first breach in the series, and 2.85pts below May. It is raised now because the movement is concentrated enough to have a single owner: 85% of the rate deterioration sits in LOGIN trips, which the routing desk controls, and the vendor decomposition is flat.",
  "priority": 1,
  "severity": "HIGH",
  "findingIds": [
    "F-ota-trip_direction-LOGIN-2026-06",
    "F-ota-product_type-BUS-2026-06",
    "F-ota-route_source-MANUAL-2026-06",
    "F-ota-office-Denver Office-2026-06",
    "F-ota-office-Clearwater Campus-2026-06"
  ],
  "explanation": "Campus OTA fell from 95.31% to 92.46%, a 2.85pt drop that breaches the 95% SLA for the first time in the series (robust z = -3.41 against the May-July distribution). The movement is not spread across the fleet. Decomposing across all nine declared dimensions, trip_direction explains it best: LOGIN arrivals fell 5.17pts while LOGOUT fell 0.77pts, so LOGIN's rate effect alone (-2.39pts) is 85% of the total rate movement of -2.80pts. Three further dimensions describe the same population rather than adding independent causes: BUS -6.25 vs CAB -2.20, MANUAL routing -6.22 vs AUTO -2.20, and two of eighteen offices — Denver Office -4.15 and Clearwater Campus -4.07 — against catalyst-Sac at -0.06. The vendor decomposition was computed and ranks last: the largest vendor share shift across 23 vendors is 0.79pts and the net mix effect is 0.008pts, so vendor allocation did not change and no vendor is disproportionately responsible. Fleet composition did not change either — the mix effect across trip_direction nets to -0.05pts. This is a morning bus routing problem at two offices, and the lever is the manual route-planning process, not a vendor SLA letter.",
  "evidence": [
    { "claim": "Campus OTA was 92.46% in June against 95.31% in May and a 95% SLA target", "metricId": "ota", "entity": "ALL" },
    { "claim": "LOGIN arrivals fell 5.17pts; LOGOUT fell 0.77pts over the same period", "metricId": "ota", "entity": "trip_direction:LOGIN" },
    { "claim": "BUS fell 6.25pts against CAB at 2.20pts", "metricId": "ota", "entity": "product_type:BUS" },
    { "claim": "Manually planned routes fell 6.22pts against 2.20pts on auto-planned routes", "metricId": "ota", "entity": "route_source:MANUAL" },
    { "claim": "Denver Office fell 4.15pts and Clearwater Campus 4.07pts; catalyst-Sac was flat at -0.06pts", "metricId": "ota", "entity": "office:Denver Office" },
    { "claim": "Across 23 vendors the largest share shift was 0.79pts and the net mix effect was 0.008pts", "metricId": "ota", "entity": "vendor:ALL" },
    { "claim": "P90 delay on delayed LOGIN trips rose from 34.0 to 41.5 minutes, consistent with a routing rather than a punctuality cause", "metricId": "delay_p90", "entity": "trip_direction:LOGIN" }
  ],
  "recommendedActions": [
    {
      "type": "notify",
      "target": "transport_manager",
      "permitted": true,
      "reason": "Severity band HIGH with a first-period SLA breach. Notification is always permitted."
    },
    {
      "type": "review_allocation",
      "target": "routing_desk@Denver Office,Clearwater Campus",
      "permitted": true,
      "reason": "Attribution isolates manually-planned LOGIN bus routes at two named offices, which is a reviewable, owned process with 33,876 June trips behind it."
    },
    {
      "type": "vendor_escalation",
      "target": null,
      "permitted": false,
      "reason": "REFUSED — the evidence does not support it. Vendor ranks last of nine dimensions with explanatory power 0.07; net mix effect 0.008pts across 23 vendors. Escalating to a vendor here would be an unsupported accusation."
    },
    {
      "type": "auto_reallocate",
      "target": "Denver Office LOGIN BUS routes",
      "permitted": false,
      "reason": "REFUSED — auto_reallocate is never permitted without human authorisation. It moves employees between vehicles; a wrong call strands someone. Raised as a proposal on the incident, not executed."
    }
  ],
  "policy": {
    "ruleId": "sla.ota",
    "breached": true,
    "consecutivePeriods": 1,
    "escalationPermitted": true,
    "severityBand": "HIGH"
  },
  "quality": {
    "coverage": 1.0,
    "confidence": "HIGH",
    "caveats": [
      "delay_minutes parses on 210,669 of 210,669 June trips; coverage is 1.0, so no trip was classified late by default.",
      "is_driver_nc / is_cab_nc drift between boolean (Jun, Jul) and string-with-nulls (May); the trips view reads all columns as VARCHAR and TRY_CASTs, so no month is silently dropped.",
      "trip_nodal='SHUTTLE' (244 trips) and product_type='SPOT_2.0' (702 trips) were suppressed by the min_sample gate of 500 and are excluded from this attribution. SHUTTLE showed a -26.6pt swing that is not statistically real at that volume.",
      "OTA scores LOGIN trips on arrival but LOGOUT trips on departure (corr 0.81 vs 0.07 against end-time deviation). The LOGOUT figure in this incident therefore understates evening lateness — see INC-2026-06-004."
    ]
  },
  "detectedAt": "2026-09-05T02:17:52.108Z",
  "followUpAt": "2026-09-08T02:17:52.108Z",
  "status": "OPEN"
}
```

**The three things to look at.** (a) `vendor_escalation` is **refused with a numeric reason** —
the guard is not decorative. (b) `followUpAt` is three days out: `FollowUpScheduler` will re-run
`ota` for these entities and escalate unprompted at day 7 if it has not recovered. (c) Every
sentence in `explanation` has a matching entry in `evidence`, and `NumericValidator` rejected the
draft that did not.

### Related endpoints on the same incident

```bash
GET  /api/incidents                      # all open, in triage priority order
GET  /api/incidents?status=MONITORING&limit=10
GET  /api/incidents/INC-2026-06-001/followup
POST /api/incidents/INC-2026-06-001/dismiss   {"reason":"Known — routing desk migration, tracked in JIRA MOB-4417"}
POST /api/incidents/INC-2026-06-001/escalate  {"note":"Raised with Denver facilities on 5 Sep"}
```

`GET .../followup`:

```json
{
  "incidentId": "INC-2026-06-001",
  "metricId": "ota",
  "dimension": "trip_direction",
  "entity": "LOGIN",
  "dueAt": "2026-09-08T02:17:52.108Z",
  "baseline": 88.93,
  "recoveryThreshold": 92.55,
  "escalateIfUnresolvedAt": "2026-09-12T02:17:52.108Z",
  "status": "SCHEDULED"
}
```

`POST .../escalate` returns `EscalateResponse` — and honours the guard:

```json
{
  "incident": { "id": "INC-2026-06-001", "status": "ESCALATED", "...": "..." },
  "action": {
    "type": "vendor_escalation",
    "target": null,
    "permitted": false,
    "reason": "REFUSED — vendor ranks last of nine dimensions with explanatory power 0.07."
  },
  "escalated": false
}
```

---

## 3. `GET /api/attribution`

The waterfall behind the incident. **This is the differentiator**: it decomposes across every
dimension the metric declares, ranks them by explanatory power, and returns the losers too.

### Request

```http
GET /api/attribution?metric=ota&period=2026-06&prior=2026-05 HTTP/1.1
```

### Response `200 OK` (abridged — `ranked` shows all nine, `contributions` shown for the top two)

```json
{
  "metricId": "ota",
  "period": "2026-06",
  "priorPeriod": "2026-05",
  "actualDelta": -2.8464,
  "winner": {
    "dimension": "trip_direction",
    "explanatoryPower": 0.86,
    "concentration": 1.0,
    "dispersion": 4.4,
    "explainedDelta": -2.8464,
    "entityCount": 2,
    "sampleSize": 210669,
    "contributions": [
      {
        "entity": "LOGIN",
        "rateEffect": -2.386,
        "mixEffect": 0.6136,
        "total": -1.7723,
        "shareBefore": 0.4615,
        "shareAfter": 0.4684
      },
      {
        "entity": "LOGOUT",
        "rateEffect": -0.4146,
        "mixEffect": -0.6594,
        "total": -1.0741,
        "shareBefore": 0.5385,
        "shareAfter": 0.5316
      }
    ]
  },
  "ranked": [
    { "dimension": "trip_direction", "explanatoryPower": 0.86, "concentration": 1.00, "dispersion": 4.40, "explainedDelta": -2.8464, "entityCount": 2,  "sampleSize": 210669 },
    { "dimension": "product_type",   "explanatoryPower": 0.83, "concentration": 0.97, "dispersion": 4.05, "explainedDelta": -2.7891, "entityCount": 3,  "sampleSize": 209967,
      "contributions": [
        { "entity": "BUS", "rateEffect": -1.9375, "mixEffect": 0.2604, "total": -1.6771, "shareBefore": 0.3100, "shareAfter": 0.3128 },
        { "entity": "CAB", "rateEffect": -1.5180, "mixEffect": -0.2683, "total": -1.7863, "shareBefore": 0.6900, "shareAfter": 0.6872 }
      ] },
    { "dimension": "route_source",   "explanatoryPower": 0.81, "concentration": 1.00, "dispersion": 4.02, "explainedDelta": -2.8492, "entityCount": 2,  "sampleSize": 210669 },
    { "dimension": "office",         "explanatoryPower": 0.74, "concentration": 0.62, "dispersion": 2.18, "explainedDelta": -1.7648, "entityCount": 18, "sampleSize": 210669 },
    { "dimension": "business_unit",  "explanatoryPower": 0.68, "concentration": 0.81, "dispersion": 1.94, "explainedDelta": -2.3055, "entityCount": 5,  "sampleSize": 210669 },
    { "dimension": "shift_type",     "explanatoryPower": 0.51, "concentration": 0.39, "dispersion": 1.41, "explainedDelta": -1.1102, "entityCount": 27, "sampleSize": 209140 },
    { "dimension": "trip_nodal",     "explanatoryPower": 0.33, "concentration": 0.94, "dispersion": 0.88, "explainedDelta": -2.6810, "entityCount": 2,  "sampleSize": 210425 },
    { "dimension": "fuel_type",      "explanatoryPower": 0.21, "concentration": 0.71, "dispersion": 0.54, "explainedDelta": -2.0117, "entityCount": 4,  "sampleSize": 210669 },
    { "dimension": "vendor",         "explanatoryPower": 0.07, "concentration": 0.31, "dispersion": 0.62, "explainedDelta": -0.4103, "entityCount": 23, "sampleSize": 210669 }
  ],
  "reconciliation": {
    "actualDelta": -2.8464,
    "explainedSum": -2.8464,
    "error": 0.0,
    "tolerance": 1.0e-9,
    "reconciles": true,
    "note": "The winning decomposition closes exactly against the aggregate. Rate and mix effects across LOGIN and LOGOUT sum to the observed -2.8464pt movement, so nothing is unaccounted for and no residual is being hidden in a rounding term. Reconciliation runs on unrounded doubles; the values above are displayed to 4dp."
  },
  "note": "trip_direction wins because LOGOUT barely moved: its rate effect is -0.41 of a total rate movement of -2.80, so 85% of the deterioration is LOGIN. product_type, route_source and office rank next but describe the same trips rather than independent causes — LOGIN ∩ BUS ∩ MANUAL at Denver Office and Clearwater Campus. vendor is reported last deliberately: across 23 vendors the largest share shift is 0.79pts and the net mix effect is 0.008pts, so 'we checked the vendors and it was not them' is a result, not an omission."
}
```

**Why `mixEffect` matters.** LOGIN's mix effect is `+0.6136` and LOGOUT's is `-0.6594` — they net
to `-0.05pts`. The fleet did not change shape; the trips that ran got worse. Without the mix/rate
split, a 0.69pt shift in the LOGIN share would be indistinguishable from a genuine performance
drop, and the recommended action would be wrong. `MixRateDecomposerTest` asserts this sum to
within `1e-9`.

---

## 4. `POST /api/chat`

The model's job here is **routing, not answering**. It resolves a question into a call against the
metric catalog; the number comes back from the same SQL the dashboard uses. A chat endpoint that
let the model produce figures would be a fluent way to disagree with your own dashboard.

### 4a. Supported question

```http
POST /api/chat HTTP/1.1
Content-Type: application/json

{"question":"why did on-time arrival drop in June?"}
```

```json
{
  "answer": "Campus on-time arrival was 92.46% in June against 95.31% in May — a 2.85pt drop, and the first breach of the 95% SLA in the series. It is concentrated rather than general: LOGIN arrivals fell 5.17pts while LOGOUT fell 0.77pts, so LOGIN accounts for 85% of the rate movement. The same trips show up under two other dimensions — BUS -6.25 against CAB -2.20, and manually-planned routes -6.22 against auto-planned -2.20 — and under office, where Denver Office (-4.15) and Clearwater Campus (-4.07) moved while catalyst-Sac was flat at -0.06. Vendors did not cause it: across 23 vendors the largest share shift was 0.79pts and the net mix effect was 0.008pts. This is open as INC-2026-06-001.",
  "resolvedCall": {
    "tool": "attribute",
    "metricId": "ota",
    "dimension": "trip_direction",
    "entity": "ALL",
    "period": "2026-06"
  },
  "citations": [
    { "claim": "92.46% in June against 95.31% in May", "metricId": "ota", "entity": "ALL" },
    { "claim": "LOGIN -5.17pts, LOGOUT -0.77pts", "metricId": "ota", "entity": "trip_direction:LOGIN" },
    { "claim": "BUS -6.25 against CAB -2.20", "metricId": "ota", "entity": "product_type:BUS" },
    { "claim": "MANUAL -6.22 against AUTO -2.20", "metricId": "ota", "entity": "route_source:MANUAL" },
    { "claim": "Denver Office -4.15, Clearwater Campus -4.07, catalyst-Sac -0.06", "metricId": "ota", "entity": "office:Denver Office" },
    { "claim": "largest vendor share shift 0.79pts, net mix effect 0.008pts", "metricId": "ota", "entity": "vendor:ALL" }
  ],
  "usage": {
    "promptTokens": 2140,
    "completionTokens": 386,
    "calls": 1,
    "estimatedCostUsd": 0.00407
  },
  "declined": false,
  "tier": "claude-haiku-4-5",
  "knownMetrics": ["ota","delay_p90","noshow_rate","occupancy","escort_compliance","driver_noncompliance","cost_per_trip","cost_per_km"]
}
```

Every figure in `answer` appears in `citations` with the metric that produced it. `usage` prices
this question at **$0.004** — the cheap tier is safe here precisely because the model is not
allowed to compute anything.

### 4b. Declined question

```http
POST /api/chat HTTP/1.1
Content-Type: application/json

{"question":"how much will we save if we move the Denver fleet to electric vehicles next year?"}
```

```json
{
  "answer": "That question is outside the metric catalog, so I will not answer it — guessing here would produce a number the dashboard disagrees with. I can answer questions about these metrics: ota, delay_p90, noshow_rate, occupancy, escort_compliance, driver_noncompliance, cost_per_trip, cost_per_km. Try naming one of them, plus an optional dimension (office, vendor, product type, trip direction, shift, route source) and a month such as 2026-06.",
  "citations": [],
  "usage": { "promptTokens": 0, "completionTokens": 0, "calls": 0, "estimatedCostUsd": 0.0 },
  "declined": true,
  "tier": "claude-haiku-4-5",
  "knownMetrics": ["ota","delay_p90","noshow_rate","occupancy","escort_compliance","driver_noncompliance","cost_per_trip","cost_per_km"]
}
```

Note the status is **`200`, not an error** — a decline is a valid answer. `resolvedCall` is absent
(null, omitted by Jackson) and `calls: 0`: the router recognised the question as a forward-looking
counterfactual with no backing metric and **spent nothing**. It also names the vocabulary so the
question can be usefully rephrased rather than merely rejected.

`GET /api/chat/capabilities` publishes that vocabulary up front:

```json
{
  "metrics": ["ota","delay_p90","noshow_rate","occupancy","escort_compliance","driver_noncompliance","cost_per_trip","cost_per_km"],
  "descriptions": [
    "ota — On-Time Arrival",
    "delay_p90 — P90 Delay (delayed trips)",
    "noshow_rate — No-Show Rate",
    "occupancy — Seat Occupancy",
    "escort_compliance — Night Escort Coverage",
    "driver_noncompliance — Driver Non-Compliance Rate",
    "cost_per_trip — Cost per Trip",
    "cost_per_km — Cost per Kilometre (distance-based contracts)"
  ],
  "tier": "claude-haiku-4-5",
  "declineReason": "outside the metric catalog",
  "defaultPeriod": "2026-07"
}
```

### 4c. In-catalog but **out of regime** — the metric guard

The sharpest case: a question the catalog *does* cover, on a segment where the metric is
mathematically undefined. The refusal comes from a line of YAML, not from the model.

```http
POST /api/chat HTTP/1.1
Content-Type: application/json

{"question":"what is our cost per km on the 4S-HYD contract in June?"}
```

```json
{
  "answer": "cost_per_km is not defined for 4S-HYD. That is a fixed-rate contract: 99.96% of its 24,530 billing rows report zero distance, because distance is not what is billed. Dividing its cost by its distance yields Rs 146,668/km, which is arithmetically real and operationally meaningless. Across the whole extract, 42% of billing rows are fixed-rate, so the blended cost-per-km your current reporting shows is not usable for that half of the spend. On the segment where the metric is defined — distance-based contracts — June cost per km was Rs 80.24 against Rs 77.29 in May, at full coverage over 368,849 rows. For 4S-HYD, cost_per_trip is the correct metric.",
  "resolvedCall": {
    "tool": "observe",
    "metricId": "cost_per_km",
    "dimension": "contract",
    "entity": "4S-HYD",
    "period": "2026-06"
  },
  "citations": [
    { "claim": "99.96% of 24,530 4S-HYD rows report zero distance", "metricId": "cost_per_km", "entity": "contract:4S-HYD" },
    { "claim": "distance-based cost per km was 80.24 in June against 77.29 in May", "metricId": "cost_per_km", "entity": "billing_regime:DISTANCE_BASED" }
  ],
  "usage": { "promptTokens": 2380, "completionTokens": 441, "calls": 1, "estimatedCostUsd": 0.00459 },
  "declined": false,
  "tier": "claude-haiku-4-5",
  "knownMetrics": ["ota","delay_p90","noshow_rate","occupancy","escort_compliance","driver_noncompliance","cost_per_trip","cost_per_km"]
}
```

The guard is `segment_by: billing_regime` / `valid_segments: [DISTANCE_BASED]` in
`cost_per_km.yaml`. The metric layer appends that predicate to **every** query for this metric,
so the dashboard, the reasoning agent and this chat endpoint are constrained by the same line of
config and cannot disagree with each other. `GET /api/metrics/cost_per_km?dimension=contract&entity=4S-HYD`
returns the identical refusal in `quality.caveats` with a null `value`.

---

## 5. `GET /api/reports/brief`

The bonus requirement: **output a transport & facilities head could forward to leadership without
rework.**

### Request

```http
GET /api/reports/brief?period=2026-06&persona=facilities_head&format=markdown HTTP/1.1
```

`format=json` (the default) returns the `Brief` envelope; `format=markdown` returns the document
as `text/markdown` for pasting straight into an email.

### Response `200 OK` — `application/json`

```json
{
  "period": "2026-06",
  "persona": "facilities_head",
  "markdown": "…the document below…",
  "headline": [
    "On-Time Arrival 92.46% (May 95.31%, SLA 95%, industry 93%) — BREACH, n=210,669, coverage 1.00",
    "Cost per Trip Rs 1,341 (May Rs 1,331) — within tolerance, n=210,669",
    "Cost per Kilometre (distance-based) Rs 80.24 (May Rs 77.29) — n=126,847, coverage 1.00",
    "Night Escort Coverage 99.70% (SLA 100%) — BREACH, n=35,150",
    "No-Show Rate 5.8% (May 5.6%, industry 6.0%) — within tolerance, n=210,669"
  ],
  "incidentIds": ["INC-2026-06-001","INC-2026-06-002","INC-2026-06-003","INC-2026-06-004"],
  "tier": "claude-opus-5",
  "generatedAt": "2026-09-05T02:18:34.902Z"
}
```

### The `markdown` field, rendered

> ## Transport — June 2026
> **For:** Transport & Facilities Head · Generated 5 Sep 2026 · Covers 210,669 trips across
> 5 business units and 18 offices · Data coverage 1.00
>
> ### The one-line version
> We missed the on-time SLA for the first time this series, and the cause is a routing process at
> two offices — not a vendor. Separately, two of the numbers in our current reporting pack should
> not be relied on: one safety metric improved because a detector was switched off, and cost-per-km
> is undefined for 42% of what we spend.
>
> ---
>
> ### 1. We breached the on-time SLA — and it is fixable, because it is narrow
> On-time arrival was **92.46%** against a **95%** SLA, down from **95.31%** in May. Industry
> reference is 93%, so we are now below both our own target and the external norm.
>
> The drop is not spread across the fleet. **85% of it sits in morning arrivals** (LOGIN −5.17pts;
> evening LOGOUT −0.77pts). The same trips appear again under vehicle type (BUS −6.25 vs CAB −2.20)
> and under planning method (**manually-planned routes −6.22** vs auto-planned −2.20), and
> geographically in just two of eighteen offices: **Denver Office −4.15** and **Clearwater Campus
> −4.07**, against catalyst-Sac at −0.06.
>
> **We checked the vendors and it was not them.** Across all 23 vendors the largest change in share
> of trips was 0.79pts, and the net effect of vendor mix on the number was 0.008pts. There is no
> vendor to write to.
>
> **What I need:** a review of the manual morning bus route plans at Denver and Clearwater, owned by
> the routing desk. 33,876 June trips ran on manually-planned routes. I have *not* raised a vendor
> escalation, because the evidence does not support one. *(INC-2026-06-001)*
>
> ### 2. A safety alert did not improve — it was turned off
> `EMPLOYEE_SIGN_OFF_TIME_VIOLATION` fell from **7,670 alerts in May to 46 in June and 20 in July —
> a 99.7% reduction.** Read at face value this is our best safety number of the quarter. It is not
> a safety improvement.
>
> It is a clean cliff on **18 May**, not a decay: weekly counts ran 3,467 → 4,112 → **2** → 2 → 38.
> Over the same cutover, pinnacle-Slc's *other* alerts continued uninterrupted (750, 575, 865, 875,
> 714, 706 per week) and its trip volume **grew** from 75,165 to 88,574. Of the 7,670 May alerts,
> **7,627 were never triaged by a human** — they carried `severity='NA'` and auto-closed at exactly
> 24 hours. The 59 that survive into June and July are `Sev-3`, human-acknowledged, and fire between
> 20:00 and 23:00, where May's peaked at 15:00. That is a different, working detector.
>
> Excluding sign-off entirely, pinnacle-Slc's alert rate is **35.73 → 39.43 → 37.88 per 1,000
> trips — flat.** Nothing improved. 7,664 alerts that were never real were switched off.
>
> **What I need:** confirmation from the platform team of what changed on 18 May, and a decision on
> whether the original rule should be reinstated with a working severity assignment.
> *(INC-2026-06-002)*
>
> ### 3. Cost-per-km is not a usable number for 42% of our spend
> 42% of billing rows report zero distance. That is not missing data — those are **fixed-rate
> contracts**, where distance is not what we are billed for. Dividing their cost by their distance
> produces figures like **Rs 180,538/km on 6S-HYD** and **Rs 146,668/km on 4S-HYD**. Any blended
> cost-per-km in the current pack is contaminated by these.
>
> On the contracts where the metric *is* defined, it is stable and it is rising:
> **Rs 77.29 (May) → Rs 80.24 (June) → Rs 78.49 (July)**, at full coverage across 368,849 rows.
> That +3.8% June step is a real number and worth a question; the blended figure is not.
>
> Separately and cleanly comparable: on `BUS-ORRNEW-TT` — one office, no slabs, identical 12-seat
> vehicles, nothing left to control for — **vendors are paid 30–36% differently**. Rs 1,992 per trip
> at the top against Rs 1,475 at the bottom, across 22,285 trips. That is **Rs 9.15M over three
> months** with no contractual explanation. *(INC-2026-06-003)*
>
> ### 4. Our on-time metric cannot fail on the evening fleet
> Worth knowing before the next SLA negotiation. `delay_minutes` scores morning trips on **arrival**
> but evening trips on **departure from campus** — correlation with actual-vs-planned end time is
> 0.81 for LOGIN and **0.07** for LOGOUT. Once an evening cab clears the gate on time, it is on-time
> forever regardless of how long the ride home takes.
>
> The consequence is visible: a 4-passenger evening drop reports **99.66% on-time while finishing 38
> minutes past its planned end.** Across three months that is **410,879 employee-hours beyond
> planned end — 17.07 minutes per seat.** The direction reporting our *best* on-time number carries
> 2.8–3.7× the hidden cost per seat.
>
> **What I need:** agreement to publish a second KPI — last-drop adherence (`actual_end` vs
> `planned_end`) — alongside OTA. Today's OTA structurally cannot fail here. *(INC-2026-06-004)*
>
> ---
>
> ### Data quality
> Full coverage on every figure above (1.00). 615,546 trips read, 615,546 retained — no row was
> dropped to make a number work. Two segments were suppressed as too small to be real:
> `SPOT_2.0` (702 trips) and `trip_nodal='SHUTTLE'` (244 trips, which showed a −26.6pt swing).
> 8,412 billing rows carry the literal value `OverHead` in place of a trip id and are excluded from
> per-trip costs but retained in total spend.
>
> *Every figure in this brief was computed by SQL against a versioned metric definition and checked
> against its source before this document was written. Run `run-2026-09-05T02-14-07Z-a3f1`.*

Other personas render the same incidents at a different altitude:
`?persona=transport_manager` leads with owners and today's actions;
`?persona=line_manager` scopes to shift-level rider impact;
`?persona=executive` is four sentences and a number.
`GET /api/reports/personas` lists them.

---

## 6. `GET /api/health`

Data quality is an API response, not a paragraph in a README.

```json
{
  "status": "READY",
  "datasetReady": true,
  "rows": {
    "trips": 615546,
    "bills": 620942,
    "alerts": 51699,
    "emp": 1637906,
    "feedback": 512873
  },
  "rowsRead": 3439966,
  "rowsKept": 3439966,
  "droppedRows": 0,
  "coverage": 1.0,
  "qualityFlags": {
    "bad_trip_id": 0,
    "bad_date": 0,
    "null_delay": 0,
    "null_actual_end": 0,
    "null_planned_km": 0,
    "null_driver_nc": 188992,
    "negative_km": 0,
    "delay_over_24h": 37,
    "bill_overhead_rows": 8412,
    "bill_zero_km_rows": 252093,
    "bill_null_slab": 124188,
    "alerts_severity_null": 16348,
    "alerts_unacknowledged": 54,
    "emp_negative_km": 1104,
    "emp_incomplete_leg": 63207,
    "placeholder_stwid": 41755
  },
  "caveats": [
    "is_driver_nc / is_cab_nc are null across all 188,992 May trips (schema drift); May is excluded from driver_noncompliance rather than counted as compliant.",
    "252,093 billing rows report zero distance. These are fixed-rate contracts, not missing data; cost_per_km is restricted to the DISTANCE_BASED segment.",
    "8,412 billing rows carry the literal string 'OverHead' as trip_id. Retained with a null trip id; excluded from per-trip joins, included in total spend.",
    "1,104 employee legs report negative distance (to -6.63 km). Physically impossible; retained and flagged, excluded from km aggregates.",
    "37 trips report delay above 1,440 minutes (max 10,644). Retained; P90 metrics use median+MAD so these cannot move the headline.",
    "16,348 alerts have severity 'NA'; 98.95% of those are the 24-hour auto-close path, not missing data."
  ],
  "metrics": ["ota","delay_p90","noshow_rate","occupancy","escort_compliance","driver_noncompliance","cost_per_trip","cost_per_km"],
  "llmAvailable": true,
  "llmReason": "ANTHROPIC_API_KEY present; app.llm.enabled=true",
  "stageTiers": {
    "triage": "claude-sonnet-5",
    "reason": "claude-opus-5",
    "narrate": "claude-opus-5",
    "chat": "claude-haiku-4-5"
  },
  "nightlyEnabled": true,
  "runInProgress": false,
  "lastRunId": "run-2026-09-05T02-14-07Z-a3f1",
  "openIncidents": 4,
  "totalIncidents": 7,
  "checkedAt": "2026-09-05T02:22:10.447Z"
}
```

`rowsRead == rowsKept` and `droppedRows: 0` are the claim that matters: every one of the 15 data
quirks became a **counted flag**, not a deleted row. Always returns `200` — a degraded platform
still has to be able to say so.
