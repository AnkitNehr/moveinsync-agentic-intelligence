package com.moveinsync.mi.pipeline.spi;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import java.util.List;

/**
 * Explains <em>why</em> a cluster of findings moved, with every claim bound to a computed number.
 *
 * <p>The reasoning stage never sees a trip row. It sees findings, their shift-share decompositions
 * and the ranked list of dimensions that were considered and rejected — a few kilobytes of already
 * computed JSON. That constraint is what makes the output auditable: each sentence it produces comes
 * back paired with the {@code metricId} and {@code entity} it was derived from, so a reviewer can
 * re-derive any claim rather than trusting it.
 */
public interface ReasoningPort {

    /**
     * An explanation and the evidence that substantiates it.
     *
     * @param explanation prose explanation of the movement and its most likely driver
     * @param evidence    claim-to-metric bindings, one per factual assertion in the explanation
     * @param hypothesis  short causal hypothesis, or null when the evidence supports none
     */
    record Explanation(String explanation, List<Evidence> evidence, String hypothesis) {

        public Explanation {
            evidence = evidence == null ? List.of() : List.copyOf(evidence);
        }
    }

    /**
     * Explains one cluster.
     *
     * @param draft       the incident draft under explanation
     * @param findings    the findings the draft consolidates, lead finding first
     * @param attribution decomposition of the lead metric across every dimension, winner first;
     *                    may be an empty result when the metric was unmeasurable
     * @return the explanation; implementations must not return null
     */
    Explanation explain(TriagePort.IncidentDraft draft, List<Finding> findings, AttributionResult attribution);

    /** Label recorded in the audit trail, e.g. a model id or {@code deterministic}. */
    String tier();
}
