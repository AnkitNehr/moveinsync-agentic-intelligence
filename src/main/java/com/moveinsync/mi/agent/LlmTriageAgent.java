package com.moveinsync.mi.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.moveinsync.mi.llm.CachedPrefixBuilder;
import com.moveinsync.mi.llm.ClaudeClient;
import com.moveinsync.mi.llm.ModelTier;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.fallback.DeterministicTriage;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Service;

/**
 * Triage — the first and cheapest model call in the pipeline.
 *
 * <p>One batched request for the entire ranked candidate list, never one per finding. That is a
 * deliberate cost lever: twenty findings cost one call, not twenty. The model receives roughly 4 KB
 * of already-computed JSON — no trip rows ever reach it — and answers a question code is genuinely
 * bad at: which of these movements deserve to interrupt a human this morning, and which of them are
 * the same story told from different angles.
 *
 * <p>The clustering is the value. On the real June extract, the on-time drop surfaces on nineteen
 * correlated slices (office, product type, route source, business unit, direction). A threshold rule
 * emits nineteen alerts about one problem. This agent is asked to emit one.
 *
 * <p>Every failure path — no credential, malformed JSON, a network blip, an empty response — falls
 * back to {@link DeterministicTriage} rather than throwing. A demo must never die because an API
 * call did.
 */
@Service
@Order(0)
public class LlmTriageAgent implements TriagePort {

    private static final Logger log = LoggerFactory.getLogger(LlmTriageAgent.class);

    private static final ModelTier TIER = ModelTier.MID;
    private static final int MAX_TOKENS = 4000;

    /** Candidates handed to the model. Beyond this the marginal finding is noise. */
    private static final int MAX_CANDIDATES = 20;

    private final ClaudeClient claude;
    private final CachedPrefixBuilder prefix;
    private final MetricFormat format;
    private final DeterministicTriage fallback;
    private final ObjectMapper json = new ObjectMapper();

    public LlmTriageAgent(
            ClaudeClient claude,
            CachedPrefixBuilder prefix,
            MetricFormat format,
            DeterministicTriage fallback) {
        this.claude = claude;
        this.prefix = prefix;
        this.format = format;
        this.fallback = fallback;
    }

    @Override
    public String tier() {
        return claude.isAvailable() ? TIER.modelId() : fallback.tier();
    }

    @Override
    public List<IncidentDraft> triage(List<Finding> ranked, String period) {
        if (!claude.isAvailable() || ranked == null || ranked.isEmpty()) {
            return fallback.triage(ranked, period);
        }
        try {
            List<Finding> candidates = ranked.size() > MAX_CANDIDATES
                    ? ranked.subList(0, MAX_CANDIDATES)
                    : ranked;

            String raw = claude.complete(TIER, prefix.prefix(), buildRequest(candidates, period), MAX_TOKENS);
            List<IncidentDraft> drafts = parse(raw, candidates);

            if (drafts.isEmpty()) {
                log.warn("Triage returned no usable incidents; falling back to deterministic clustering.");
                return fallback.triage(ranked, period);
            }
            log.info("Triage ({}) clustered {} candidates into {} incidents.",
                    TIER.modelId(), candidates.size(), drafts.size());
            return drafts;

        } catch (Exception e) {
            log.warn("Triage call failed ({}); falling back to deterministic clustering.", e.toString());
            return fallback.triage(ranked, period);
        }
    }

    // ---- request ---------------------------------------------------------------------------------

