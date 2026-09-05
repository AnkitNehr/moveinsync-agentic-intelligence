# Presentation deck — 10 slides

**Total: 8 minutes presenting + 5 minutes live demo (slides 5–7 are the demo).**
Every number is from `docs/findings/`, reproduced by `POST /api/runs`.

Formatting convention below:
- **ON SLIDE** — what the audience sees. Keep it sparse; they read faster than you talk.
- **SAY** — the exact line. The bolded sentence is the one that must land; everything else is scaffolding you can drop if you are short on time.
- **NOTES** — for you only. Anticipated questions and the answers.

---

## Slide 1 — A metric without context is just a number

**ON SLIDE**

> # OTA is 92.46%
>
> *(nothing else — full bleed, one number, large)*
>
> …then on click:
>
> | | |
> |---|---|
> | Last month | 95.31% |
> | SLA | 95% |
> | Industry | 93% |
> | Cause | ? |
> | Owner | ? |
> | Action | ? |

**SAY**

> "This is what a transport manager sees on a Monday morning. Ninety-two point four six percent.
> Is that good? You genuinely cannot tell. **A metric without context is just a number** — and
> getting the context is not an analytics problem, it's four hours of somebody's week, every week,
> pivoting spreadsheets to find out that it wasn't the vendors after all.
> The dashboard is not the bottleneck. The dashboard is fine. **What's missing is the person who
> reads it.**"

**NOTES** — This framing is lifted directly from the problem statement's pain point, deliberately.
Do not spend more than 45 seconds here. The audience already believes this; you are establishing
that you understood the brief, not selling them the problem.

---

## Slide 2 — The one decision: code computes, AI judges

**ON SLIDE**

> ### One architectural decision, applied without exception
>
> | Deterministic Java | The model |
> |---|---|
> | Ingest, 15 data quirks | — |
> | Every metric definition | — |
> | Every benchmark (trend · SLA · peer · industry) | — |
> | Anomaly detection, robust z | — |
> | **Attribution — rate vs mix** | — |
> | **Policy — what is a breach** | — |
> | — | Cluster and dedupe |
> | — | **Explain why** |
> | — | **Write it for a human** |
> | **Policy — what may we do** | — |
>
> ✅ `NoLlmInCoreTest` — build fails on an Anthropic import in the core
> ✅ `NumericValidator` — every generated figure must exist in its input
> ✅ `MixRateDecomposerTest` — contributions sum to the delta within `1e-9`

**SAY**

> "There is exactly one architectural decision in this system and everything else follows from it.
> **Code computes every number. The model only judges, explains, and writes.**
> The model never sees a trip row — it sees about four kilobytes of already-computed, already-ranked
> JSON. That's not a safety blanket, it's the design. It means the system can be *wrong about
> judgement*, which a human can argue with, and it **cannot be wrong about arithmetic**.
> And these aren't promises on a slide. The first one is a test that fails the build if anyone
> imports the Anthropic SDK into the metric layer. **The central claim of this pitch is a green
> test.**"

**NOTES** — If someone asks "isn't that just a wrapper?": no — see slide 3, the funnel *is* the
product; the LLM is the last 5% and the cheapest part. If asked why not let the LLM query SQL
directly: because then the chat endpoint and the dashboard would return different numbers for the
same question, and one of them would be wrong in a way nobody could detect.

---

## Slide 3 — The funnel, with real numbers

**ON SLIDE**

> ```
>  3,439,966 rows        ingested, 0 dropped              ← code, free
>    615,546 trips       May–Jul 2026
>      1,944 series      8 metrics × 9 grains             ← code, free
>         50 unusual     robust z + min_sample gate       ← code, free
>         20 candidates  scored, ranked                   ← code, free
>  ─────────────────────────────────────────────────────────
>          4 incidents   ← the model enters HERE          ← 12 calls, $0.52
>          3 personas    briefs written and routed
>          1 follow-up   scheduled for 3 days from now
> ```
>
> **Cost scales with findings, not with trips.**

**SAY**

