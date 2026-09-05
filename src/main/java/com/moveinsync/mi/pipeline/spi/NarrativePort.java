package com.moveinsync.mi.pipeline.spi;

import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import java.util.List;

/**
 * Renders a governed incident, or a period digest, for a specific reader.
 *
 * <p>Persona is a parameter, not a fork in the code. A transport manager wants the vendor and the
 * lever; a facilities head wants the office and the cost; a line manager wants the trips their own
 * people were on. Same numbers, three framings — so the persona is passed in and the underlying
 * facts stay identical, which is also what makes the renderings comparable in an audit.
 */
public interface NarrativePort {

    /** Reader profiles the platform renders for. Anything else falls back to {@link #TRANSPORT_MANAGER}. */
    String TRANSPORT_MANAGER = "transport_manager";
    String FACILITIES_HEAD = "facilities_head";
    String LINE_MANAGER = "line_manager";
    String EXECUTIVE = "executive";

    /** The personas the platform knows how to render, in presentation order. */
    List<String> PERSONAS = List.of(TRANSPORT_MANAGER, FACILITIES_HEAD, LINE_MANAGER, EXECUTIVE);

    /**
     * A rendered incident.
     *
     * @param title   headline naming the metric, the movement and the entity
     * @param whyNow  why this warrants attention in this period rather than generally
     * @param body    the narrative itself, Markdown
     */
    record Narrative(String title, String whyNow, String body) {
    }

    /**
     * Renders one incident for one reader.
     *
     * @param incident the governed incident, with policy and actions already decided
     * @param findings the findings behind it, lead finding first
     * @param persona  one of {@link #PERSONAS}; unknown values fall back to transport manager
     * @return the rendering; implementations must not return null
     */
    Narrative narrate(Incident incident, List<Finding> findings, String persona);

    /**
     * Renders a period digest across every open incident.
     *
     * @param period    period label, e.g. {@code 2026-06}
     * @param persona   one of {@link #PERSONAS}
     * @param incidents incidents to summarise, most urgent first; may be empty
     * @param headline  pre-computed headline metrics rendered as {@code label -> formatted value}
     * @return Markdown brief; never null
     */
    String brief(String period, String persona, List<Incident> incidents, List<String> headline);

    /** Label recorded in the audit trail, e.g. a model id or {@code deterministic}. */
    String tier();
}
