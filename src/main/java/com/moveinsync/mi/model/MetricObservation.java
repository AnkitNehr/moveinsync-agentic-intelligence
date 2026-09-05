package com.moveinsync.mi.model;

/**
 * One metric, measured for one entity, over one period, with everything needed to judge it.
 *
 * <p>This is the atomic unit produced by the scanner. A findings pipeline that emitted only
 * {@code value} would be a chart; carrying {@link References}, {@code sampleSize}, {@code severity}
 * and {@link Quality} alongside it is what lets downstream stages rank, suppress and explain.
 *
 * @param metricId   stable metric identifier, e.g. {@code ota}, {@code noshow_rate}, {@code cost_per_km}
 * @param grain      time grain of the measurement, e.g. {@code month}
 * @param entity     dimension member being measured, e.g. {@code LOGIN}, {@code Denver}, {@code ALL}
 * @param period     period label, e.g. {@code 2026-06}
 * @param value      observed metric value; nullable when coverage was insufficient to compute one
 * @param sampleSize number of underlying rows behind the value; drives the min-sample volume gate
 * @param references trend / SLA / peer / industry comparison frames
 * @param severity   normalised 0.0-1.0 urgency blending SLA breach, trend magnitude and robust z
 * @param quality    coverage, confidence band and data-quality caveats
 */
public record MetricObservation(
        String metricId,
        String grain,
        String entity,
        String period,
        Double value,
        long sampleSize,
        References references,
        double severity,
        Quality quality) {
}
