package com.moveinsync.mi.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.moveinsync.mi.agent.guard.NumericValidator;
import com.moveinsync.mi.llm.CachedPrefixBuilder;
import com.moveinsync.mi.llm.ClaudeClient;
import com.moveinsync.mi.llm.ModelClient;
import com.moveinsync.mi.llm.ModelTier;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.fallback.BuiltInNarrator;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Service;

/**
 * Narrative — turning a validated incident into something a specific person will read.
 *
 * <p>Persona is a parameter, not a separate agent. The same incident renders for the transport
 * manager (act on it today), the facilities head (a document forwardable to leadership without
 * rework), the line manager (shift readiness) and an executive summary. One pipeline, four voices.
 *
 * <p>Like the reasoning agent, output is checked by {@link NumericValidator} against the findings
 * the incident was built from. Prose destined for a director is exactly where an invented figure
 * would do the most damage, so the guard is strictest here: fail twice and the deterministic
 * template ships instead. A blander sentence is always preferable to a wrong number.
 */
@Service
@Order(0)
public class LlmNarrativeAgent implements NarrativePort {

    private static final Logger log = LoggerFactory.getLogger(LlmNarrativeAgent.class);

    private static final ModelTier TIER = ModelTier.STRONG;
    private static final int MAX_TOKENS_NARRATIVE = 3000;
    private static final int MAX_TOKENS_BRIEF = 5000;

    private final ModelClient claude;
    private final CachedPrefixBuilder prefix;
    private final NumericValidator validator;
    private final BuiltInNarrator fallback;
    private final ObjectMapper json = new ObjectMapper();

    public LlmNarrativeAgent(
            ModelClient claude,
            CachedPrefixBuilder prefix,
            NumericValidator validator,
            MetricFormat format) {
        this.claude = claude;
        this.prefix = prefix;
        this.validator = validator;
        // BuiltInNarrator is not a Spring bean — PortRegistry constructs it inline — so this agent
        // owns its own instance rather than asking the container for one that does not exist.
        this.fallback = new BuiltInNarrator(format);
    }

    @Override
    public String tier() {
        return claude.isAvailable() ? TIER.modelId() : fallback.tier();
    }

    // ---- per-incident narrative ------------------------------------------------------------------

    @Override
    public Narrative narrate(Incident incident, List<Finding> findings, String persona) {
        if (!claude.isAvailable() || incident == null) {
            return fallback.narrate(incident, findings, persona);
        }
        try {
            String canonical = prefix.canonicalPersona(persona);
            String request = narrateRequest(incident, findings, canonical);
            String raw = claude.complete(TIER, prefix.prefix(), request, MAX_TOKENS_NARRATIVE);

            JsonNode node = readJson(raw);
            if (node == null) {
                return fallback.narrate(incident, findings, persona);
            }
            String title = node.path("title").asText(incident.title());
            String whyNow = node.path("why_now").asText(incident.whyNow());
            String body = node.path("body").asText("").trim();
            if (body.isEmpty()) {
                return fallback.narrate(incident, findings, persona);
            }

            if (findings != null && !findings.isEmpty()) {
                var check = validator.validateAgainstFindings(title + "\n" + whyNow + "\n" + body, findings);
                if (!check.ok()) {
                    log.warn("Narrative for persona '{}' contained unsupported numbers {}; using template.",
                            canonical, check.offendingList());
                    return fallback.narrate(incident, findings, persona);
                }
            }

            log.info("Narrative ({}) rendered incident '{}' for persona '{}'.",
                    TIER.modelId(), incident.id(), canonical);
            return new Narrative(title, whyNow, body);

        } catch (Exception e) {
            log.warn("Narrative call failed ({}); using deterministic template.", e.toString());
            return fallback.narrate(incident, findings, persona);
        }
    }

