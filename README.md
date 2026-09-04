# MoveInSync — Agentic Intelligence & Reporting Layer for Enterprise Mobility

Hackathon submission repo. Full brief: [docs/problem-statement.md](docs/problem-statement.md).

**Goal:** an agentic layer over enterprise mobility data that *senses* what's happening,
*reasons* about what it means, and *acts* — surfacing what matters, benchmarking it against a
reference point (trend / SLA / peer), and communicating it to the right persona at the right
time. Not a passive dashboard.

## Status

| Stage | State |
| --- | --- |
| Repo + BMAD scaffold | ✅ done |
| Sample dataset | ⬜ not yet received |
| Analysis / brief | ⬜ not started |
| PRD + architecture | ⬜ not started |
| Implementation | ⬜ not started |

## Layout

```
.
├── _bmad/            BMAD v6 framework config (bmm module)
├── _bmad-output/     BMAD-generated artifacts
│   ├── planning-artifacts/        brief, PRD, UX, architecture, epics
│   └── implementation-artifacts/  sprint status, stories, reviews, retros
├── .claude/skills/   29 BMAD skills exposed to Claude Code
├── docs/             problem statement + long-term project knowledge
└── data/             sample dataset (gitignored; see data/README.md)
```

## Getting started

The dataset is not in the repo. Drop the provided anonymised trip logs into `data/raw/`
(gitignored) — see [data/README.md](data/README.md).

BMAD is already installed; no setup step is needed. Open this folder in Claude Code and the
skills under `.claude/skills/` are available.

## BMAD workflow

Planned path through the BMAD v6 (`bmm`) skills:

```
bmad-brainstorming / bmad-forge-idea      idea
        ↓
bmad-product-brief                        analysis
        ↓
bmad-prd                                  planning
        ↓
bmad-architecture                         solutioning
        ↓
bmad-create-epics-and-stories             break down
        ↓
bmad-sprint-planning → bmad-agent-dev     build
        ↓
bmad-code-review → bmad-review            verify
        ↓
bmad-qa-generate-e2e-tests                test
        ↓
bmad-retrospective                        close
```

Run `bmad-help` if you're unsure which skill applies.

## Tech stack

Undecided — the brief prefers Java / Angular / AWS but is not restrictive. To be settled in
the architecture stage.
