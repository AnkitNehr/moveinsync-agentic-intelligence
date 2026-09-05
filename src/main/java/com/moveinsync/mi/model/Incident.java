package com.moveinsync.mi.model;

import java.util.List;

/**
 * A governed, narrated operational issue assembled from one or more correlated findings.
 *
 * <p>Incidents are the platform's output contract. Related findings are clustered so that the June
 * OTA drop surfaces once — as a single LOGIN/BUS/MANUAL story — rather than as a dozen near-duplicate
 * alerts on correlated slices of the same movement.
 *
 * @param recommendedActions proposed remediations, each individually policy-gated
 * @param evidence           claim-to-metric bindings that make the explanation auditable
 * @param quality            aggregate data-quality envelope across the constituent findings
 * @param detectedAt         ISO-8601 timestamp the incident was raised
 * @param followUpAt         ISO-8601 timestamp the incident should be re-evaluated
 * @param status             lifecycle state, e.g. {@code OPEN} / {@code MONITORING} / {@code RESOLVED}
 */
public record Incident(
        String id,
        String title,
        String whyNow,
        int priority,
        String severity,
        List<String> findingIds,
        String explanation,
        List<Evidence> evidence,
        List<Action> recommendedActions,
        PolicyDecision policy,
        Quality quality,
        String detectedAt,
        String followUpAt,
        String status) {

    public Incident {
        findingIds = findingIds == null ? List.of() : List.copyOf(findingIds);
        evidence = evidence == null ? List.of() : List.copyOf(evidence);
        recommendedActions = recommendedActions == null ? List.of() : List.copyOf(recommendedActions);
    }
}
