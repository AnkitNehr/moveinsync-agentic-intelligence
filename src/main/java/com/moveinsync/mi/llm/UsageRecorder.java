package com.moveinsync.mi.llm;

import com.moveinsync.mi.model.RunSummary;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.LongAdder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Per-run token and cost accounting for every LLM call the platform makes.
 *
 * <p>An agentic system that cannot say what it spent is not operable. This recorder is the single
 * place tokens are counted, so {@link RunSummary#promptTokens()}, {@link RunSummary#completionTokens()}
 * and {@link RunSummary#estimatedCostUsd()} are derived from the API's own usage block rather than
 * from an estimate made by the code that wrote the prompt.
 *
 * <h2>Prompt tokens are three numbers, not one</h2>
 *
 * <p>The API reports {@code input_tokens} as the <em>uncached remainder</em> only. The full prompt
 * is {@code input_tokens + cache_read_input_tokens + cache_creation_input_tokens}. Reporting just
 * {@code input_tokens} would make a well-cached run look like it barely sent a prompt, and would
 * hide the thing worth watching: whether the cached prefix is actually being hit. Cache reads are
 * therefore tracked separately and surfaced on the snapshot, so a run where
 * {@link Snapshot#cacheReadInputTokens()} is zero across many calls is visibly a caching regression.
 *
 * <h2>Thread safety</h2>
 *
 * <p>Counters are {@link LongAdder}s in a pre-populated {@link EnumMap}, so concurrent agent calls
 * accumulate without contention and without ever inserting a key. {@link #beginRun(String)} swaps in
 * a fresh set of counters atomically, so a snapshot taken mid-swap reads one consistent generation
 * rather than a half-reset mixture.
 */
@Service
public class UsageRecorder {

    private static final Logger log = LoggerFactory.getLogger(UsageRecorder.class);

    /** Run id used before {@link #beginRun(String)} is called. */
    public static final String NO_RUN = "unscoped";

    /**
     * Usage attributable to one model tier within a run.
     *
     * @param tier                model tier
     * @param calls               successful completions
     * @param failures            calls that threw or returned unusable output
     * @param inputTokens         uncached prompt tokens
     * @param outputTokens        completion tokens
     * @param cacheReadTokens     prompt tokens served from the cached prefix
     * @param cacheWriteTokens    prompt tokens written to cache
     * @param estimatedCostUsd    cache-aware estimated spend for this tier
     */
    public record TierUsage(
            ModelTier tier,
            long calls,
            long failures,
            long inputTokens,
            long outputTokens,
            long cacheReadTokens,
            long cacheWriteTokens,
            double estimatedCostUsd) {

        /** Fraction of prompt tokens served from cache, 0.0 to 1.0. Zero when nothing was sent. */
        public double cacheHitRatio() {
            long prompt = inputTokens + cacheReadTokens + cacheWriteTokens;
            return prompt == 0L ? 0.0 : (double) cacheReadTokens / prompt;
        }
    }

    /**
     * Immutable roll-up of one run's LLM spend, shaped to drop straight into a {@link RunSummary}.
     *
     * @param runId                    run this snapshot covers
     * @param calls                    successful completions across all tiers
     * @param failures                 failed or unusable calls across all tiers
     * @param promptTokens             uncached + cache-read + cache-write prompt tokens
     * @param completionTokens         completion tokens
     * @param cacheReadInputTokens     prompt tokens served from the cached prefix
     * @param cacheCreationInputTokens prompt tokens written to cache
     * @param estimatedCostUsd         cache-aware estimated spend
     * @param byTier                   per-tier breakdown, in {@link ModelTier} declaration order
     */
    public record Snapshot(
            String runId,
            long calls,
            long failures,
            long promptTokens,
            long completionTokens,
            long cacheReadInputTokens,
            long cacheCreationInputTokens,
            double estimatedCostUsd,
            List<TierUsage> byTier) {

        public Snapshot {
            byTier = byTier == null ? List.of() : List.copyOf(byTier);
        }

        /** Fraction of prompt tokens served from cache across the whole run. */
        public double cacheHitRatio() {
            return promptTokens == 0L ? 0.0 : (double) cacheReadInputTokens / promptTokens;
        }

        /** One-line form for logs, e.g. {@code "6 calls, 48210 prompt / 3120 completion, $0.2416, cache 82%"}. */
        public String summary() {
            return String.format(
                    Locale.ROOT,
                    "%d calls (%d failed), %d prompt / %d completion tokens, $%.4f, cache hit %.0f%%",
                    calls, failures, promptTokens, completionTokens, estimatedCostUsd, cacheHitRatio() * 100.0);
        }
    }

    /** One generation of counters. Replaced wholesale by {@link #beginRun(String)}. */
    private static final class Counters {
        private final String runId;
        private final Map<ModelTier, LongAdder> calls = newAdderMap();
        private final Map<ModelTier, LongAdder> failures = newAdderMap();
        private final Map<ModelTier, LongAdder> input = newAdderMap();
        private final Map<ModelTier, LongAdder> output = newAdderMap();
        private final Map<ModelTier, LongAdder> cacheRead = newAdderMap();
        private final Map<ModelTier, LongAdder> cacheWrite = newAdderMap();

        Counters(String runId) {
            this.runId = runId;
        }

        private static Map<ModelTier, LongAdder> newAdderMap() {
            Map<ModelTier, LongAdder> map = new EnumMap<>(ModelTier.class);
            for (ModelTier tier : ModelTier.values()) {
                map.put(tier, new LongAdder());
            }
            return map;
        }
    }

    private final AtomicReference<Counters> counters = new AtomicReference<>(new Counters(NO_RUN));

    /**
     * Starts a new accounting generation. Everything recorded after this call is attributed to
     * {@code runId}; everything before it is discarded.
     *
     * @param runId run identifier, or null to reset to {@link #NO_RUN}
     */
    public void beginRun(String runId) {
        counters.set(new Counters(runId == null || runId.isBlank() ? NO_RUN : runId));
    }

    /** Run id the current counters are attributed to. */
    public String runId() {
        return counters.get().runId;
    }

    /**
     * Records one successful completion.
     *
     * <p>All four token counts come straight from the API's usage block. Callers pass zero for cache
     * fields the response did not report — the SDK returns them as {@code Optional}, and an absent
     * value means "none", not "unknown".
     *
     * @param tier                tier the call was made on
     * @param inputTokens         {@code usage.input_tokens} — the uncached remainder
     * @param outputTokens        {@code usage.output_tokens}
     * @param cacheReadTokens     {@code usage.cache_read_input_tokens}
     * @param cacheCreationTokens {@code usage.cache_creation_input_tokens}
     */
    public void record(
            ModelTier tier, long inputTokens, long outputTokens, long cacheReadTokens, long cacheCreationTokens) {
        ModelTier resolved = tier == null ? ModelTier.MID : tier;
        Counters current = counters.get();
        current.calls.get(resolved).increment();
        current.input.get(resolved).add(Math.max(0L, inputTokens));
        current.output.get(resolved).add(Math.max(0L, outputTokens));
        current.cacheRead.get(resolved).add(Math.max(0L, cacheReadTokens));
        current.cacheWrite.get(resolved).add(Math.max(0L, cacheCreationTokens));

        if (log.isDebugEnabled()) {
            log.debug("LLM usage {} in={} out={} cacheRead={} cacheWrite={} cost=${}",
                    resolved.modelId(), inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens,
                    String.format(Locale.ROOT, "%.5f",
                            resolved.costUsd(inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens)));
        }
    }

    /**
     * Records a call that threw or returned unusable output.
     *
     * <p>Counted separately from successes because a run that fell back to deterministic templates
     * six times is a different operational story from a run that never called the model at all, and
     * the run summary must be able to tell them apart.
     */
    public void recordFailure(ModelTier tier) {
        counters.get().failures.get(tier == null ? ModelTier.MID : tier).increment();
    }

    /** Immutable roll-up of everything recorded for the current run. */
    public Snapshot snapshot() {
        Counters current = counters.get();
        List<TierUsage> tiers = new ArrayList<>(ModelTier.values().length);

        long totalCalls = 0L;
        long totalFailures = 0L;
        long totalPrompt = 0L;
        long totalCompletion = 0L;
        long totalCacheRead = 0L;
        long totalCacheWrite = 0L;
        double totalCost = 0.0;

        for (ModelTier tier : ModelTier.values()) {
            long calls = current.calls.get(tier).sum();
            long failures = current.failures.get(tier).sum();
            long input = current.input.get(tier).sum();
            long output = current.output.get(tier).sum();
            long cacheRead = current.cacheRead.get(tier).sum();
            long cacheWrite = current.cacheWrite.get(tier).sum();
            double cost = tier.costUsd(input, output, cacheRead, cacheWrite);

            tiers.add(new TierUsage(tier, calls, failures, input, output, cacheRead, cacheWrite, cost));

            totalCalls += calls;
            totalFailures += failures;
            totalPrompt += input + cacheRead + cacheWrite;
            totalCompletion += output;
            totalCacheRead += cacheRead;
            totalCacheWrite += cacheWrite;
            totalCost += cost;
        }

        return new Snapshot(
                current.runId, totalCalls, totalFailures, totalPrompt, totalCompletion,
                totalCacheRead, totalCacheWrite, totalCost, tiers);
    }

    /** Total estimated spend for the current run, USD. */
    public double estimatedCostUsd() {
        return snapshot().estimatedCostUsd();
    }

    /** Total prompt tokens (uncached + cache read + cache write) for the current run. */
    public long promptTokens() {
        return snapshot().promptTokens();
    }

    /** Total completion tokens for the current run. */
    public long completionTokens() {
        return snapshot().completionTokens();
    }

    /** Prompt tokens served from the cached prefix during the current run. */
    public long cacheReadInputTokens() {
        return snapshot().cacheReadInputTokens();
    }

    /**
     * Returns a copy of {@code base} with the token and cost fields filled from the current run.
     *
     * <p>Lets the orchestrator build a {@link RunSummary} from the deterministic stages it owns —
     * trips, series, candidates, incidents, timings — and hand it here to have the LLM columns
     * populated, instead of threading token counters through every stage.
     *
     * @param base partially populated summary; null yields an all-zero summary with LLM fields set
     * @return a new {@link RunSummary}; never null
     */
    public RunSummary fill(RunSummary base) {
        Snapshot snap = snapshot();
        if (base == null) {
            return new RunSummary(
                    snap.runId(), null, 0L, 0, 0, 0,
                    snap.promptTokens(), snap.completionTokens(), snap.estimatedCostUsd(), 0L, List.of());
        }
        return new RunSummary(
                base.runId(),
                base.startedAt(),
                base.trips(),
                base.seriesEvaluated(),
                base.candidates(),
                base.incidents(),
                snap.promptTokens(),
                snap.completionTokens(),
                snap.estimatedCostUsd(),
                base.wallClockMs(),
                base.stageTimings());
    }
}
