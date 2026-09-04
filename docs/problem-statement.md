# MoveInSync Hackathon — Problem Statement

**Title:** Agentic Intelligence & Reporting Layer for Enterprise Mobility
**Theme:** Agentic AI (domain: Enterprise Mobility / Operations Intelligence)

## Background

Large enterprises move a few hundred to a few thousand employees daily through a mix of
home and nodal pick-and-drop cabs and fixed-route shuttles. Transport managers are
accountable for cost, safety, experience, and sustainability — but most of their time goes
into assembling data, not acting on it. The signal is rich. The insight is missing. The
actions are manual.

## Personas

| Persona | Scope | Needs |
| --- | --- | --- |
| **Transport manager** (operational) | Day-to-day ops: vendor coordination, escalations, shift planning, delay management | Fast, actionable signals — not reports |
| **Transport & facilities head** (strategic) | Budget, SLA accountability, vendor strategy, leadership reporting | A coherent cost/safety/experience story without assembling it manually |
| **Team / line manager** (shift-based ops) | Shift-level visibility | Who made it, who was late, how delays ripple into floor/ops readiness |

## Problem Definition

Mobility operations generate rich structured data continuously (trips, vendors, drivers,
employees — ops scale, timeliness/delays, safety/compliance, cost, sustainability, employee
experience, vendor performance). Today this largely sits in static weekly/monthly reports.

**Pain point:** a metric without context is just a number. "OTA is 78%" matters far less than
"it was 85% last month, SLA is 90%, and two vendors are responsible for the gap."
Benchmarking against historical trend / SLA / industry norm / peer is currently absent.

**Desired improvement:** an agentic layer that *senses* what's happening, *reasons* about what
it means, and *acts* — with minimal human prompting — surfacing what matters, benchmarking
it, and communicating outcomes to the right person at the right time.

## Tech Stack

Open / participant's choice — *preferably Java, Angular, AWS resources, but not restrictive.*

## Resources Provided

Sample dataset only: anonymised trip logs across cab, nodal, and shuttle modes — including
vendor performance, GPS traces, delay records, cost data, and employee feedback.

## Expected Output

Solutions may take any of the following forms, or combine several:

- Conversational agent (NL Q&A on mobility data)
- Proactive alerting & triggers
- Automated reporting & narratives
- Insight & anomaly detection
- Decision-support dashboard
- Automated communications

## Requirements

### Mandatory

- Working, demo-able prototype running on the provided dataset
- Agentic behaviour — senses, reasons, and acts; not a passive dashboard or query-only tool
- Serves at least one of the three named personas
- Contextualises metrics against at least one reference point (historical trend, SLA/goal,
  industry benchmark, or peer comparison)

### Good-to-have

- Combines two or more of the solution forms listed above
- Handles messy or missing data gracefully (GPS gaps, unmatched records, incomplete rosters)
- Proactive triggers rather than purely on-demand responses

### Bonus

- Credible deployability story into an existing enterprise mobility platform — multi-tenancy,
  latency, cost
- Output a transport & facilities head could forward to leadership without rework

### Not expected

- Production-grade authentication or security
- A full historical data pipeline
- Integration with real vendor systems

### Constraints

- Anonymised sample trip-log dataset only — no live system access

## Evaluation Criteria

| # | Criteria | What we are looking for | Weight |
| --- | --- | --- | --- |
| 1 | Business impact & experience | Does it meaningfully reduce manager effort or surface decisions that would otherwise be missed — and does it land? Clarity for the intended persona, leadership-ready output, shareable without rework. | **35** |
| 2 | Agentic design & cost at scale | Is AI solving a genuine problem rather than decorating the solution — and can it actually be run? Inference cost per interaction, latency, efficiency at enterprise volumes. | **20** |
| 3 | Architecture & code quality | Sound structure and engineering judgement; deployable into an existing platform; choices a team could build on. | **20** |
| 4 | Functionality | It runs — a working, demo-able prototype, end to end, on the provided dataset. | **25** |
| | | **Total** | **100** |

## Deliverables

- Source code repository (GitHub/GitLab)
- Architecture diagram
- README + setup instructions
- Sample inputs/outputs
- Demo video (if requested)
- Presentation deck
- Live demo
