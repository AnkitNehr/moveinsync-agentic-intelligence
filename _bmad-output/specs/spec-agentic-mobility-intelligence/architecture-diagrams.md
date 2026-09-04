# Architecture Diagrams

Companion to [SPEC.md](SPEC.md). Diagrams only; the decisions they depict live in the kernel, `agents.md`, and `stack.md`.

## System overview

Read this as a funnel: millions of rows enter the deterministic core, a few dozen scored candidates leave it, and the LLM sees only those. That narrowing is the cost model (CAP-13) and the reason the constraint "LLM calls receive only ranked or aggregated payloads" is enforceable.

```mermaid
flowchart TB
    subgraph SRC["Sources (sample dataset)"]
        A1["Trip logs<br/>cab / nodal / shuttle"]
        A2["GPS traces"]
        A3["Vendor + cost data"]
        A4["Employee feedback"]
        A5["Roster / shift plan"]
    end

    subgraph DET["Deterministic core — no LLM"]
        B["Ingest &amp; Normalise<br/>CAP-1"]
        C["Fact store<br/>trip_fact + dimensions"]
        D["Metric layer<br/>CAP-2"]
        E["Benchmark engine<br/>CAP-3"]
        F["Anomaly detection<br/>CAP-4"]
        G["Attribution engine<br/>CAP-5"]
        H["Candidate ranker<br/>CAP-4"]
    end

    subgraph AGT["Agentic layer — LLM"]
        I["Triage agent<br/>CAP-6"]
        J["Reasoning agent<br/>CAP-7"]
        K["Action agent<br/>CAP-11"]
        L["Narrative agent<br/>CAP-8"]
        M["Conversational agent<br/>CAP-10"]
    end

    subgraph OUT["Delivery"]
        N["Ops console<br/>CAP-12"]
        O["Email / Slack / Teams"]
        P["Leadership brief"]
        Q["Vendor escalation record"]
    end

    R[("Agent memory<br/>incidents, suppressions,<br/>follow-ups, feedback")]

    A1 & A2 & A3 & A4 & A5 --> B --> C --> D
    D --> E --> F --> G --> H
    H --> I --> J --> K
    J --> L
    K --> O & Q
    L --> N & P & O
    M --> D
    N --> M
    K <--> R
    I <--> R
    R -.suppression + follow-up.-> H
```

## Proactive cycle

The scheduled sense → reason → act loop (CAP-9). The follow-up check at the end is what makes this a loop rather than a one-shot, and is the concrete form of the brief's "acts with minimal human prompting".

```mermaid
sequenceDiagram
    autonumber
    participant S as Scheduler
    participant C as Deterministic core
    participant T as Triage agent
    participant R as Reasoning agent
    participant A as Action agent
    participant M as Memory
    participant U as Persona

    S->>C: nightly / hourly run
    C->>C: metrics, benchmarks, anomalies, attribution
    C->>T: top N scored candidates (compact JSON)
    T->>M: check suppressions + open incidents
    M-->>T: "V3 escalated 2d ago, follow-up due"
    T->>T: cluster, dedupe, decide what warrants attention
    T-->>R: promoted incidents only
    loop per incident
        R->>C: tool call - slice by route / shift / driver
        C-->>R: MetricObservations
        R->>R: form hypothesis, cite evidence
        R-->>A: cause + recommended action
    end
    A->>M: open incident, schedule follow-up check
    A->>U: persona-shaped notification
    Note over M,C: follow-up fires in 3d:<br/>did OTA recover? escalate if not
```

## Numeric integrity guard

How the "LLM never computes a number" constraint is actually enforced rather than merely intended (CAP-7).

```mermaid
flowchart LR
    O["MetricObservations<br/>(each with metric_id)"] --> P["Prompt assembly<br/>numbers only, no raw rows"]
    P --> LLM["LLM<br/>narrative + explanation"]
    LLM --> V{"Numeric validator<br/>every figure present<br/>in supplied inputs?"}
    V -->|yes| OUT["Emit"]
    V -->|no| REJ["Reject + retry<br/>with offending figure named"]
    REJ --> P
```
