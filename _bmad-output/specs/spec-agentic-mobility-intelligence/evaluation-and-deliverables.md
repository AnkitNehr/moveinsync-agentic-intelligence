# Evaluation, Scope Ladder & Deliverables

Companion to [SPEC.md](SPEC.md). The scoring reality the build sequence is optimised against.

## Weights

| # | Criterion | What is looked for | Weight |
| --- | --- | --- | --- |
| 1 | Business impact & experience | Meaningfully reduces manager effort or surfaces decisions otherwise missed; clarity for the persona; leadership-ready and shareable without rework | **35** |
| 2 | Agentic design & cost at scale | AI solving a genuine problem rather than decorating; inference cost per interaction, latency, efficiency at enterprise volume | **20** |
| 3 | Architecture & code quality | Sound structure and engineering judgement; deployable into an existing platform | **20** |
| 4 | Functionality | It runs, end to end, on the provided dataset | **25** |

Criterion 1 is where attribution (CAP-5) pays. Criterion 2 is where the deterministic-core thesis pays and where most entries will lose points by ignoring cost entirely.

## Requirement coverage

**Mandatory:**

| Requirement | Covered by |
| --- | --- |
| Working demo-able prototype on the provided dataset | CAP-1, CAP-9; local-first constraint |
| Agentic — senses, reasons, acts; not a passive dashboard | CAP-4/6 (sense), CAP-7 (reason), CAP-11 (act) |
| Serves at least one named persona | CAP-8; all three covered in `personas.md` |
| Contextualises against at least one reference point | CAP-3 — all four reference types |

**Good-to-have:**

| Item | Covered by |
| --- | --- |
| Combines two or more solution forms | Conversational (CAP-10), proactive alerting (CAP-9/11), automated reporting (CAP-8), anomaly detection (CAP-4), dashboard (CAP-12), automated comms (CAP-11) — six of six |
| Handles messy or missing data gracefully | CAP-1 quality vector; flags propagate into narrative |
| Proactive triggers rather than on-demand only | CAP-9, CAP-11 follow-up loop |

**Bonus:**

| Item | Covered by |
| --- | --- |
| Credible deployability — multi-tenancy, latency, cost | `stack.md`; CAP-13 |
| Output forwardable to leadership without rework | CAP-8; six-point bar in `personas.md` |

## Scope ladder

Build in this order. Each level is independently demo-able, so an overrun still leaves something that runs.

| Level | Scope | Priority |
| --- | --- | --- |
| **L0** | Ingest + metric catalog + benchmarks — numbers with context | must |
| **L1** | Anomaly detection + attribution — *which vendor caused it* | must, the differentiator |
| **L2** | Triage, reasoning, narrative; proactive daily digest | must, the agentic mandate |
| **L3** | Conversational agent over the semantic layer | should |
| **L4** | Action agent: escalation, follow-up loop, self-escalation | should, closes the loop |
| **L5** | Angular console + leadership brief export | polish |

**L0–L2 alone satisfies every mandatory requirement.** Everything above is score.

## Deliverables

- Source code repository
- Architecture diagram — see `architecture-diagrams.md`
- README + setup instructions
- Sample inputs/outputs
- Demo video (if requested)
- Presentation deck
- Live demo

## Constraints from the brief

- Anonymised sample trip-log dataset only; no live system access.
- Not expected: production auth/security, a full historical pipeline, real vendor integrations.
