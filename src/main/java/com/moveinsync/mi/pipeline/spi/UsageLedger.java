package com.moveinsync.mi.pipeline.spi;

import java.util.Map;

/**
 * Token and cost accounting for the agentic stages.
 *
 * <p>The {@link com.moveinsync.mi.model.RunSummary} promises real token counts, not estimates. That
 * only holds if there is exactly one place every LLM call reports into. This is that place: an LLM
 * client records each call here as it completes, and the pipeline snapshots the ledger before and
 * after each stage to attribute spend to the stage that incurred it.
 *
 * <p>With the model disabled the ledger stays at zero, which is the honest answer — a run that used
 * no tokens should report no tokens rather than a plausible-looking estimate.
 *
 * <p><b>Wiring an LLM client:</b> inject {@code UsageLedger} and call
 * {@link #record(String, String, long, long)} once per completed request, passing the pipeline stage
 * name and the model id. Nothing else in the platform needs to change.
 */
public interface UsageLedger {

    /**
     * Immutable accounting snapshot.
     *
     * @param promptTokens     prompt (input) tokens consumed
     * @param completionTokens completion (output) tokens produced
     * @param calls            number of model requests
     * @param estimatedCostUsd priced spend in USD, using the configured per-model rates
     */
    record Usage(long promptTokens, long completionTokens, long calls, double estimatedCostUsd) {

        public static final Usage ZERO = new Usage(0L, 0L, 0L, 0.0);

        public Usage plus(Usage other) {
            if (other == null) {
                return this;
            }
            return new Usage(
                    promptTokens + other.promptTokens,
                    completionTokens + other.completionTokens,
                    calls + other.calls,
                    estimatedCostUsd + other.estimatedCostUsd);
        }

        /**
         * Difference against an earlier snapshot, floored at zero.
         *
         * <p>This is how a stage's own consumption is isolated: snapshot before, snapshot after,
         * subtract. Flooring matters because {@link UsageLedger#reset()} can move the totals
         * backwards between the two reads, and a negative token count in an audit record is worse
         * than a zero.
         *
         * @param baseline snapshot taken before the stage ran
         * @return this snapshot minus the baseline
         */
        public Usage since(Usage baseline) {
            if (baseline == null) {
                return this;
            }
            return new Usage(
                    Math.max(0L, promptTokens - baseline.promptTokens),
                    Math.max(0L, completionTokens - baseline.completionTokens),
                    Math.max(0L, calls - baseline.calls),
                    Math.max(0.0, estimatedCostUsd - baseline.estimatedCostUsd));
        }

        public long totalTokens() {
            return promptTokens + completionTokens;
        }
    }

    /**
     * Records one completed model request.
     *
     * @param stage            pipeline stage that made the call, e.g. {@code TRIAGE}
     * @param model            model id, e.g. {@code claude-opus-5}; drives the price lookup
     * @param promptTokens     prompt tokens reported by the API
     * @param completionTokens completion tokens reported by the API
     */
    void record(String stage, String model, long promptTokens, long completionTokens);

    /** Cumulative usage across every stage since the last {@link #reset()}. */
    Usage total();

    /** Usage attributed to one stage, or {@link Usage#ZERO} when that stage made no calls. */
    Usage forStage(String stage);

    /** Per-stage breakdown, in first-call order. */
    Map<String, Usage> byStage();

    /** Clears all counters. Called at the start of a run so the summary covers that run only. */
    void reset();
}