    private String narrateRequest(Incident incident, List<Finding> findings, String persona) {
        ObjectNode root = json.createObjectNode();
        root.put("persona", persona);
        prefix.personaGuide(persona).ifPresent(guide -> root.put("persona_guide", guide));

        ObjectNode inc = root.putObject("incident");
        inc.put("id", incident.id());
        inc.put("title", incident.title());
        inc.put("why_now", incident.whyNow());
        inc.put("severity", incident.severity());
        inc.put("explanation", incident.explanation());
        if (incident.policy() != null) {
            ObjectNode p = inc.putObject("policy");
            p.put("rule_id", incident.policy().ruleId());
            p.put("breached", incident.policy().breached());
            p.put("severity_band", incident.policy().severityBand());
            p.put("consecutive_periods", incident.policy().consecutivePeriods());
        }
        if (incident.quality() != null) {
            ObjectNode q = inc.putObject("data_quality");
            q.put("coverage", incident.quality().coverage());
            q.put("confidence", incident.quality().confidence());
            ArrayNode cav = q.putArray("caveats");
            incident.quality().caveats().forEach(cav::add);
        }
        ArrayNode actions = inc.putArray("actions");
        for (Action a : incident.recommendedActions()) {
            ObjectNode an = actions.addObject();
            an.put("type", a.type());
            an.put("target", a.target());
            an.put("permitted", a.permitted());
            an.put("reason", a.reason());
        }

        root.put("task", """
                Write this incident for the named persona, following the persona guide exactly.

                Lead with the outcome — the first sentence answers "what happened", not "what we did". \
                Name the responsible entity and quantify its contribution. State every figure against \
                a reference point. Disclose data-quality caveats inline, in the prose, not as a footnote.

                If an action is not permitted, say so and say why — do not present it as available.

                NO INTERNAL VOCABULARY, for any persona. The payload keys are field names, not words: \
                never write robust_z, rate_effect, mix_effect, severity bands like SLA-NONE-000, \
                metric ids like cost_per_trip, or dimension names like trip_direction or shift_type. \
                Write what they mean — "the morning pickups", "the trips themselves got slower", \
                "well outside its normal month-to-month range". This was previously required only of \
                facilities_head, which was the wrong reading: the transport manager is not a systems \
                engineer either, and the line manager least of all.

                For facilities_head the result must additionally be self-contained and forwardable to \
                leadership without editing — no internal identifiers, and no reference to this tool.

                HARD CONSTRAINT: every number you write must appear verbatim in the payload above. \
                Never compute, derive, average or re-round anything.""");

        root.put("response_format",
                "Reply with ONLY a JSON object: {\"title\":\"one line\",\"why_now\":\"one or two "
                        + "sentences\",\"body\":\"markdown\"}");

        ArrayNode fs = root.putArray("supporting_findings");
        if (findings != null) {
            findings.stream().limit(8).forEach(f -> {
                ObjectNode n = fs.addObject();
                n.put("metric", f.metricId());
                n.put("dimension", f.dimension());
                n.put("entity", f.entity());
                n.put("current", f.current());
                n.put("prior", f.prior());
                n.put("delta", f.deltaPts());
                n.put("trips", f.sampleSize());
            });
        }
        return root.toPrettyString();
    }

    // ---- the leadership brief --------------------------------------------------------------------

    @Override
    public String brief(String period, String persona, List<Incident> incidents, List<String> headline) {
        if (!claude.isAvailable()) {
            return fallback.brief(period, persona, incidents, headline);
        }
        try {
            String canonical = prefix.canonicalPersona(persona);

            ObjectNode root = json.createObjectNode();
            root.put("period", period);
            root.put("persona", canonical);
            prefix.personaGuide(canonical).ifPresent(g -> root.put("persona_guide", g));

            ArrayNode hl = root.putArray("headline_facts");
            if (headline != null) {
                headline.forEach(hl::add);
            }
            ArrayNode arr = root.putArray("incidents");
            if (incidents != null) {
                for (Incident i : incidents) {
                    ObjectNode n = arr.addObject();
                    n.put("title", i.title());
                    n.put("severity", i.severity());
                    n.put("why_now", i.whyNow());
                    n.put("explanation", i.explanation());
                }
            }

            root.put("task", """
                    Write the period brief for this persona. Conclusion first, in the title line. \
                    Nine sentences or fewer for facilities_head. Cover what moved, who is responsible, \
                    what it costs or risks, and what you recommend. Disclose data-quality caveats in a \
                    closing line. It must be forwardable to leadership without a single edit.

                    Every number must come verbatim from the payload. Invent nothing.""");
            root.put("response_format", "Reply with ONLY markdown. No JSON, no code fence.");

            String out = claude.complete(TIER, prefix.prefix(), root.toPrettyString(), MAX_TOKENS_BRIEF);
            if (out == null || out.isBlank()) {
                return fallback.brief(period, persona, incidents, headline);
            }
            log.info("Brief ({}) rendered for persona '{}', period {}.", TIER.modelId(), canonical, period);
            return out.trim();

        } catch (Exception e) {
            log.warn("Brief call failed ({}); using deterministic template.", e.toString());
            return fallback.brief(period, persona, incidents, headline);
        }
    }

    private JsonNode readJson(String raw) {
        String extracted = ClaudeClient.extractJsonObject(raw);
        if (extracted == null || extracted.isBlank()) {
            return null;
        }
        try {
            return json.readTree(extracted);
        } catch (Exception e) {
            log.warn("Narrative response was not parseable JSON: {}", e.toString());
            return null;
        }
    }
}
