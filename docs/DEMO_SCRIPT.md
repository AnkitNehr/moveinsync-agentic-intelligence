# Demo run sheet — 5 minutes

One operator, one screen, three findings. **Total 5:00.** The timings below are budgets, not
targets — if you are over at a checkpoint, cut from §4 first, then §5. Never cut §3.

**The rule for this demo:** you talk while it computes. There is no moment where you and the
audience watch a spinner together. Every wait is pre-loaded with something to say.

---

## T−10 minutes — setup (do this before anyone is watching)

```bash
cd "moveinsync assesment"

# 1. Backend. Leave running. Wait for "Ingest complete in ~8000 ms".
export ANTHROPIC_API_KEY=sk-...
mvn spring-boot:run

# 2. Frontend, separate terminal. Wait for "Compiled successfully".
cd frontend && npm install && npm start

# 3. PRIME THE DEMO — run once now, so the fallback in §Fallback A is warm and real.
curl -s -X POST localhost:8080/api/runs \
     -H 'Content-Type: application/json' \
     -d '{"period":"2026-06-01","priorPeriod":"2026-05-01"}' | tee /tmp/mis-primed-run.json

# 4. Verify. All three must be true before you present.
curl -s localhost:8080/api/health | grep -E '"status"|"llmAvailable"|"droppedRows"'
#   "status":"READY"   "llmAvailable":true   "droppedRows":0
```

