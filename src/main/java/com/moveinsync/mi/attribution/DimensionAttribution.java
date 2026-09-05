package com.moveinsync.mi.attribution;

import com.moveinsync.mi.model.Contribution;

import java.util.List;

/**
 * The decomposition of one aggregate movement across one dimension, with a score for how well that
 * dimension explains the movement.
 *
 * <p>Every dimension can be decomposed, and every decomposition reconciles to the same delta. That
 * makes them all arithmetically correct and most of them useless: slicing a fleet-wide decline by
 * fuel type reproduces the decline in every bucket and explains nothing. {@link #explanatoryPower()}
 * is what separates the dimension that carries the signal from the ones that merely restate the
 * total.
 *
 * @param dimension           dimension decomposed, e.g. {@code trip_direction}
 * @param actualDelta         the aggregate movement being explained, current minus prior
 * @param explainedDelta      movement accounted for by the top-3 entities of this dimension
 * @param explanatoryPower    composite 0.0-1.0 score used to rank dimensions; see {@link AttributionService}
 * @param concentration       share of gross entity movement carried by the top 3 entities, 0.0-1.0
 * @param dispersion          how differently entities moved from the aggregate, 0.0-1.0; 0 means uniform
 * @param reconciliationError absolute gap between the summed contributions and {@code actualDelta}
 * @param entityCount         entities that cleared the volume gate and entered the decomposition
 * @param sampleSize          current-period rows across those entities
 * @param contributions       per-entity rate/mix split, largest absolute contribution first
 */
public record DimensionAttribution(
        String dimension,
        double actualDelta,
        double explainedDelta,
        double explanatoryPower,
        double concentration,
        double dispersion,
        double reconciliationError,
        int entityCount,
        long sampleSize,
        List<Contribution> contributions) {

    public DimensionAttribution {
        contributions = contributions == null ? List.of() : List.copyOf(contributions);
    }

    /**
     * Whether the decomposition closes against the delta it claims to explain.
     *
     * <p>A false here is not necessarily a bug: it also fires when entities were excluded by the
     * volume gate, which is real information about coverage and belongs in the narrative.
     *
     * @param tolerance acceptable absolute error
     * @return true when the contributions sum to the aggregate movement within tolerance
     */
    public boolean reconciles(double tolerance) {
        return reconciliationError <= tolerance;
    }

    /**
     * The single largest contributor, which is what a narrative names first.
     *
     * @return the top contribution, or null when nothing cleared the volume gate
     */
    public Contribution leader() {
        return contributions.isEmpty() ? null : contributions.getFirst();
    }
}
