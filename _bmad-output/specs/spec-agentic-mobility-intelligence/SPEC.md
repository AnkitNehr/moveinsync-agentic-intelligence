---
id: SPEC-agentic-mobility-intelligence
companions:
  - architecture-diagrams.md
  - metric-catalog.md
  - agents.md
  - personas.md
  - stack.md
  - evaluation-and-deliverables.md
sources:
  - ../../../docs/problem-statement.md
  - ../../../docs/solution-architecture.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Agentic Intelligence & Reporting Layer for Enterprise Mobility

## Why

A pain to solve, under a hackathon mandate. Enterprises move hundreds to thousands of employees daily across cab, nodal, and shuttle modes, and the transport managers accountable for cost, safety, experience, and sustainability spend most of their time assembling data rather than acting on it. The data is rich and continuous; what reaches a human is a static weekly or monthly report of bare numbers. Five distinct gaps sit between that data and a decision — **context** (a metric arrives without trend, SLA, or peer reference), **attribution** (the metric moved but not which vendor, route, or shift moved it), **action** (the cause is known but escalation and communication remain manual), **latency** (weekly reporting against hourly operational reality), and **audience** (one dataset must become three persona-shaped artifacts). Attribution is the gap the brief implicitly asks for: its own example — *"two vendors are responsible for the gap"* — is an attribution statement, not a reporting statement. Closing these gaps is worth doing because the people paying the cost of the gap are precisely the people whose job is to act instead.

## Capabilities

- **CAP-1**
  - **intent:** Load the provided trip-log dataset across cab, nodal, and shuttle modes into a single trip-level fact set, retaining records that are incomplete rather than discarding them.
  - **success:** A load run over the sample dataset reports per-record quality flags and no input row is silently dropped; the run summary states counts per flag and per source file.

- **CAP-2**
  - **intent:** An operator can obtain any supported mobility metric at any supported grain, with every consumer resolving the same definition.
  - **success:** The same metric requested via digest, console, and chat returns an identical value for the same period and grain; a metric below its declared minimum sample size returns `insufficient_sample` rather than a number.

- **CAP-3**
  - **intent:** Every metric value the system emits arrives carrying its comparison against historical trend, SLA target, peer cohort, and industry benchmark, so no number is presented bare.
  - **success:** Every emitted metric payload carries all four reference types or an explicit `unavailable` marker with a reason, and states whether the SLA is breached.

- **CAP-4**
  - **intent:** Identify metric movements that are statistically unusual rather than routine, and order them so a human sees only the few that warrant attention.
  - **success:** A run over the sample dataset produces a ranked candidate list; an injected synthetic vendor degradation surfaces in the top candidates, while ordinary day-of-week variation does not.

- **CAP-5**
  - **intent:** When a rate metric moves between periods, decompose that movement into per-entity rate and mix contributions.
  - **success:** Per-entity contributions sum to the observed total delta within a stated tolerance, and the output names top contributors with their share (e.g. "V3 accounts for 4.2pts of a 7.2pt drop").

- **CAP-6**
  - **intent:** Decide which ranked candidates become incidents, clustering related movements and suppressing ones already raised or previously dismissed.
  - **success:** A second run on unchanged data raises no duplicate incident for an already-open one, and a previously dismissed pattern does not resurface.

- **CAP-7**
  - **intent:** For a promoted incident, produce a causal explanation citing the specific metric observations and attribution results supporting it.
  - **success:** Every quantitative claim in the explanation maps to a supplied observation by id; a validation step rejects any output containing a number absent from its inputs.

- **CAP-8**
  - **intent:** Render the same incident or reporting period for the transport manager, the transport & facilities head, or the line manager, differing in framing, depth, and recommended action.
  - **success:** One incident produces three distinct renderings, and the transport & facilities head rendering is self-contained enough to forward to leadership without editing.

- **CAP-9**
  - **intent:** Run the sense → reason → act cycle on a schedule without a human prompting it, delivering the result to the relevant persona.
  - **success:** A scheduled run completes end to end over the sample dataset and emits its output with no human input during the run.

