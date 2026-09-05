package com.moveinsync.mi.attribution;

import java.util.List;
import java.util.Optional;

/**
 * Outcome of scanning every available dimension for the one that best explains a movement.
 *
 * <p>The ranked list is retained in full, not just the winner. A reviewer challenging the conclusion
 * needs to see that the dimensions the system rejected were actually examined — "vendor mix does not
 * explain this" is a finding, and it is only credible if the vendor decomposition is on the record.
 *
 * @param metricId    metric whose movement was decomposed
 * @param period      current period label
 * @param priorPeriod comparison period label
 * @param actualDelta aggregate movement, current minus prior
 * @param ranked      every dimension decomposed, best explanation first
 */
public record AttributionResult(
        String metricId,
        String period,
        String priorPeriod,
        double actualDelta,
        List<DimensionAttribution> ranked) {

    public AttributionResult {
        ranked = ranked == null ? List.of() : List.copyOf(ranked);
    }

    /**
     * The dimension that best explains the movement.
     *
     * @return the top-ranked decomposition, or empty when no dimension cleared the volume gate
     */
    public Optional<DimensionAttribution> winner() {
        return ranked.isEmpty() ? Optional.empty() : Optional.of(ranked.getFirst());
    }

    /**
     * Looks up the decomposition for a specific dimension.
     *
     * <p>Lets the scanner attach a finding's own dimension decomposition rather than the global
     * winner's, so a finding about LOGIN carries the trip_direction split it was derived from.
     *
     * @param dimension dimension name
     * @return that dimension's decomposition, or empty when it was not scanned
     */
    public Optional<DimensionAttribution> forDimension(String dimension) {
        return ranked.stream().filter(d -> d.dimension().equals(dimension)).findFirst();
    }

    /** An empty result, used when the metric has no measurable aggregate in either period. */
    public static AttributionResult empty(String metricId, String period, String priorPeriod) {
        return new AttributionResult(metricId, period, priorPeriod, 0.0, List.of());
    }
}
