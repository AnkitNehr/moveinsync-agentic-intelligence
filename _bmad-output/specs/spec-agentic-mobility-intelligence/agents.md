# Agentic Layer

Companion to [SPEC.md](SPEC.md). Backs CAP-6, CAP-7, CAP-9, CAP-10, CAP-11, CAP-13.

## Why these are agents and not code

Everything reducible to arithmetic already happened in the deterministic core. What remains is genuinely model-shaped work: deciding what a busy human should look at, forming a causal hypothesis from heterogeneous evidence, and writing something a director will forward without editing. That division is what makes the AI load-bearing rather than decorative — the test the brief's second criterion applies.

## The five agents

| Agent | Job | Tier | Why an LLM |
| --- | --- | --- | --- |
| **Triage** (CAP-6) | Cluster related candidates, dedupe against open incidents, apply suppressions, decide what warrants a human | cheap | Judgement about salience; one batched call for the whole day's candidate set |
| **Reasoning** (CAP-7) | Form a hypothesis, pull supporting slices via tool calls, cite evidence | strong | Causal reasoning over heterogeneous evidence |
| **Action** (CAP-11) | Choose channel, persona, and escalation level; schedule the follow-up check | cheap | Routing decision over a bounded, constrained tool set |
| **Narrative** (CAP-8) | Compose persona-shaped prose and the leadership brief | strong | Genuinely a writing task |
| **Conversational** (CAP-10) | Map a natural-language question onto a metric-layer call | cheap | Intent parsing over a bounded function surface |

## Tool surface

Agents call the metric layer through a fixed function set, never SQL:

- `get_metric(metric_id, grain, entity, period)` → MetricObservation
- `attribute(metric_id, period, by_grain)` → ranked contributions
- `list_anomalies(period, limit)` → ranked candidates
- `get_incident(incident_id)` / `open_incident(...)` / `schedule_followup(...)`
- `get_suppressions(pattern)`

This surface is the reason the constraint "porting onto a real platform is one adapter" holds: swap the implementation behind these functions and every agent keeps working.

## Guardrails

1. Agents receive `MetricObservation` objects, never raw trip rows.
2. Every figure in generated output must carry a resolvable `metric_id`.
3. A post-generation numeric validator scans output and rejects any number absent from the supplied observations, naming the offending figure on retry. See the guard diagram in `architecture-diagrams.md`.
4. Data-quality flags on the inputs must be reflected in the prose — a cost figure built on imputed rates says so.
5. An unsupported chat question is declined, never guessed (CAP-10).

## The follow-up loop (CAP-11)

The action agent does not just notify. It writes an incident to memory and schedules a re-check: *"is V3's OTA back above SLA in 3 days?"* When the check fires and the metric has not recovered, the system escalates itself — a second notification at a higher level, without anyone asking. This is the difference between a system that senses and reasons, and one that also acts.

Memory holds open incidents, suppressions (from dismissals), scheduled follow-ups, and user feedback. Suppression feeds back into the candidate ranker, so the system gets quieter as the operator teaches it what they do not care about.

## Cost model (CAP-13)

For a 5,000-trips/day tenant:

| Stage | Volume | LLM? | Approximate cost driver |
| --- | --- | --- | --- |
| Ingest + metrics | ~5k rows/day | no | compute, seconds |
| Benchmark + anomaly | ~2k series | no | compute |
| Attribution | top ~50 series | no | compute |
| Triage | 1 batched call/day | yes | ~4k in / ~800 out |
| Reasoning | ~3–6 promoted incidents/day | yes | ~3k in / ~1k out each |
| Narrative | 1 weekly + 1 monthly | yes | ~8k in / ~2k out |
| Chat | on demand | yes | ~2k in / ~600 out per turn |

Single-digit dollars per tenant per month, and the claim survives scrutiny because the deterministic core absorbs the volume — token cost tracks incident count, not trip count.

Levers, all implemented rather than aspirational:

- **Tiered models** — cheap tier for triage, routing, and chat intent; strong tier only for causal reasoning and narrative.
- **Prompt caching** on the static prefix (metric catalog, persona style guides, SLA config), which is byte-identical across every call for a tenant.
- **Batching** — one triage call per day for the full candidate set, not one per anomaly.
- **Deterministic pre-filter** — removes >95% of candidates before a token is spent.
- **Precomputed aggregates** — console and chat hit materialised rollups, so p95 stays well under a second without touching a model.
- **Bounded per-tenant budget** — on exhaustion, degrade to deterministic alerts. The system never goes dark.

Each run emits token counts, tier used, and wall-clock per stage, so the cost story is demonstrated at the demo rather than asserted on a slide.
