package com.moveinsync.mi.model;

import java.util.List;

/**
 * Live snapshot of one analysis run, polled while {@code POST /api/runs} is still blocked.
 *
 * <p>The demo button stays synchronous on purpose. This record is the cheap side channel so a
 * second request can see which funnel stage is executing and which counts have already landed,
 * without waiting for the receipt.
 *
 * @param running          whether the pipeline lock is held
 * @param runId            id of the in-flight or last completed run, or null when nothing has started
 * @param startedAt        ISO-8601 start of that run, or null
 * @param currentStage     stage inside {@link #FUNNEL} that is executing now, or null when idle
 * @param completed        stages that have finished at least once this run, in funnel order
 * @param trips            trip rows counted after ingest, or null before that
 * @param seriesEvaluated  metric series examined after scan, or null before that
 * @param findings         raw scanner hits after scan, or null before that
 * @param candidates       findings that survived ranking, or null before that
 * @param incidents        incidents persisted so far, or null before the first persist
 */
public record RunProgress(
        boolean running,
        String runId,
        String startedAt,
        String currentStage,
        List<StageTiming> completed,
        Long trips,
        Integer seriesEvaluated,
        Integer findings,
        Integer candidates,
        Integer incidents) {

    /**
     * Stages the console draws as the sense → reason → act funnel. {@code audit} is timed on the
     * ledger but omitted here: it is bookkeeping, not a narrowing step a judge needs to watch.
     */
    public static final List<String> FUNNEL = List.of(
            "ingest",
            "scan",
            "rank",
            "policy",
            "triage",
            "reason",
            "narrate",
            "actionGuard",
            "persist");

    public RunProgress {
        completed = completed == null ? List.of() : List.copyOf(completed);
    }

    public static RunProgress idle() {
        return new RunProgress(false, null, null, null, List.of(), null, null, null, null, null);
    }

    /**
     * Wall clock and tokens for one funnel stage. Repeated timings of the same name (ingest quality
     * then trip count, reason per incident) are summed into one row.
     *
     * @param stage            catalog stage id
     * @param millis           accumulated wall clock
     * @param promptTokens     prompt tokens attributed to this stage
     * @param completionTokens completion tokens attributed to this stage
     */
    public record StageTiming(String stage, long millis, long promptTokens, long completionTokens) {
    }
}
