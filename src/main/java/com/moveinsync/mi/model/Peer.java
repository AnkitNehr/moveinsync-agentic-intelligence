package com.moveinsync.mi.model;

/**
 * Cohort reference frame for a metric value.
 *
 * <p>Compares one entity against its siblings on the same dimension in the same period — a vendor
 * against the other 22 vendors, an office against the other 17 offices — so that a movement can be
 * separated into "this entity moved" versus "the whole fleet moved".
 *
 * @param cohortMedian median metric value across the entity's cohort for the period
 * @param rank         qualitative placement: BEST / ABOVE_MEDIAN / BELOW_MEDIAN / WORST
 * @param percentile   entity's percentile within the cohort, 0.0 to 100.0
 */
public record Peer(Double cohortMedian, String rank, Double percentile) {

    public static Peer none() {
        return new Peer(null, null, null);
    }
}
