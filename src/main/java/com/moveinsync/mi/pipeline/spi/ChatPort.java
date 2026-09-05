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

        /**
         * Builds the standard refusal, naming the catalog so the user can rephrase usefully.
         *
         * <p>Callers pass display labels, not metric ids. A refusal is the one reply guaranteed to be
         * read closely — the reader is trying to work out what they did wrong — so it is the worst
         * possible place to print {@code noshow_rate, delay_p90, driver_noncompliance}. Listing
         * column names tells a transport manager that the system is not really talking to them, and
         * it does not even solve their problem, because typing the id back is not how they phrase
         * questions in the first place.
         *
         * <p>The wording leads with what is available rather than with the refusal. Both sentences
         * are honest, but "here is what I can tell you" leaves the user with a next move, where
         * "that is outside the catalog" leaves them at a dead end. The decline still says plainly
         * that it will not guess, because that restraint is the point.
         */
        public static Answer decline(String question, List<String> knownMetrics) {
            String metrics = knownMetrics == null || knownMetrics.isEmpty()
                    ? "none loaded"
                    : String.join(", ", knownMetrics);
            return new Answer(
                    "I can answer questions about " + metrics + " — for the fleet as a whole, or "
                            + "broken down by office, vendor, business unit, contract, shift, vehicle "
                            + "type or the morning/evening split, for any month in the data such as "
                            + "June 2026. You can also ask why something moved, and I will break the "
                            + "change down for you.\n\n"
                            + "This particular question is " + DECLINE_REASON + ", so I have not "
                            + "answered it. I could produce a confident-sounding number, but it would "
                            + "be one the dashboard disagrees with, and a wrong figure in an "
                            + "operations review is worse than no figure at all.",
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