- **CAP-10**
  - **intent:** A user can ask a mobility question in natural language and receive an answer computed from the governed metric layer with its reference context attached.
  - **success:** Representative questions return numbers identical to the metric layer for the same grain and period; a question outside the catalog is declined rather than guessed.

- **CAP-11**
  - **intent:** Take an action on an incident — notify, escalate, or open a vendor escalation record — and schedule a later check on whether the metric recovered.
  - **success:** An incident produces a scheduled follow-up; when the metric has not recovered by the check, a further escalation is raised without human prompting.

- **CAP-12**
  - **intent:** A transport manager can review open incidents with their evidence, attribution, and underlying trend in one place, and dismiss or escalate from there.
  - **success:** The console lists current incidents from a run and drills into per-entity attribution; a dismissal made there suppresses that pattern on the next run.

- **CAP-13**
  - **intent:** Report what each agentic run cost and how long it took, so the cost-per-interaction claim is demonstrable rather than asserted.
  - **success:** A run emits token counts, model tier, and wall-clock per stage; a documented projection extrapolates these to a stated trips-per-day tenant volume.

## Constraints

- No LLM may compute, derive, or restate a numeric value absent from its structured input. All arithmetic happens in deterministic code, and a post-generation validator rejects violations.
- LLM calls receive only ranked or aggregated payloads, never raw trip rows — token cost must stay independent of tenant data volume.
- Model tiering is mandatory: triage, routing, and chat intent on the cheap tier; causal reasoning and narrative on the strong tier.
- Per-tenant token budget is bounded. On exhaustion the system degrades to deterministic alerts rather than going dark.
- Agents reach data only through the metric-layer interface, never direct SQL, so porting onto a real platform is one adapter implementation.
- Metric definitions are versioned and single-sourced; ad-hoc SQL outside the catalog is not a supported path to a number.
- The sample dataset has not been received. Ingest is driven by a declared column mapping, not hardcoded field access.
- Every fact row carries `tenant_id` and the query layer injects the filter; no query path may omit it.
- A metric below its declared minimum sample size is returned as `insufficient_sample`, never as a number.
- Data-quality flags propagate into narrative output — a figure built on partial GPS coverage must say so.
- The prototype runs end to end on a laptop from the sample dataset, with no cloud infrastructure required.

## Non-goals

- Production-grade authentication, authorization, or security hardening.
- A full historical data pipeline, streaming ingestion, or backfill tooling.
- Integration with real vendor systems, dispatch systems, or live GPS feeds.
- Actions that affect real-world operations — dispatching, rebooking, or contacting actual vendors. Escalations are recorded, not delivered.
- Predictive or ML forecasting of future delays; the system explains what happened, not what will.
- Mobile applications.
- Multi-language output.

## Success signal

A transport & facilities head opens a brief the system generated without being asked, finds the two vendors responsible for the month's OTA gap already named with the arithmetic behind the claim, and forwards it to leadership unedited. On the same morning, the transport manager starts with three incidents worth acting on instead of a spreadsheet.

## Assumptions

- Dataset shape is assumed from the brief's description, because the file has not been received.
- The dataset is assumed to span enough history for period-over-period comparison. If it is a single snapshot, trend benchmarking degrades to SLA and peer only.
- Industry benchmark values are assumed to come from static configuration, since no external benchmark source is provided.
- Multi-tenancy is assumed to be demonstrated structurally on a single-tenant demo rather than proven at scale.
- Escalations and notifications are assumed to be recorded or simulated rather than delivered into real systems.
- Output is assumed English-only.

## Open Questions

- Which persona is the primary demo target? It decides where the L5 polish budget goes.
- What is the actual submission deadline? It decides Java (better scored on criterion 3) versus Python (faster to build) — see `stack.md`.
- Does the dataset carry employee-level roster and shift data? Without it, CAP-8's line-manager rendering cannot be served.
- Are SLA targets supplied in the dataset or brief, or do we define them ourselves?
- For the demo, is a real delivery channel (Slack, email) available, or should delivery be simulated?
- Does the dataset include a vendor identifier with enough volume per vendor for peer comparison to be statistically meaningful?
