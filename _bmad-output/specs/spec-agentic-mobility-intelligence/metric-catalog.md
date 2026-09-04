# Metric Catalog, Benchmarks & Attribution

Companion to [SPEC.md](SPEC.md). Backs CAP-1 through CAP-5.

## Data quality vector (CAP-1)

Incomplete records are retained and flagged, never dropped. Flags propagate all the way into narrative output.

| Flag | Meaning | Downstream effect |
| --- | --- | --- |
| `gps_gap_pct` | share of expected pings missing | suppresses route-geometry metrics only; other metrics unaffected |
| `roster_unmatched` | employee absent from roster | excluded from experience metrics, retained in cost and timeliness |
| `cost_imputed` | cost derived from vendor rate card, not billed | any narrative citing cost must disclose it |
| `time_estimated` | arrival inferred from last valid ping | widens the delay confidence interval |
| `vendor_unmapped` | vendor id not in dimension table | excluded from peer comparison, retained in totals |

A metric computed over flagged rows carries an aggregate `quality` block stating coverage and a confidence label.

## Metric definition shape (CAP-2)

Declarative catalog entries compiled to SQL. The catalog is the only path to a number — console, digest, chat, and agents all resolve through it.

```yaml
- id: ota
  label: On-Time Arrival
  formula: countIf(actual_arrival <= scheduled_arrival + grace) / count(*)
  grains: [global, vendor, route, shift, site, mode]
  direction: higher_is_better
  sla_key: sla.ota
  min_sample: 30
  version: 1
```

`min_sample` is load-bearing: below it the layer returns `insufficient_sample` rather than a number, which is what stops a two-trip route from generating a spurious incident.

## Metric families

| Family | Metrics |
| --- | --- |
| Timeliness | OTA, OTD, delay minutes p50 / p90, delay frequency |
| Cost | cost per trip, per employee, per km; variance vs budget |
| Safety | speeding events per 100km, night-escort compliance, SOS incidents |
| Utilisation | seat occupancy, empty-seat km, trips per vehicle |
| Sustainability | CO2 per employee-km, mode-mix share |
| Experience | CSAT / NPS, complaint rate, repeat-complaint rate |
| Vendor | composite scorecard across the above, weighted |

## MetricObservation contract (CAP-3)

The single interface between the deterministic core and the agentic layer. Every number crossing that boundary is one of these.

```json
{
  "metric_id": "ota", "grain": "vendor", "entity": "V3",
  "period": "2026-08", "value": 0.781, "sample_size": 4820,
  "references": {
    "trend":    { "prior": 0.853, "delta": -0.072, "robust_z": -3.1 },
    "sla":      { "target": 0.90, "delta": -0.119, "breached": true },
    "peer":     { "cohort_median": 0.884, "rank": "5 of 5", "percentile": 0 },
    "industry": { "benchmark": 0.87, "source": "config" }
  },
  "severity": 0.91,
  "quality": { "gps_coverage": 0.84, "confidence": "high" }
}
```

Four reference types, each either populated or explicitly `unavailable` with a reason. This is the mandatory "contextualises against at least one reference point" requirement satisfied four times over.

## Attribution — mix-rate variance decomposition (CAP-5)

The differentiator. For an overall rate `R`, entity share `w`, and entity rate `r`, between periods `t-1` and `t`:

```
rate_effect(v) = w(v, t-1) x [ r(v,t) - r(v,t-1) ]
mix_effect(v)  = [ w(v,t) - w(v,t-1) ] x [ r(v,t-1) - R(t-1) ]

sum over v of [ rate_effect(v) + mix_effect(v) ]  ~=  R(t) - R(t-1)
```

`rate_effect` is "this vendor got worse". `mix_effect` is "volume shifted toward a vendor that was already weak". Separating them matters because they demand different actions — one is a vendor performance conversation, the other is an allocation decision.

The decomposition sums to the observed delta, which makes it auditable and gives CAP-5 its testable success criterion. Run it across vendor, route, shift, and site grains and rank by absolute contribution.

Worked output shape:

> OTA fell 7.2pts. Vendor V3's rate decline accounts for **4.2pts**; a further **1.8pts** is mix shift as V3 absorbed volume from V1. The remaining 1.2pts is spread across 9 routes with no single dominant contributor.

## Anomaly detection & ranking (CAP-4)

- **Detection:** robust z-score using median and MAD — resistant to the outliers this data is full of, unlike mean and standard deviation. EWMA for drift. Day-of-week and holiday awareness so Monday is compared against Mondays.
- **Ranking:**

```
score = severity x confidence x actionability x recency x (1 - suppression)
```

`actionability` is the term that keeps this from becoming an alert firehose: a metric that moved but has no owner or available lever scores low and never reaches a human. `suppression` is fed by dismissals from the console (CAP-12) and by open incidents in memory (CAP-6).

Only the top N candidates cross into the agentic layer. Everything described in this file is deterministic code.