> "Here's the whole system as one funnel. Three point four million rows in. Nineteen hundred and
> forty-four metric series evaluated. Fifty of them moved in a way that's statistically real. Twenty
> survive ranking. Four become incidents worth a human's attention.
> **The model enters at the second-to-last line.** Twelve calls, fifty-two cents.
> And here's the consequence that matters for deployability: **because the model only ever sees
> findings, ten times the data costs exactly the same.** Cost scales with how many things are
> actually wrong, not with how much data you have. That's the difference between a demo and
> something you can run across fifty tenants."

**NOTES** — The `min_sample` gate is worth one sentence if you have time: `trip_nodal='SHUTTLE'` is
244 trips and showed a −26.6 point swing. Without the gate that's your headline finding and it's
noise. Volume-gating is unglamorous and it is why the four findings are real.

---

## Slide 4 — Architecture

**ON SLIDE**

The mermaid diagram from `README.md` — ingest → metric → benchmark → anomaly → attribution →
**POLICY** → agents → **POLICY** → routing/delivery, with memory and audit loops drawn back into
detection. Colour-coded: **blue = deterministic · green = policy · amber = model · red = guard.**

Beneath it, three lines:

> **Policy runs twice** — before the AI (*is this a breach?*) and after (*what may we do?*)
> **Memory closes the loop** — suppress what's known, re-check in 3 days, escalate at 7
> **Every stage is a port** — no key? deterministic fallback. Whole pipeline still runs.

**SAY**

> "Left to right is one run. The thing I'd point at is the green boxes — **policy appears twice, and
> the AI is sandwiched between them.** Before the model, deterministic policy decides what counts as
> an SLA breach and at what severity. After the model, a second guard decides what we're allowed to
> *do* about it. The model gets to have an opinion; it never gets to have authority.
> The dotted lines going backwards are memory and audit. That's what makes this agentic rather than
> a report generator — it remembers what it already told you, and it comes back on its own.
> One more thing: **every agentic stage is behind an interface with a deterministic implementation.**
> Pull the API key out and the whole pipeline still runs end to end. You lose the prose. You don't
> lose the system."

**NOTES** — If asked about AWS: DuckDB is embedded so there's nothing to provision; the ports map
cleanly onto Bedrock for the model, S3/Athena or Redshift for the fact store, EventBridge for the
cadence. One class each. That's slide 9 — don't pre-empt it here.

---

## Slide 5 — DEMO 1: the June morning-bus story

**ON SLIDE**

> ### `POST /api/runs` → live
>
> **95.31% → 92.46%** · SLA 95% · first breach in the series
>
> | | Δ pts | | Δ pts |
> |---|---|---|---|
> | **LOGIN** | **−5.17** | LOGOUT | −0.77 |
> | **BUS** | **−6.25** | CAB | −2.20 |
> | **MANUAL** | **−6.22** | AUTO | −2.20 |
> | Denver | −4.15 | catalyst-Sac | −0.06 |
> | Clearwater | −4.07 | | |
> | **All 23 vendors** | **max share shift 0.79pt · mix effect 0.008** | | |

**SAY**

> "I'm pressing the button. While it runs — this is the finding I'd have missed.
> June's on-time rate dropped two point eight five points and broke the SLA. Every dashboard shows
> you that. What no dashboard shows you is that **eighty-five percent of it is in one corner.**
> Morning trips, not evening. Buses, not cabs. Manually-planned routes, not auto-planned. Two
> offices out of eighteen.
> And look at the bottom row. **We checked all twenty-three vendors and it wasn't them** — the
> biggest change in any vendor's share of trips was zero point seven nine of a point.
> That last line is the one I care about. The system didn't guess vendors and stop. **It scanned
> every dimension the metric declares, ranked them, and reported the losers too** — because 'we
> checked the vendors and it wasn't them' is a finding. It's the difference between writing a vendor
> a letter and phoning the routing desk at Denver. **One of those fixes it.**"

**NOTES** — Click into the attribution waterfall in the UI. Point at `mixEffect`: LOGIN is +0.61,
LOGOUT is −0.66, net −0.05. The fleet didn't change shape; the trips that ran got worse. Without
the rate/mix split you cannot tell those two apart and your recommended action is wrong.
Reconciliation shows error `0.0` against tolerance `1e-9` — the decomposition closes.

