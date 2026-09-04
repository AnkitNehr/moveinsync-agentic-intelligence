# Data

The provided anonymised sample dataset is **not committed** — `data/raw/` and `data/processed/`
are gitignored, as are loose `*.csv` / `*.parquet` files.

## Expected layout

```
data/
├── raw/         drop the provided dataset here, unmodified
├── processed/   derived/cleaned outputs (regenerable)
└── samples/     small committed excerpts for docs & tests (opt-in via .gitignore)
```

## What the brief says to expect

Anonymised trip logs across **cab**, **nodal**, and **shuttle** modes, including:

- vendor performance
- GPS traces
- delay records
- cost data
- employee feedback

Expect it to be messy: GPS gaps, unmatched records, incomplete rosters. Handling that
gracefully is an explicit good-to-have in the evaluation.

## Committing excerpts

If you need a small sample in the repo for tests or docs, put it in `data/samples/` — that
path is explicitly un-ignored. Keep it small and verify it carries no re-identifiable fields.
