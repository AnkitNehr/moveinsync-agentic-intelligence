# Personas & Output Shaping

Companion to [SPEC.md](SPEC.md). Backs CAP-8 and CAP-12.

Three personas, one pipeline. Persona is a parameter on the narrative agent, not three separate systems — that is what makes CAP-8's "one incident produces three renderings" testable.

## The three

| Persona | Owns | Needs | Failure mode today |
| --- | --- | --- | --- |
| **Transport manager** (operational) | Day-to-day ops: vendor coordination, escalations, shift planning, delay management | Fast, actionable signals | Drowns in reports that arrive too late to act on |
| **Transport & facilities head** (strategic) | Budget, SLA accountability, vendor strategy, leadership reporting | A coherent cost / safety / experience story, assembled | Spends hours building the leadership deck by hand |
| **Team / line manager** (shift-based) | Floor and ops readiness for a shift | Who made it, who was late, how delays ripple | No shift-level visibility at all |

## Rendering matrix

| Persona | Trigger | Form | Content |
| --- | --- | --- | --- |
| Transport manager | Real-time, on SLA breach or promoted incident | Push notification (Slack / Teams) | Cause, attribution, one recommended action, escalate control |
| T&F head | Weekly and monthly | Forwardable document | Cost / safety / experience narrative, SLA posture, vendor ranking, trend context |
| Line manager | Before shift start | Digest | Who is late, ETA impact, floor-readiness delta for the shift |

## The forwardable-without-rework bar

The T&F head output targets the brief's bonus criterion directly. To clear it, a rendering must:

1. Open with the conclusion, not the methodology.
2. Name responsible entities explicitly, with their contribution quantified (from CAP-5).
3. State every number against a reference point — trend, SLA, peer, or industry (from CAP-3).
4. Disclose data-quality caveats inline rather than in a footnote.
5. Contain no system jargon, no metric ids, no internal identifiers in the prose.
6. Be self-contained — a reader with no access to the tool understands it fully.

A rendering failing any of these is not leadership-ready, and this list is the acceptance checklist for CAP-8.

## Console (CAP-12)

The transport manager's surface. Lists open incidents; drills from an incident into its evidence, attribution breakdown, and the underlying metric trend; offers dismiss and escalate.

Dismissal is not cosmetic — it writes a suppression to memory, which feeds the candidate ranker, so the same pattern scores lower next run. That feedback path is what keeps the system from re-raising what the operator has already judged irrelevant.
