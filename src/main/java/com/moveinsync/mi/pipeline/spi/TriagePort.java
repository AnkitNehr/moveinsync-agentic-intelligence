package com.moveinsync.mi.pipeline.spi;

import com.moveinsync.mi.model.Finding;
import java.util.List;

/**
 * Turns a ranked list of findings into a much shorter list of incident drafts.
 *
 * <p>The scanner emits dozens of statistically real movements, and most of them are the same story
 * told through correlated slices. In the June OTA drop, LOGIN, BUS and MANUAL all move together
 * because manually planned bus routes on the morning login leg are largely the same trips; emitting
 * three incidents would triple the operator's workload without adding a single fact. Triage is the
 * stage that collapses them.
 *
 * <p>This is the first point in the pipeline where a model may be involved. It is expressed as a
 * port so that the deterministic implementation and an LLM-backed one are interchangeable, and so
 * the pipeline can run end to end with no API key present.
 */
public interface TriagePort {

    /**
     * A proposed incident, before reasoning and narration have run.
     *
     * @param clusterKey  stable key identifying the cluster; used to derive a reproducible incident id
     * @param title       working title, refined later by the narrative stage
     * @param whyNow      one-line justification for surfacing this in the current period
     * @param priority    1 (most urgent) upward
     * @param findingIds  ids of the findings this draft consolidates, lead finding first
     * @param rationale   why these findings were grouped, retained for audit
     */
    record IncidentDraft(
            String clusterKey,
            String title,
            String whyNow,
            int priority,
            List<String> findingIds,
            String rationale) {

        public IncidentDraft {
            findingIds = findingIds == null ? List.of() : List.copyOf(findingIds);
            priority = Math.max(1, priority);
        }

        /** The lead finding id — the one whose metric and entity name the incident. */
        public String leadFindingId() {
            return findingIds.isEmpty() ? null : findingIds.getFirst();
        }
    }

    /**
     * Clusters ranked findings into incident drafts.
     *
     * @param ranked ranked findings, highest score first; may be empty
     * @param period current period label, e.g. {@code 2026-06}
     * @return drafts ordered by priority, most urgent first; never null
     */
    List<IncidentDraft> triage(List<Finding> ranked, String period);

    /** Label recorded in the audit trail, e.g. a model id or {@code deterministic}. */
    String tier();
}
