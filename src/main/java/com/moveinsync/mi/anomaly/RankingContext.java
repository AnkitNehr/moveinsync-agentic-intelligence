package com.moveinsync.mi.anomaly;

import com.moveinsync.mi.model.Finding;

import java.util.Map;

/**
 * What the ranker knows that the scanner does not: history and operator feedback.
 *
 * <p>Both maps are keyed by {@link #key(Finding)}, a metric/dimension/entity triple deliberately
 * excluding the period so that state persists as periods roll forward. Kept as an explicit parameter
 * rather than injected so the ranker stays pure and testable, and so the agent-memory store can
 * supply it without the ranker depending on persistence.
 *
 * @param suppression        0.0 to 1.0 per series; 1.0 removes a finding entirely. Fed by console
 *                           dismissals and by incidents already open, so the platform gets quieter
 *                           as the operator teaches it rather than repeating itself every run.
 * @param consecutivePeriods how many consecutive periods each series has been moving adversely.
 *                           Absent entries fall back to a value derived from the SLA reference.
 */
public record RankingContext(
        Map<String, Double> suppression,
        Map<String, Integer> consecutivePeriods) {

    public RankingContext {
        suppression = suppression == null ? Map.of() : Map.copyOf(suppression);
        consecutivePeriods = consecutivePeriods == null ? Map.of() : Map.copyOf(consecutivePeriods);
    }

    /** No suppressions and no history: the state of a first run against a fresh dataset. */
    public static RankingContext empty() {
        return new RankingContext(Map.of(), Map.of());
    }

    /**
     * Suppression key for a finding. Period is excluded on purpose — dismissing "OTA on LOGIN" should
     * keep it dismissed next month, not just for the month it was raised in.
     */
    public static String key(Finding finding) {
        return finding.metricId() + "|" + finding.dimension() + "|" + finding.entity();
    }

    /** Suppression weight for a finding, 0.0 when never suppressed. */
    public double suppressionFor(Finding finding) {
        Double value = suppression.get(key(finding));
        return value == null || !Double.isFinite(value) ? 0.0 : Math.clamp(value, 0.0, 1.0);
    }

    /**
     * Consecutive adverse periods for a finding, or {@code null} when memory holds no record and the
     * ranker should derive a value instead.
     */
    public Integer consecutiveFor(Finding finding) {
        return consecutivePeriods.get(key(finding));
    }
}
