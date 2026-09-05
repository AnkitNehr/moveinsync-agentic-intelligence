package com.moveinsync.mi.metrics.spi;

import com.moveinsync.mi.model.MetricObservation;

/**
 * What the scanner needs from the benchmark engine: a bare number turned into an interpretable one.
 *
 * <p>Implemented by {@code BenchmarkService}. The scanner never assembles a
 * {@link MetricObservation} itself, because doing so would mean deciding what an SLA target is or
 * what a peer cohort looks like in two places. It supplies the measurement; the benchmark engine
 * attaches the trend, SLA, peer and industry frames and the resulting severity.
 */
public interface ObservationPort {

    /**
     * Wraps a measured value in its four reference frames.
     *
     * <p>Every frame must be either populated or explicitly unavailable — never silently absent.
     * That is the mandatory contextualisation requirement, and it holds for every observation the
     * scanner emits, not only the ones that reach a narrative.
     *
     * @param metricId   stable metric identifier
     * @param grain      dimension the entity belongs to, e.g. {@code trip_direction}
     * @param entity     dimension member, or {@link MetricSpec#ALL} for the aggregate
     * @param period     period label
     * @param value      the measured value; nullable when coverage was insufficient
     * @param sampleSize rows behind the value
     * @param coverage   fraction of those rows carrying a usable value
     * @return a fully referenced observation; implementations must not return null
     */
    MetricObservation observe(
            String metricId,
            String grain,
            String entity,
            String period,
            Double value,
            long sampleSize,
            double coverage);
}
