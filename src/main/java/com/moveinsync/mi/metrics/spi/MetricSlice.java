package com.moveinsync.mi.metrics.spi;

/**
 * One metric value for one entity in one period, as returned by the metric layer.
 *
 * <p>{@code value} is nullable and that nullability is load-bearing. When a slice falls below its
 * metric's {@code min_sample}, or when no row in the slice carried a parseable value, the metric
 * layer returns a slice with a null value rather than a zero. Zero and "not enough data to say" are
 * different claims, and collapsing them is how a segment with 244 trips ends up reported as a
 * 26-point swing.
 *
 * @param entity     dimension member, e.g. {@code LOGIN}, {@code Denver}, or {@code ALL} for the total
 * @param value      the metric value, or null when the slice could not be measured
 * @param sampleSize rows behind the slice; the volume measure used for mix-rate weighting
 * @param coverage   fraction of those rows that carried a usable value, 0.0 to 1.0
 */
public record MetricSlice(String entity, Double value, long sampleSize, double coverage) {

    public MetricSlice {
        sampleSize = Math.max(0L, sampleSize);
        coverage = Double.isFinite(coverage) ? Math.clamp(coverage, 0.0, 1.0) : 0.0;
    }

    /** True when this slice carries a finite, usable value. */
    public boolean measured() {
        return value != null && Double.isFinite(value);
    }
}