---

## Slide 6 — DEMO 2: the alarm that stopped ringing

**ON SLIDE**

> ### `EMPLOYEE_SIGN_OFF_TIME_VIOLATION`
>
> # 7,670 → 46 → 20
> ## −99.7%
>
> *(on click, in red)*
>
> > **This is not a safety improvement.**
>
> | Check | Result |
> |---|---|
> | Shape | Cliff on **18 May**, not a decay: 3,467 → 4,112 → **2** → 2 → 38 |
> | Other alerts, same BU | Ran straight through: 750, 575, 865, 875, 714, 706 |
> | Trip volume | **Grew**: 75,165 → 88,035 → 88,574 |
> | Were they triaged? | **7,627 of 7,670** were `severity=NA`, auto-closed at 24h — never seen by a human |
> | The survivors | `Sev-3`, human-acked, fire at 20:00–23:00. May's peaked at 15:00. **Different detector.** |
> | Alert rate ex-sign-off | 35.73 → 39.43 → 37.88 — **flat** |

**SAY**

> "This is the one I'd put the whole submission on.
> A safety alert dropped by ninety-nine point seven percent. Best number of the quarter.
> **A dashboard renders the alerts that fired. It cannot render the alerts that stopped.** There is
> no chart in any BI tool anywhere that shows you an absence. This system finds it because it scans
> series for absence as well as presence.
> But finding it is only half. Look at what it does next — it *refuses to call it good news.*
> Clean cliff on the eighteenth of May, not a decay. The same business unit's other alerts never
> paused. Trip volume actually grew. And seven thousand six hundred and twenty-seven of the seven
> thousand six hundred and seventy alerts were auto-closed at twenty-four hours and **never triaged
> by a human at all.**
> Strip sign-off out and the alert rate is thirty-five, thirty-nine, thirty-seven. **Flat. Nothing
> improved.** Seven thousand six hundred and sixty-four alerts that were never real got switched off,
> and someone was about to put minus ninety-nine point seven percent in a board pack as a safety win.
> **An agent that reported 'safety improved' would have been fluent, confident, and wrong.** That's
> the failure mode everyone's afraid of with this technology, and it's the one we spent the effort on."

**NOTES** — This is your strongest 60 seconds. Do not rush it and do not add to it. If asked how the
system knows to be sceptical: the reasoning agent has read-only tools for exactly these checks
(volume in the same period, sibling series, severity distribution, time-of-day signature), and the
`whyNow` field is required to survive `NumericValidator`. It cannot assert a cause it did not check.

---

## Slide 7 — DEMO 3: cost-per-km is a broken metric

**ON SLIDE**

> ### 42% of billing rows report **zero kilometres**
> That is not missing data. Those are **fixed-rate contracts.**
>
> | Contract | Rows | Zero-km | Naive cost/km |
> |---|---|---|---|
> | 6S-HYD | 23,945 | 99.97% | **₹180,538** |
> | 4S-HYD | 24,530 | 99.96% | ₹146,668 |
> | 4Seater | 151,770 | 0.12% | ₹83 |
> | DV_Package | 78,410 | 0.30% | ₹100 |
>
> **Defined segment:** ₹77.29 → **₹80.24** → ₹78.49 · full coverage · 368,849 rows
>
> ```yaml
> # cost_per_km.yaml
> segment_by: billing_regime
> valid_segments: [DISTANCE_BASED]
> ```
> *One line of config. The dashboard, the agent and the chat endpoint cannot disagree.*

**SAY**

> "Last one, and this is the deployability argument.
> Forty-two percent of the billing rows have zero kilometres on them. The obvious read is 'missing
> data, filter it out.' It isn't. **Those are fixed-rate contracts — distance is not what's being
> billed.** Divide their cost by their distance and you get a hundred and eighty thousand rupees per
> kilometre. Arithmetically real. Operationally meaningless.
> So the system doesn't compute it. Not because someone wrote an if-statement — because
> **cost-per-km is declared in YAML as undefined outside the distance-based segment**, and the metric
> layer appends that predicate to every query. Ask it in the chat window and it tells you the metric
> is undefined for that contract and offers you cost-per-trip instead.
> **A number that isn't computable is a better answer than a number that's wrong**, and it's the
> answer everywhere at once — dashboard, agent, chat — because it's one line of config, not three
> implementations that will drift apart in six months.
> Where the metric *is* defined it's stable and it's rising: seventy-seven, eighty, seventy-eight.
> That June step is a real question to ask. The blended number was never a question at all."

