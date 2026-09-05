package com.moveinsync.mi.model;

/**
 * A single factual claim in an incident narrative, bound to the observation that backs it.
 *
 * <p>Every sentence the LLM writes must trace to a computed number. Carrying {@code metricId} and
 * {@code entity} alongside the claim makes the narrative auditable: a reviewer can re-derive any
 * statement from the underlying observation rather than trusting the model's prose.
 *
 * @param claim    the assertion as stated in the narrative
 * @param metricId metric that substantiates the claim
 * @param entity   dimension member the claim is about
 */
public record Evidence(String claim, String metricId, String entity) {
}