    private String buildRequest(List<Finding> candidates, String period) {
        ObjectNode root = json.createObjectNode();
        root.put("period", period);
        root.put("task", """
                Cluster these ranked findings into the few incidents a transport manager should act on \
                this morning. Findings that describe the same underlying movement seen through different \
                dimensions are ONE incident, not several — put every such finding id in the same cluster. \
                Order by how much a human should care. Return between 1 and 5 incidents. \
                Do not invent numbers: titles and rationale may only restate figures present in the input.""");

        ArrayNode arr = root.putArray("candidates");
        for (Finding f : candidates) {
            ObjectNode n = arr.addObject();
            n.put("finding_id", f.id());
            n.put("metric", f.metricId());
            n.put("metric_label", format.label(f.metricId()));
            n.put("dimension", f.dimension());
            n.put("entity", f.entity());
            n.put("current", round(f.current()));
            n.put("prior", round(f.prior()));
            n.put("delta", round(f.deltaPts()));
            n.put("delta_display", format.delta(f.metricId(), f.deltaPts()));
            n.put("trips", f.sampleSize());
            n.put("robust_z", round(f.robustZ()));
            n.put("rank_score", round(f.score()));
            if (f.observation() != null && f.observation().references() != null
                    && f.observation().references().sla() != null) {
                n.put("sla_breached", f.observation().references().sla().breached());
                Double target = f.observation().references().sla().target();
                if (target != null) {
                    n.put("sla_target", round(target));
                }
            }
        }

        root.put("response_format", """
                Reply with ONLY a JSON object, no prose and no code fence:
                {"incidents":[{"finding_ids":["..."],"title":"...","why_now":"...","priority":1,\
                "rationale":"..."}]}
                priority is 1 for the most important. title is one line, no markdown. \
                why_now explains why it deserves attention today, in one or two sentences.""");

        return root.toPrettyString();
    }

    // ---- response --------------------------------------------------------------------------------

    private List<IncidentDraft> parse(String raw, List<Finding> candidates) {
        String extracted = ClaudeClient.extractJsonObject(raw);
        if (extracted == null || extracted.isBlank()) {
            return List.of();
        }

        Map<String, Finding> byId = candidates.stream()
                .collect(Collectors.toMap(Finding::id, Function.identity(), (a, b) -> a));

        JsonNode incidents;
        try {
            incidents = json.readTree(extracted).path("incidents");
        } catch (Exception e) {
            log.warn("Triage response was not parseable JSON: {}", e.toString());
            return List.of();
        }
        if (!incidents.isArray()) {
            return List.of();
        }

        List<IncidentDraft> drafts = new ArrayList<>();
        Set<String> claimed = new HashSet<>();

        for (JsonNode node : incidents) {
            // Only ids the scanner actually produced survive. A hallucinated id is dropped rather
            // than trusted — the model clusters, it does not get to invent findings.
            Set<String> ids = new LinkedHashSet<>();
            for (JsonNode idNode : node.path("finding_ids")) {
                String id = idNode.asText(null);
                if (id != null && byId.containsKey(id) && claimed.add(id)) {
                    ids.add(id);
                }
            }
            if (ids.isEmpty()) {
                continue;
            }

            Finding lead = byId.get(ids.iterator().next());
            String title = text(node, "title", lead == null ? "Incident" : defaultTitle(lead));
            String whyNow = text(node, "why_now", "");
            String rationale = text(node, "rationale", "");
            int priority = node.path("priority").asInt(drafts.size() + 1);

            drafts.add(new IncidentDraft(
                    lead == null ? title : lead.metricId() + "|" + lead.dimension(),
                    title,
                    whyNow,
                    priority,
                    List.copyOf(ids),
                    rationale));
        }

        drafts.sort(java.util.Comparator.comparingInt(IncidentDraft::priority));
        return drafts;
    }

    private String defaultTitle(Finding f) {
        return format.label(f.metricId()) + " moved on " + f.dimension() + " = " + f.entity();
    }

    private static String text(JsonNode node, String field, String fallbackValue) {
        String v = node.path(field).asText(null);
        return v == null || v.isBlank() ? fallbackValue : v.trim();
    }

    private static double round(double v) {
        return Double.isFinite(v) ? Math.round(v * 100.0) / 100.0 : 0.0;
    }
}