**Windows to have open, in this order (Cmd-` / Alt-Tab between them — do not use a browser with 20 tabs):**

| # | Window | Pre-loaded to |
|---|---|---|
| 1 | Browser | `http://localhost:4200` — **Dashboard**, scrolled to top |
| 2 | Browser tab | `http://localhost:4200/incidents/INC-2026-06-002` — the alert incident, **already loaded** |
| 3 | Terminal (large font, dark) | `cd` into repo, command history primed with the `POST /api/runs` curl |
| 4 | Editor | `src/main/resources/metrics/cost_per_km.yaml`, scrolled to `segment_by:` |
| 5 | Browser tab (**closed by default**) | `docs/findings/safety.md` — Fallback B only |

Set terminal font to ≥18pt. Turn off notifications. Close Slack.

---

## 0:00 – 0:30 · The frame

**Window 1 — Dashboard, top of page.**

The KPI strip is showing **OTA 92.46%** with an amber SLA badge.

> **SAY:** "This is a transport manager's Monday morning. On-time arrival, ninety-two point four
> six percent. Is that good? You can't tell — and finding out is four hours of pivoting
> spreadsheets. **A metric without context is just a number.** The dashboard isn't the bottleneck.
> What's missing is the person who reads it. That's what this is."

⏱ **Checkpoint 0:30.** Do not go over. Move.

---

## 0:30 – 1:00 · Press the button

**Window 3 — Terminal.** Type it live; don't paste. It's four seconds and it makes the point that
this is one call.

```bash
curl -X POST localhost:8080/api/runs -H 'Content-Type: application/json' \
     -d '{"period":"2026-06-01","priorPeriod":"2026-05-01"}'
```

> **SAY, immediately, while it runs:** "One POST. Three point four million rows, five sources, May
> to July. While that goes — here's the shape of it. Everything up to the fourth line of that
> funnel is deterministic Java: ingest, metric definitions, benchmarking, anomaly detection,
> attribution, policy. **Nineteen hundred series evaluated, twenty candidates ranked, and only then
> does a model get involved** — over about four kilobytes of already-computed JSON. It never sees a
> trip row. That's the whole design: **code computes, AI judges.**"

The run takes ~4 minutes with LLM. **You are not going to wait for it.** Let it stream in the
background and switch away.

> **SAY:** "That'll take four minutes, three and a half of which is Opus writing prose. I'm not
> going to make you watch it — here's the run from ten minutes ago, same period, same numbers."

**Switch to Window 1.** Hit refresh — the primed run's incidents are already there.

⏱ **Checkpoint 1:00.**

---

## 1:00 – 2:15 · Finding 1 — the June morning-bus story

**Window 1 — Dashboard.** Click incident **INC-2026-06-001** (top of the list, priority 1).

> **SAY:** "June broke the SLA — ninety-five point three one down to ninety-two point four six.
> Every dashboard shows you that much. Here's what it can't."

**Click the attribution waterfall.** This is the centrepiece of the whole demo. Let it render, then
point at rows as you speak.

> **SAY, pointing:** "Eighty-five percent of the drop is in one corner. **Morning trips, minus five
> point one seven — evening, minus zero point seven seven.** Buses minus six point two five, cabs
> minus two point two. Manually-planned routes minus six point two two, auto-planned minus two
> point two. Two offices out of eighteen — Denver and Clearwater — while catalyst-Sac is flat at
> minus zero point zero six."

**Scroll to the bottom of the ranked dimension list — the `vendor` row.**

> **SAY:** "And this is the row I actually care about. **All twenty-three vendors, ranked last.**
> The biggest change in any vendor's share of trips was zero point seven nine of a point. The
> system checked the vendors and it wasn't them — **and it says so, rather than staying silent.**
> That's the difference between writing a vendor a letter and phoning the routing desk at Denver.
> One of those fixes it."

**Scroll to `recommendedActions`.** Point at `vendor_escalation`.

> **SAY:** "And look — it *refuses* to raise a vendor escalation. Not because escalation is
> disabled, but because **the evidence doesn't support it, and it gives you the number**: vendor
> explanatory power zero point zero seven. Click it anyway — four-oh-three, same reason on screen.
> The model can have an opinion. It never gets authority."

**Click `notify`.** Then **Outbox** tab.

> **SAY:** "Notify already went. Routing desk, not vendor ops — because LOGIN and MANUAL won, not
> vendor. This is the artefact a manager forwards. The dashboard was the sensing. This is the act."

**Back on the incident. Re-check period `2026-07`. Click Run follow-up now.**

> **SAY:** "And it promised to look again. I am not waiting three days. July is on disk. One click
> and the loop either closes quietly or escalates — nobody prompted it except the calendar, and
> today the calendar is this button."

⏱ **Checkpoint 2:45.** If you're at 2:55, skip the follow-up click and go. Never skip the locked vendor letter.

---

## 2:45 – 3:40 · Finding 2 — the alarm that stopped ringing

**Switch to Window 2** (already loaded — do not navigate, do not search).

> **SAY:** "This is the one I'd put the whole thing on."

Point at the headline: **7,670 → 46 → 20, −99.7%**.

> **SAY:** "A safety alert dropped ninety-nine point seven percent. Best number of the quarter.
> **A dashboard renders the alerts that fired. It structurally cannot render the alerts that
> stopped.** There is no chart anywhere that shows you an absence. This finds it because it scans
> for absence as well as presence.
> But finding it is half of it. Watch what it does next — **it refuses to call it good news.**"

**Scroll to the evidence list.** Read the four checks off the screen, fast.

> **SAY:** "Clean cliff on the eighteenth of May, not a decay — three thousand four hundred, four
> thousand one hundred, then **two**. The same business unit's other alerts ran straight through
> the cutover. Trip volume actually *grew*. And seven thousand six hundred and twenty-seven of the
> seven thousand six hundred and seventy were auto-closed at twenty-four hours — **never triaged by
> a human at all.**
> Strip sign-off out and the alert rate is thirty-five, thirty-nine, thirty-seven. **Flat. Nothing
> improved.** Seven thousand six hundred and sixty-four alerts that were never real got switched
> off, and someone was about to put minus ninety-nine point seven percent in a board pack as a
> safety win.
> **An agent that reported 'safety improved' would have been fluent, confident, and wrong.** That's
> the failure mode everyone is afraid of with this technology. It's the one we spent the effort on."

⏱ **Checkpoint 3:40.** This is the emotional peak. Pause for one beat before moving.

---

## 3:40 – 4:20 · Finding 3 — cost-per-km is broken

**Window 1 → Chat tab.** Type the question live:

```
what is our cost per km on the 4S-HYD contract in June?
```

> **SAY while it answers:** "Forty-two percent of the billing rows have zero kilometres. Obvious
> read: missing data, filter it out. It isn't — **those are fixed-rate contracts. Distance isn't
> what's being billed.** Divide cost by distance and you get a hundred and eighty thousand rupees
> per kilometre. Arithmetically real. Operationally meaningless."

The answer returns: *"cost_per_km is not defined for 4S-HYD… 99.96% of its 24,530 rows report zero
distance… on the segment where it is defined, June was ₹80.24 against ₹77.29 in May."*

**Switch to Window 4 — the YAML, already scrolled to the right lines.**

> **SAY:** "And it's not an if-statement someone wrote in the chat handler. **It's two lines of
> config in the metric definition** — `segment_by: billing_regime`, `valid_segments:
> DISTANCE_BASED` — and the metric layer appends that predicate to every query for this metric.
> Dashboard, reasoning agent, chat endpoint: **same guard, one place, cannot drift apart.**
> **A number that isn't computable is a better answer than a number that's wrong.**"

⏱ **Checkpoint 4:20.**

---

## 4:20 – 5:00 · The close

**Window 3 — Terminal.** Your live run has finished by now. Show its tail.

```bash
curl -s localhost:8080/api/runs/latest | jq '.summary'
```

> **SAY, pointing at `estimatedCostUsd`:** "That's my live run finishing. Four incidents. Twelve
> model calls. **Fifty-two cents.** And that's not a modelled figure — **every run returns its own
> token count and its own price. It's a receipt.**
> Forty dollars a tenant a month, all in. Under an hour of a transport manager's time, against a
> system that reads three point four million rows a night. And because the model only ever sees
> *findings*, **ten times the data costs the same.**
> Three findings on your data. One changes who gets the phone call. One stops a false safety claim
> reaching a board pack. One retires a number that's been wrong for as long as it's been reported.
> **None of them came from the AI computing anything.**
> The ask: point it at one real tenant's extract for two weeks. Nothing to provision. Then judge it
> on how many of its findings a human agrees with."

**Stop talking.** ⏱ **5:00.**

---

# Fallbacks

Read these before you present. You will not have time to read them during.

## Fallback A — the LLM call fails mid-demo (most likely failure)

**Symptoms:** the run hangs past ~5 minutes; terminal shows `429`, `529`, a timeout, or the UI
incident list stays empty.

**You already have the fix, because you primed at T−10.** The dashboard in Window 1 is rendering
the *primed* run, not the live one. **Nothing on screen is affected.** Finish the demo exactly as
written and change only the 4:20 close:

```bash
jq '{incidents, promptTokens, completionTokens, estimatedCostUsd, wallClockMs}' /tmp/mis-primed-run.json
```

> **SAY:** "The live call's timed out on me — which is worth thirty seconds, because it's the case
> we designed for. **Every agentic stage sits behind an interface with a deterministic
> implementation.** Watch."

Then, live:

```bash
curl -s -X POST localhost:8080/api/runs \
     -H 'Content-Type: application/json' -H 'X-Force-Deterministic: true' \
     -d '{"period":"2026-06-01","priorPeriod":"2026-05-01"}' | jq '{incidents, estimatedCostUsd, wallClockMs}'
```

```json
{ "incidents": 4, "estimatedCostUsd": 0.0, "wallClockMs": 14980 }
```

> **SAY:** "**Same four incidents. Same numbers. Fifteen seconds. Zero dollars.** The prose is
> templated instead of written, and that's the entire loss. Every figure in this demo was computed
> by deterministic Java — **the model was never load-bearing for correctness, only for
> explanation.** An outage degrades this system. It doesn't stop it."

*This is a stronger demo than the one you planned.* If the LLM fails, you have been handed the
architecture argument for free. Take it.

*(If the header isn't wired in your build, get the same result by restarting with
`--app.llm.enabled=false`, or by unsetting `ANTHROPIC_API_KEY` before `mvn spring-boot:run`.
Rehearse whichever one your build supports — once, before the demo.)*

## Fallback B — a number on screen doesn't match what you're saying

**Do not talk over it. Do not hand-wave.** You have the receipts; use them.

> **SAY:** "That's not the figure I expected — let me show you where it comes from rather than
> guess."

Open **Window 5** (`docs/findings/safety.md` or the relevant file) and show the query output the
claim was derived from. Every number in this demo has a write-up in `docs/findings/` with the
artifact checks that were run against it — **including two round-1 findings that those checks
killed, and a timezone error we made and caught.**

> **SAY:** "Every claim in here has a write-up with the checks behind it, including two findings we
> killed ourselves. That's the standard we held it to."

Being able to do this is worth more than the finding you lost.

## Fallback C — the backend won't start or the dataset isn't loaded

**Check first (10 seconds):**

```bash
curl -s localhost:8080/api/health | jq '{status, datasetReady, rows, llmAvailable, llmReason}'
```

| `status` | Meaning | Do this |
|---|---|---|
| connection refused | Backend down | Restart: `mvn spring-boot:run`. Present slides 1–4 while it boots (~40s + 8s ingest). |
| `"DEGRADED"`, `datasetReady:false` | CSVs missing from `data/raw/` | `ls data/raw/` — **filenames contain a space** (`Ride_data _trip-may_2026.csv`). Do not rename them; the glob is `Ride_data*.csv`. |
| `"READY"`, `llmAvailable:false` | No API key | Run the whole demo on the deterministic path and lead with it — see Fallback A's script. It costs you the prose, nothing else. |

**If nothing recovers:** present from `docs/SAMPLE_IO.md`. It contains the real payloads for every
endpoint in this run sheet, with the real numbers. Walk it top to bottom in the same order as this
script. The findings are the demo; the UI is the packaging.

## Fallback D — you are over time at 3:40

Cut in this order, and only in this order:

1. **§3:40–4:20 (cost-per-km)** — hardest to land quickly, easiest to lose. Replace with one line:
   *"There's a third finding — cost-per-km is undefined for forty-two percent of the spend and the
   system says so instead of computing it. It's in the README."*
2. **The follow-up click in §1:00–2:45.** Keep the locked vendor letter.
3. **§0:00–0:30 (the frame)** — open cold on the attribution waterfall instead.

**Never cut §2:45–3:40.** The alert that went silent is the finding no dashboard can produce, and
it is the only thing in this demo that a competing submission cannot also claim.

---

## One-card cheat sheet

Print this. Numbers you must be able to say without looking:

| | |
|---|---|
| OTA | **95.31 → 92.46 → 94.69** · SLA 95 · industry 93 |
| Concentration | LOGIN **−5.17** / LOGOUT −0.77 · BUS **−6.25** / CAB −2.20 · MANUAL **−6.22** / AUTO −2.20 |
| Offices | Denver −4.15 · Clearwater −4.07 · catalyst-Sac −0.06 |
| Vendors | 23 vendors · max share shift **0.79pt** · mix effect **0.008** |
| Alert | **7,670 → 46 → 20 = −99.7%** · cliff **18 May** · **7,627** auto-closed, never triaged · ex-sign-off rate **35.73 → 39.43 → 37.88, flat** |
| Cost | **42%** zero-km · 6S-HYD naive **₹180,538/km** · defined segment **₹77.29 → 80.24 → 78.49** |
| Scale | 3,439,966 rows · 1,944 series · 20 candidates · **4 incidents** · **12 calls** · **$0.52** · **~$40/tenant/mo** |
| Latency | deterministic **~15s** · full run **~4 min** |
