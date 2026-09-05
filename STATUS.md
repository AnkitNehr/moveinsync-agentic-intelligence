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

## If something is broken

Check the bottom of this file — the overnight run appends a
**"What works / what doesn't"** section after the compile-and-boot verification.
