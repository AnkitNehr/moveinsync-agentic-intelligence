# Overnight status — read this first

Last updated by the overnight run. Check `git log` for what landed.

## What you have

**Repo:** https://github.com/AnkitNehr/moveinsync-agentic-intelligence (private)

**Dataset:** `data/raw/` — 3.4M rows, May–Jul 2026, gitignored. Dictionaries in
`data/dictionary/`.

## Start it

```bash
cd "moveinsync assesment"

# backend — :8080
export ANTHROPIC_API_KEY=sk-...        # OPTIONAL: runs fully without it
/opt/homebrew/bin/mvn spring-boot:run

# frontend — :4200  (separate terminal)
cd frontend && npm install && npm start

# trigger a run — THE DEMO BUTTON
curl -X POST localhost:8080/api/runs \
     -H 'Content-Type: application/json' \
     -d '{"period":"2026-06-01","priorPeriod":"2026-05-01"}'
```

## Read in this order

| File | Why |
|---|---|
| `docs/FINDINGS.md` | Every verified finding, ranked. **Your demo content.** |
| `docs/ARCHITECTURE.md` | One diagram + where every package lives |
| `docs/DEMO_SCRIPT.md` | Timed 5-minute run sheet |
| `docs/DECK_OUTLINE.md` | 10 slides with the line to say on each |
| `docs/SAMPLE_IO.md` | Deliverable: sample inputs/outputs |
| `README.md` | Quickstart + requirement coverage table |

## The three demo findings (verified against real data)

1. **June broke, but only in one corner.** Campus OTA 95.31 → 92.46 → 94.69.
   Concentrated: LOGIN −5.17 vs LOGOUT −0.77 · BUS −6.25 vs CAB −2.20 ·
   MANUAL routing −6.22 vs AUTO −2.20 · 2 of 5 business units · Denver and
   Clearwater. **Not a vendor problem — a morning bus routing problem.**

2. **An alarm stopped ringing.** `EMPLOYEE_SIGN_OFF_TIME_VIOLATION`:
   7,670 (May) → 46 (Jun) → 20 (Jul) = **−99.7%**. A dashboard shows alerts that
   fired; it cannot show alerts that stopped. This is the agentic proof.

3. **Cost-per-km is a broken metric.** 42% of trips are fixed-rate contracts that
   never record distance (4S-HYD/6S-HYD 100% zero-km). Blending them produces
   ₹183,506/km artifacts. **Their existing number is meaningless for half the spend.**

## Known constraints

- **Vendor mix barely shifts** (max 0.79pts) — attribution must scan *all*
  dimensions, never assume vendor. This is handled; don't "fix" it back.
- Rating `0` may mean *unrated* rather than a genuine zero — see `docs/findings/feedback.md`
  for the decision and its impact on averages.
- Without `ANTHROPIC_API_KEY` the app runs end-to-end on deterministic fallbacks,
  but you lose triage clustering and the generated narrative.

## The two tests that carry the pitch

```bash
/opt/homebrew/bin/mvn test
```

- `MixRateDecomposerTest` — contributions sum to the observed delta within 1e-9.
  Your headline claim, as a green test.
- `SlaPolicyTest` — every breach rule, deterministic and reproducible.

---

# VERIFIED — what actually works

Everything below was run, not assumed.

## ✅ Builds and tests

```
mvn compile   BUILD SUCCESS
mvn test      106 tests · 0 failures · 0 errors · 14 skipped
```

The skipped 14 are the live-dataset metric tests (conditional on data being present).

Both load-bearing suites pass:

| Suite | Covers |
|---|---|
| `MixRateDecomposerTest` | reconciliation · entities in one period · weight handling · rate-vs-mix separation · degenerate input |
| `SlaPolicyTest` | severity bands · consecutive periods · lower_is_better inversion · robustness |

## ✅ Boots and runs on the real data

App starts in **19.5s**, ingesting all 3.4M rows.

```
POST /api/runs {"period":"2026-06","priorPeriod":"2026-05"}

615,546 trips → 1,021 series → 20 candidates → 2 incidents   in 6.6s
```

`GET /api/health` confirms the invariant: **rowsRead == rowsKept == 615,546, droppedRows 0**,
with 13 auto-generated caveats explaining every quirk in plain English.

## ✅ It found the June story

```
P1 [CRITICAL] On-Time Arrival fell -4.07 pts on office = Clearwater Campus
P2 [CRITICAL] Cost per Kilometre fell -31.53 on contract = DV_Package
```

The P1 incident clustered **19 correlated slices into one alert** and produced:

> *"Scanning all 9 decomposable dimensions, trip_direction explains the movement best.
> LOGIN (−2.43 pts: −2.41 rate, −0.02 mix). Mix effects account for only 1% of the gross
> movement, so this is a rate change, not a redistribution of volume. An explanation
> blaming a shift of volume between entities is not supported by these numbers."*

Note what that last sentence does: the engine **rejected the vendor-mix narrative** we
originally assumed, because the data doesn't support it. That is the system working.

## 🔧 Two things fixed after the first live run

1. **cost-per-km SLA was a guessed 25.0** against an observed 75–80 range — every unit sat
   in permanent CRITICAL breach and a cost *decrease* was raised as an incident.
   Recalibrated to 85.0 from the data (`tools/analysis/sla_baseline.py`).
2. **189 billing lines carry negative `trip_cost`** (largest −₹2,233,332.99) — credit notes,
   not trips. They pulled a business unit's cost/km to −21.13. Now excluded from unit cost,
   retained in total spend. **This quirk is not in the supplied data dictionary.**

## ✅ Frontend builds and serves

```
npx ng build    Application bundle generation complete — 264.56 kB (71.51 kB transferred)
npx ng serve    http://localhost:4200
curl localhost:4200/api/health   → proxy OK, 615,546 trips, 2 incidents
```

One fix was needed: Angular permits an `as` alias only on a *primary* `@if`, and the
incident view used `@else if (incident(); as inc)`. That single NG5002 cascaded into
30+ errors. Restructured to a nested primary `@if`.

## ✅ Every endpoint responds

```
200  /api/health          200  /api/incidents      200  /api/runs/latest
200  /api/metrics         200  /api/attribution    200  /api/reports/brief
```

Chat answers a supported question with per-claim `metricId` citations, and **declines**
an unsupported one:

> *"That question is outside the metric catalog, so I will not answer it — guessing here
> would produce a number the dashboard disagrees with."*

Put that in the demo. A chatbot that refuses is more convincing than one that always answers.

## ⚠️ Still outstanding

- **LLM path unverified** — no `ANTHROPIC_API_KEY` in the environment, so only the
  deterministic fallback has been exercised. Export a key and re-run to light up triage
  clustering and generated narrative. The app logs the degradation explicitly at startup.
- **`docs/FINDINGS.md`** — synthesis agent still running. The seven per-area findings
  documents are complete in `docs/findings/`.
- **No browser screenshot taken** — the UI serves and proxies correctly, but nobody has
  looked at it rendered. Open http://localhost:4200 and check the incident waterfall
  before you demo.

## Undocumented quirks we found (not in their dictionary)

| Quirk | Count | Impact |
|---|---|---|
| `'OverHead'` literal in `bill_data.trip_id` | 160 lines | plain `CAST` crashes; joins to no trip |
| Negative `trip_cost` (credit notes) | 189 lines, min −2,233,332.99 | drove a BU's cost/km negative |
| `severity = 'False'` far more common than described | 15,037 rows (29%) | dictionary implied a single stray value |
