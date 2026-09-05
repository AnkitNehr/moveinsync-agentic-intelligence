package com.moveinsync.mi.model;

/**
 * Period-over-period reference frame for a metric value.
 *
 * <p>All fields are nullable: the first period in a series has no prior, and a series with too few
 * observations cannot produce a robust z-score.
 *
 * @param prior   metric value in the immediately preceding period
 * @param delta   current minus prior, in the metric's native unit (rates are in points)
 * @param robustZ median/MAD-based z-score of the delta; robust to the outliers this dataset carries
 *                (delay_minutes reaches 10,644, planned_km goes negative)
 */
public record Trend(Double prior, Double delta, Double robustZ) {

    public static Trend none() {
        return new Trend(null, null, null);
    }
}
