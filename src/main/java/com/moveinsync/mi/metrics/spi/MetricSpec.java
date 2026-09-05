package com.moveinsync.mi.metrics.spi;

import java.util.List;

/**
 * The scanner's view of one metric catalog entry.
 *
 * <p>Deliberately narrow: the scanner needs to know what to scan, across which dimensions, which
 * direction is bad, and when a slice is too small to trust. Everything else about a metric — its SQL
 * compilation, its formula, its versioning — is the metric layer's concern and is intentionally not
 * visible here.
 *
 * @param id        stable metric identifier, e.g. {@code ota}
 * @param label     human-readable name for narrative use, e.g. {@code On-Time Arrival}
 * @param grains    dimensions this metric may be sliced by; {@link #GLOBAL} means the un-sliced total
 * @param direction {@link #HIGHER_IS_BETTER} or {@link #LOWER_IS_BETTER}; decides which sign is adverse
 * @param slaKey    config key of the governing SLA target, or null when no target applies
 * @param minSample smallest slice this metric may be reported on; the volume gate
 * @param rateMetric whether the value is a rate/proportion, so deltas are expressed in points
 * @param version   catalog version, carried through so a narrative can cite the definition it used
 */
public record MetricSpec(
        String id,
        String label,
        List<String> grains,
        String direction,
        String slaKey,
        long minSample,
        boolean rateMetric,
        int version) {

    /** Pseudo-dimension for the un-sliced aggregate. Resolved via {@link MetricSeriesPort#overall}. */
    public static final String GLOBAL = "global";

    /** Entity label used for the un-sliced aggregate, matching the MetricObservation contract. */
    public static final String ALL = "ALL";

    public static final String HIGHER_IS_BETTER = "higher_is_better";
    public static final String LOWER_IS_BETTER = "lower_is_better";

    public MetricSpec {
        grains = grains == null ? List.of() : List.copyOf(grains);
        direction = direction == null ? HIGHER_IS_BETTER : direction;
        minSample = Math.max(0L, minSample);
    }

    /**
     * Whether a movement of this sign is bad news for this metric.
     *
     * <p>OTA falling and no-show rate rising are both adverse; the sign alone does not say so, which
     * is why direction is part of the catalog rather than inferred.
     *
     * @param delta signed period-over-period movement
     * @return true when the movement is in the undesirable direction
     */
    public boolean isAdverse(double delta) {
        return HIGHER_IS_BETTER.equals(direction) ? delta < 0 : delta > 0;
    }
}
