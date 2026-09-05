package com.moveinsync.mi.incident;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.time.Instant;

/**
 * A standing instruction to stop surfacing a particular pattern.
 *
 * <p>Written when an operator dismisses an incident. Dismissal is not cosmetic: the suppression
 * feeds the candidate ranker, so the same metric-dimension-entity combination scores lower or drops
 * out entirely on subsequent runs. This is the feedback path that makes the system get quieter as it
 * learns what a given operator does not care about, instead of re-raising the same judgement call
 * every month.
 *
 * <p>Any of {@code metricId}, {@code dimension} or {@code entity} may be {@link #WILDCARD} to
 * suppress a whole family — for example every finding on {@code trip_nodal='SHUTTLE'} regardless of
 * metric.
 *
 * @param id              stable suppression identifier
 * @param metricId        metric to suppress, or {@link #WILDCARD}
 * @param dimension       dimension to suppress, or {@link #WILDCARD}
 * @param entity          dimension member to suppress, or {@link #WILDCARD}
 * @param reason          operator's stated rationale, retained for audit
 * @param sourceIncidentId incident whose dismissal created this suppression
 * @param createdAt       when the suppression was written
 * @param expiresAt       when it stops applying, or null for an indefinite suppression
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record Suppression(
        String id,
        String metricId,
        String dimension,
        String entity,
        String reason,
        String sourceIncidentId,
        Instant createdAt,
        Instant expiresAt) {

    /** Matches any value in the corresponding position. */
    public static final String WILDCARD = "*";

    /** Whether this suppression is still in force at the given instant. */
    public boolean activeAt(Instant now) {
        return expiresAt == null || now == null || now.isBefore(expiresAt);
    }

    /**
     * Whether this suppression covers a metric-dimension-entity triple. Comparison is
     * case-insensitive; {@link #WILDCARD} and null in the suppression match anything.
     */
    public boolean matches(String candidateMetric, String candidateDimension, String candidateEntity) {
        return fieldMatches(metricId, candidateMetric)
                && fieldMatches(dimension, candidateDimension)
                && fieldMatches(entity, candidateEntity);
    }

    private static boolean fieldMatches(String pattern, String candidate) {
        if (pattern == null || WILDCARD.equals(pattern)) {
            return true;
        }
        return pattern.equalsIgnoreCase(candidate);
    }
}
