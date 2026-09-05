package com.moveinsync.mi.model;

import java.util.List;

/**
 * Observability record for one end-to-end analysis run.
 *
 * <p>Makes the pipeline auditable and costed: how much data was read, how much of the search space
 * was actually scanned, how aggressively candidates were filtered into incidents, and what the LLM
 * stages cost in tokens and wall-clock time.
 *
 * @param runId            unique run identifier
 * @param startedAt        ISO-8601 start timestamp
 * @param trips            number of trip rows loaded across all monthly ride extracts
 * @param seriesEvaluated  metric-by-dimension-by-entity series examined by the scanner
 * @param candidates       findings that survived the significance and volume gates
 * @param incidents        incidents promoted from those candidates
 * @param promptTokens     total prompt tokens across all LLM stages
 * @param completionTokens total completion tokens across all LLM stages
 * @param estimatedCostUsd estimated LLM spend for the run in USD
 * @param wallClockMs      total run duration in milliseconds
 * @param stageTimings     per-stage timing breakdown, e.g. {@code "ingest=4210ms"}
 */
public record RunSummary(
        String runId,
        String startedAt,
        long trips,
        int seriesEvaluated,
        int candidates,
        int incidents,
        long promptTokens,
        long completionTokens,
        double estimatedCostUsd,
        long wallClockMs,
        List<String> stageTimings) {

    public RunSummary {
        stageTimings = stageTimings == null ? List.of() : List.copyOf(stageTimings);
    }
}
