package com.moveinsync.mi.incident;

import com.moveinsync.mi.model.MetricObservation;
import java.util.Optional;

/**
 * The one thing the follow-up loop needs from the metrics layer: re-measure a metric, now.
 *
 * <p>Deliberately narrow. {@link FollowUpScheduler} does not need the query builder, the SQL
 * compiler or the reference-frame machinery — it needs a single number for a single
 * metric/dimension/entity so it can answer "did this recover?". Depending on a one-method port
 * rather than on the full metric service keeps the governance loop unit-testable with a lambda and
 * stops a change in the metrics layer from rippling into incident policy.
 *
 * <p>The metrics slice satisfies this by having its metric query service implement the interface, or
 * by registering a thin adapter bean that delegates to it. Until such a bean exists the scheduler
 * degrades gracefully: it logs that re-checks are unavailable and leaves follow-ups pending rather
 * than guessing at recovery.
 */
@FunctionalInterface
public interface MetricRecheckPort {

    /**
     * Re-measures a metric for one entity in one period.
     *
     * @param metricId  metric to measure
     * @param dimension dimension the entity belongs to; null for a global measurement
     * @param entity    dimension member, or {@code ALL} / null for the aggregate
     * @param period    period label to measure, e.g. {@code 2026-07}; null means the latest period
     * @return the observation, or empty when the metric cannot be computed — for instance when the
     *         segment falls below the min-sample volume gate, which must never be read as recovery
     */
    Optional<MetricObservation> recheck(String metricId, String dimension, String entity, String period);
}