**NOTES** — If you have 20 spare seconds, the `BUS-ORRNEW-TT` finding is the money line: one office,
no slabs, identical 12-seat vehicles, nothing left to control for — and vendors are paid 30–36%
differently. ₹9.15M over three months. Only mention it if the room is engaged; it's a bonus, not a
pillar.

---

## Slide 8 — Cost at scale and latency

**ON SLIDE**

> | Stage | Tier | Model | Calls | USD |
> |---|---|---|---|---|
> | Triage | MID | sonnet-5 | 1 batched | $0.045 |
> | Reason | STRONG | opus-5 | 8 | $0.315 |
> | Narrate | STRONG | opus-5 | 3 | $0.161 |
> | Ingest → policy → guard → audit | — | none | 0 | **$0.000** |
> | **Per run** | | | **12** | **$0.52** |
>
> | | |
> |---|---|
> | Nightly runs, 30/mo | $15.60 |
> | Chat, 200 q/day @ haiku | $24.00 |
> | **Per tenant / month** | **≈ $40** |
> | **50 tenants** | **≈ $2,000/mo** |
>
> **Latency:** deterministic core **~15s** end to end · full agentic run **~4 min**
> **Cache-aware pricing** — catalog + persona guides + SLA config in a byte-identical prefix, reads at 0.10×
> **`RunSummary` carries tokens, cost and per-stage timings on every run — it's a receipt, not an estimate**

**SAY**

> "Twenty percent of the marks are 'can you actually run this,' so: fifty-two cents a run.
> Three tiers, and they're chosen on difficulty, not taste. Triage is structural work over
> structured input — Sonnet, one batched call. Causal reasoning and the stakeholder narrative are
> the two things a reader will judge us on, and they're the only two worth Opus money. Chat is
> Haiku, because the numbers are already computed and the model is only phrasing them.
> Forty dollars per tenant per month. **That's under an hour of a transport manager's time, against
> a system that reads three point four million rows every night.**
> Latency: the deterministic core is fifteen seconds. The full run is four minutes, and three and a
> half of those are Opus writing. If you need it faster, the deterministic path already produced
> every number — you're only waiting on the prose.
> And that cost figure isn't modelled. **Every single run returns its own token count and its own
> price.** It's a receipt."

**NOTES** — If challenged on the $0.52: it assumes 4 incidents, which is what June actually
produced. A pathological month with 20 incidents is roughly 5× reason and narrate, so ~$2.20 —
still trivial. The `top-n: 20` cap in config is a hard ceiling on spend per run.

---

## Slide 9 — How it extends, and how it deploys

**ON SLIDE**

> | Change | You touch | Code |
> |---|---|---|
> | **New metric** | one YAML file | **none** |
> | New grain / SLA / benchmark / cadence / tenant | config | **none** |
> | New persona | config | **none** |
> | Kafka instead of CSV | `TripSource` | **1 class** |
> | Redshift instead of DuckDB | `FactStore` | **1 class** |
> | Bedrock / self-hosted model | `ModelClient` | **1 class** |
> | Slack instead of console | `NotificationSink` | **1 class** |
>
> **Multi-tenancy is already there** — `business_unit` is a predicate at every grain; 5 BUs running side by side today.
> **Nothing to provision** — DuckDB is in-process. `git clone`, `mvn spring-boot:run`, done.
> **Degrades, doesn't fail** — no API key → deterministic fallbacks → pipeline still completes.

**SAY**

