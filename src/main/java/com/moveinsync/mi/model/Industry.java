package com.moveinsync.mi.model;

/**
 * External benchmark reference frame for a metric value.
 *
 * <p>Populated from {@code app.industry} (OTA 0.93, no-show 0.06). Only a handful of metrics have a
 * defensible external benchmark; the rest carry nulls rather than an invented number.
 *
 * @param benchmark published industry value for the metric, or null when none exists
 * @param source    provenance label for the benchmark so the narrative can cite it honestly
 */
public record Industry(Double benchmark, String source) {

    public static Industry none() {
        return new Industry(null, null);
    }
}
