package com.moveinsync.mi.pipeline.spi;

import com.moveinsync.mi.model.Evidence;
import java.util.List;

/**
 * Maps a natural-language question onto a call into the metric layer.
 *
 * <p>The model's job here is <em>routing</em>, not answering. It resolves "how did on-time arrival do
 * for Denver in June" into {@code observe(ota, office, Denver, 2026-06)} and nothing more; the number
 * that comes back is computed by SQL against the catalog definition, exactly as it would be for the
 * dashboard. That separation is the whole point — a chat endpoint that let the model produce figures
 * would be a fluent way to be confidently wrong, and it would disagree with the dashboard.
 *
 * <p>Because routing is a small, well-bounded task it runs on the cheap tier. Two rules make the
 * cheap tier safe here: the model may only choose from the catalog, and when it cannot map a
 * question it must say so. {@link Answer#declined()} exists so that "outside the metric catalog" is
 * a first-class outcome rather than a guess dressed up as an answer.
 */
public interface ChatPort {

    /** Declining is the correct response to an unmappable question — never a fallback guess. */
    String DECLINE_REASON = "outside the metric catalog";

    /**
     * The metric-layer call a question resolved to.
     *
     * @param tool      metric-layer operation invoked, e.g. {@code observe} or {@code attribute}
     * @param metricId  metric identifier from the catalog
     * @param dimension dimension sliced on, or {@code global}
     * @param entity    dimension member, or {@code ALL}
     * @param period    period label, e.g. {@code 2026-06}
     */
    record ResolvedCall(String tool, String metricId, String dimension, String entity, String period) {
    }

    /**
     * A chat answer, its provenance, and what it cost.
     *
     * @param answer      the reply; when declined, an explanation of why the question cannot be served
     * @param resolvedCall the metric-layer call that produced the figures, or null when declined
     * @param citations   claim-to-metric bindings for every figure quoted in {@code answer}
     * @param usage       tokens and cost attributable to this question
     * @param declined    true when the question could not be mapped onto the catalog
     */
    record Answer(
            String answer,
            ResolvedCall resolvedCall,
            List<Evidence> citations,
            UsageLedger.Usage usage,
            boolean declined) {

        public Answer {
            citations = citations == null ? List.of() : List.copyOf(citations);
            usage = usage == null ? UsageLedger.Usage.ZERO : usage;
        }

        /** Builds the standard refusal, naming the catalog so the user can rephrase usefully. */
        public static Answer decline(String question, List<String> knownMetrics) {
            String metrics = knownMetrics == null || knownMetrics.isEmpty()
                    ? "none loaded"
                    : String.join(", ", knownMetrics);
            return new Answer(
                    "That question is " + DECLINE_REASON + ", so I will not answer it — guessing here "
                            + "would produce a number the dashboard disagrees with. I can answer questions "
                            + "about these metrics: " + metrics + ". Try naming one of them, plus an "
                            + "optional dimension (office, vendor, product type, trip direction, shift, "
                            + "route source) and a month such as 2026-06.",
                    null,
                    List.of(),
                    UsageLedger.Usage.ZERO,
                    true);
        }
    }

    /**
     * Answers one question.
     *
     * @param question      the user's question, verbatim
     * @param defaultPeriod period to assume when the question names none; may be null
     * @return the answer, possibly a decline; implementations must not return null
     */
    Answer ask(String question, String defaultPeriod);

    /** Label recorded in the audit trail, e.g. a model id or {@code deterministic}. */
    String tier();
}