> "The seams. **A new metric is a YAML file — no Java.** You declare the formula, the grains, the
> volume gate, the SLA key and the caveats, and the scanner, the benchmarker, the attribution
> engine, the chat endpoint and the dashboard all pick it up on restart. That's eight metrics in the
> catalog today and none of them required a code change after the first one.
> Everything infrastructural is one class. Kafka instead of CSV, Redshift instead of DuckDB, Bedrock
> instead of the Anthropic API, Slack instead of the console — one implementation each, because the
> core defines the interfaces and the arrows only point inward. **That's the same discipline that
> keeps the LLM out of the metric layer.**
> Multi-tenancy isn't future work — business unit is a predicate at every grain and there are five
> of them running in the demo data right now.
> And to be plain about what this is: it isn't a product. **It's a layer you'd drop into the platform
> you already have**, next to the dashboard, not instead of it."

**NOTES** — Expected question: "what about real-time?" Honest answer — the cadence is nightly
because the decisions are nightly; a transport manager doesn't re-plan routes at 11am. The
`CadenceScheduler` is configurable to hourly and the deterministic core runs in 15 seconds, so
nothing structural stops it. Don't oversell this.

---

## Slide 10 — The ask

**ON SLIDE**

> ### What we built
> An agentic layer that finds what a dashboard structurally cannot — and refuses to overclaim it.
>
> ### The three findings, again
> **1.** June's SLA breach is a morning-bus routing problem at two offices — **not a vendor problem**
> **2.** A 99.7% safety improvement that is **a detector being switched off**
> **3.** Cost-per-km is **undefined for 42% of the spend** — and now the system says so
>
> ### The ask
> > **Point it at one real tenant's live extract for two weeks.**
> > Nothing to provision. Forty dollars.
> > Judge it on how many of its findings a human agrees with.
>
> `github.com/AnkitNehr/moveinsync-agentic-intelligence`

**SAY**

> "Three findings on your data. One of them changes who gets the phone call. One of them stops a
> false safety claim from reaching a board pack. One of them retires a number that's been wrong for
> as long as it's been reported.
> **None of the three came from the AI computing anything.** They came from deterministic code doing
> the arithmetic honestly, and a model doing the part code is bad at — judging what's worth
> escalating and explaining it to a human who has to act on it.
> So the ask is small, because it has to be: **point it at one real tenant's extract for two weeks.**
> There's nothing to provision, it costs forty dollars, and it runs without an API key if you'd
> rather see the deterministic half first.
> Then judge it on one thing — **how many of its findings a human agrees with.** That's the only
> metric that matters, and it's the one we'd want to be held to."

**NOTES** — Stop talking. Do not add a summary. If there's silence, the next words should be
theirs. Have `docs/findings/` open in a tab: every claim in this deck has a write-up behind it with
the artifact checks that were run, including the two findings that were killed by those checks.
Offering that unprompted is the strongest possible close.

---

## Backup slides (only if asked)

| # | If they ask | Show |
|---|---|---|
| B1 | "How do you handle messy data?" | The 15-quirk table from `README.md`. Lead with #2: `bill_data.trip_id` contains the literal string `'OverHead'`, which crashes a plain `CAST` — and it is **not** in the supplied data dictionary. |
| B2 | "How do you stop it hallucinating numbers?" | `NumericValidator` — extract every figure from the generated text, check it exists in the input, reject and retry naming the offending figure, then fall back to a deterministic template. Plus `NoLlmInCoreTest`. |
| B3 | "Show me it's actually agentic" | `FollowUpScheduler`. The incident carries `followUpAt` three days out; at day 7 it escalates **unprompted** if the metric hasn't recovered. Plus `Suppression` — it won't re-raise what it already told you. |
| B4 | "What did you get wrong?" | `docs/findings/` documents two round-1 findings killed by round-2 artifact checks, and a timezone error (assumed 7h offset, actual 5h/6h by office) that inverted the escort curve before it was caught. Answer this one honestly; it buys more credibility than any slide. |
| B5 | "What's the weakest part?" | The SLA target for `cost_per_km` is configured at 25.0 against an observed 77–80, so it reads as a standing 3× breach. It's reported as measured and flagged as needing recalibration — it is not silently suppressed. Also: rating `0` may mean *unrated*, which we chose to exclude; the decision and its impact are in `docs/findings/feedback.md`. |
