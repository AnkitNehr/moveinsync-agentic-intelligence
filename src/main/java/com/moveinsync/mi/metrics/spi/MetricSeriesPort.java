package com.moveinsync.mi.metrics.spi;

import java.util.List;
import java.util.Optional;

/**
 * What the scanner needs from the semantic layer: metric values, sliced and historical.
 *
 * <p>Implemented by the metric layer's {@code MetricQueryService}. No caller reaches the fact store
 * except through the catalog, and this port is the scanner's half of that contract — there is
 * deliberately no method here that accepts SQL or a raw predicate.
 *
 * <p>Implementations are responsible for enforcing each metric's {@code min_sample}: an
 * under-sampled slice must come back with a null {@link MetricSlice#value()} and its true
 * {@code sampleSize}, never omitted and never zero-filled. The scanner applies its own, stricter
 * gate on top of that.
 */
public interface MetricSeriesPort {

    /**
     * All entity slices for one metric on one dimension in one period.
     *
     * @param metricId  stable metric identifier
     * @param dimension dimension to slice by, e.g. {@code trip_direction}
     * @param period    period label, e.g. {@code 2026-06}
     * @return one slice per entity present in the period; empty when the dimension is unknown
     */
    List<MetricSlice> slices(String metricId, String dimension, String period);

    /**
     * The un-sliced aggregate for one metric in one period.
     *
     * <p>Kept separate from {@link #slices} because the total is not generally recoverable from the
     * parts: slices suppressed for low sample, and rows whose dimension value is null, are in the
     * total but not in any slice. That difference is precisely the coverage gap the attribution
     * engine reports rather than conceals.
     *
     * @param metricId stable metric identifier
     * @param period   period label
     * @return the aggregate slice with entity {@link MetricSpec#ALL}, or empty when unavailable
     */
    Optional<MetricSlice> overall(String metricId, String period);

    /**
     * Historical values for one series, oldest first, ending at (and including) {@code throughPeriod}.
     *
     * <p>Feeds the temporal robust z-score. Implementations should return only periods that actually
     * exist rather than padding with zeros, and may return fewer than {@code lookback} points; the
     * scanner decides whether the history is long enough to trust and falls back to a cross-sectional
     * comparison when it is not.
     *
     * @param metricId      stable metric identifier
     * @param dimension     dimension the entity belongs to, or {@link MetricSpec#GLOBAL}
     * @param entity        dimension member
     * @param throughPeriod most recent period to include
     * @param lookback      maximum number of periods to return
     * @return values oldest first; empty when no history is available
     */
    List<Double> history(String metricId, String dimension, String entity, String throughPeriod, int lookback);
}
