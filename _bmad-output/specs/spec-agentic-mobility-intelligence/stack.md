# Stack, Multi-tenancy & Deployability

Companion to [SPEC.md](SPEC.md). Implementation-level decisions the kernel deliberately keeps out of intents.

## Choices

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | **Java 21 + Spring Boot 3** | The brief prefers it and the evaluating organisation is a Java shop, so it scores criterion 3 ("deployable into an existing platform") directly. Mature scheduling, DI, and testing come free. |
| Analytics | **DuckDB**, embedded, over Parquet | In-process OLAP, zero infrastructure, fast at hackathon scale. The deployability story is honest: the same SQL moves to Athena, Redshift, or Snowflake by changing a JDBC URL. |
| State | **Postgres** | Incidents, suppressions, follow-ups, feedback. Relational, transactional, boring — correct for this. |
| LLM | **Claude, tiered** | Strong tool-use for the metric-layer function surface. Prompt caching maps directly onto the static-prefix cost lever in `agents.md`. Bedrock is the alternate route if enterprise procurement prefers it. |
| Frontend | **Angular 17+** | The brief prefers it. Console, chat, and charts. |
| Scheduling | **Spring `@Scheduled`**, EventBridge in production | Drives the proactive trigger behind CAP-9. |
| Deployment | **AWS**: ECS Fargate, S3 (Parquet), RDS, EventBridge | The brief prefers AWS; standard and defensible. |

## The velocity trade-off

Python + FastAPI + Polars would build roughly twice as fast. Taking it trades away part of criterion 3, because the deployability-into-an-existing-Java-platform argument weakens considerably.

Java is the better **scored** choice. Python is the better **velocity** choice. This decision is gated on the submission deadline, which is an open question in the kernel — it should be resolved before implementation starts, not during it.

## Multi-tenancy (bonus criterion)

- `tenant_id` on every fact row; the semantic layer injects the filter so no query path can omit it.
- Per-tenant SLA configuration, persona routing, and quiet hours.
- Per-tenant token budget with graceful degradation — exhaust it and the system falls back to deterministic alerts, which still work.
- The metric catalog is versioned, so changing a definition is a migration rather than a silent shift in what a number means.

## Deployability

The agent layer talks to the metric layer over the interface in `agents.md`. Dropping this onto a real mobility platform means implementing one adapter behind that interface — not rewriting the agents. That single seam is the whole deployability argument, and it is why the "agents never issue SQL" constraint sits in the kernel rather than here.

## Local-first requirement

The prototype must run end to end on a laptop from the sample dataset, with no cloud dependency beyond the LLM API. DuckDB and embedded Postgres (or a container) satisfy this. It keeps the demo reliable, which is criterion 4 (functionality, 25 points) — the criterion most often lost to a live-demo infrastructure failure.
