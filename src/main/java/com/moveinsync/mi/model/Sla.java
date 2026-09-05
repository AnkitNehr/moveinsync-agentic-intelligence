package com.moveinsync.mi.model;

/**
 * Contractual reference frame for a metric value.
 *
 * <p>Targets come from {@code app.sla} — OTA 0.95, escort compliance 1.0, alert acknowledgement
 * within 15 minutes, cost-per-km 25.0 for distance-based contracts only. Metrics with no applicable
 * target carry a null {@code target} and are never marked breached.
 *
 * @param target   configured SLA threshold for this metric, or null when none applies
 * @param delta    signed distance from the target in the metric's native unit
 * @param breached whether the observed value violates the target
 */
public record Sla(Double target, Double delta, boolean breached) {

    public static Sla notApplicable() {
        return new Sla(null, null, false);
    }
}
