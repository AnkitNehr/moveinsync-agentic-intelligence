package com.moveinsync.mi.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.moveinsync.mi.agent.guard.NumericValidator;
import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.llm.CachedPrefixBuilder;
import com.moveinsync.mi.llm.ClaudeClient;
import com.moveinsync.mi.llm.ModelClient;
import com.moveinsync.mi.llm.ModelTier;
import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.fallback.DeterministicReasoner;
import com.moveinsync.mi.pipeline.spi.ReasoningPort;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Service;

/**
 * Reasoning — the expensive call, and the only place a model is asked to form a causal claim.
 *
 * <p>It receives the incident's findings with their computed contributions already decomposed into
 * rate and mix effects, and is asked why the movement happened. It cannot query anything: every
 * number it is allowed to use is in the payload, which is what makes the arithmetic un-inventable.
 *
 * <p>Output passes through {@link NumericValidator}. Any figure in the prose that does not trace
 * back to a supplied observation causes one retry that names the offending numbers explicitly; a
 * second failure falls back to the deterministic template. This is the mechanism that turns "the
 * model never computes a number" from a claim in a slide into something enforced at runtime.
 */
@Service
@Order(0)
public class LlmReasoningAgent implements ReasoningPort {

    private static final Logger log = LoggerFactory.getLogger(LlmReasoningAgent.class);

    private static final ModelTier TIER = ModelTier.STRONG;
    private static final int MAX_TOKENS = 6000;
    private static final int MAX_CONTRIBUTIONS = 8;

    private final ModelClient claude;
    private final CachedPrefixBuilder prefix;
    private final MetricFormat format;
    private final NumericValidator validator;
    private final DeterministicReasoner fallback;
    private final ObjectMapper json = new ObjectMapper();

    public LlmReasoningAgent(
            ModelClient claude,
            CachedPrefixBuilder prefix,
            MetricFormat format,
            NumericValidator validator,
            DeterministicReasoner fallback) {
        this.claude = claude;
        this.prefix = prefix;
        this.format = format;
        this.validator = validator;
        this.fallback = fallback;
    }

    @Override
    public String tier() {
        return claude.isAvailable() ? TIER.modelId() : fallback.tier();
    }

    @Override
    public Explanation explain(
            TriagePort.IncidentDraft draft, List<Finding> findings, AttributionResult attribution) {

        if (!claude.isAvailable() || findings == null || findings.isEmpty()) {
            return fallback.explain(draft, findings, attribution);
        }

        try {
            String request = buildRequest(draft, findings);
            String raw = claude.complete(TIER, prefix.prefix(), request, MAX_TOKENS);
            Explanation parsed = parse(raw);

            if (parsed == null) {
                return fallback.explain(draft, findings, attribution);
            }

            NumericValidator.ValidationResult check =
                    validator.validateAgainstFindings(parsed.explanation(), findings);

            if (!check.ok()) {
                // One retry, naming the offending figures. If the model cannot restate the finding
                // using only supplied numbers, we do not argue with it — we use the template.
                log.warn("Reasoning output contained unsupported numbers {}; retrying once.",
                        check.offendingList());
                String retry = claude.complete(TIER, prefix.prefix(),
                        request + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED. It contained these numbers "
                                + "which do not appear anywhere in the input: " + check.offendingList()
                                + ". Rewrite using ONLY figures present in the payload above. Do not "
                                + "compute, round differently, derive, or estimate any new value.",
                        MAX_TOKENS);
                Explanation second = parse(retry);
                if (second == null
                        || !validator.validateAgainstFindings(second.explanation(), findings).ok()) {
                    log.warn("Reasoning retry still failed validation; using deterministic template.");
                    return fallback.explain(draft, findings, attribution);
                }
                parsed = second;
            }

            log.info("Reasoning ({}) explained incident '{}'.", TIER.modelId(), draft.title());
            return parsed;

        } catch (Exception e) {
            log.warn("Reasoning call failed ({}); using deterministic template.", e.toString());
            return fallback.explain(draft, findings, attribution);
        }
    }

    // ---- request ---------------------------------------------------------------------------------

    private String buildRequest(TriagePort.IncidentDraft draft, List<Finding> findings) {
        ObjectNode root = json.createObjectNode();
        root.put("incident_title", draft.title());
        root.put("why_now", draft.whyNow());

        ArrayNode arr = root.putArray("findings");
        for (Finding f : findings) {
            ObjectNode n = arr.addObject();
            n.put("finding_id", f.id());
            n.put("metric", f.metricId());
            n.put("metric_label", format.label(f.metricId()));
            n.put("dimension", f.dimension());
            n.put("entity", f.entity());
            n.put("period", f.period());
            n.put("prior_period", f.priorPeriod());
            n.put("current", round(f.current()));
            n.put("prior", round(f.prior()));
            n.put("delta", round(f.deltaPts()));
            n.put("trips", f.sampleSize());
            n.put("robust_z", round(f.robustZ()));

            if (f.observation() != null && f.observation().references() != null) {
                var refs = f.observation().references();
                ObjectNode r = n.putObject("references");
                if (refs.sla() != null) {
                    r.put("sla_target", refs.sla().target());
                    r.put("sla_breached", refs.sla().breached());
                }
                if (refs.peer() != null) {
                    r.put("peer_median", refs.peer().cohortMedian());
                    r.put("peer_rank", refs.peer().rank());
                }
                if (refs.industry() != null) {
                    r.put("industry_benchmark", refs.industry().benchmark());
                }
            }

            List<Contribution> contributions = f.contributions();
            if (contributions != null && !contributions.isEmpty()) {
                ArrayNode c = n.putArray("contributions");
                contributions.stream().limit(MAX_CONTRIBUTIONS).forEach(k -> {
                    ObjectNode cn = c.addObject();
                    cn.put("entity", k.entity());
                    cn.put("rate_effect", round(k.rateEffect()));
                    cn.put("mix_effect", round(k.mixEffect()));
                    cn.put("total_effect", round(k.total()));
                    cn.put("share_before", round(k.shareBefore()));
                    cn.put("share_after", round(k.shareAfter()));
                });
            }
        }

        root.put("task", """
                Explain WHY this movement happened, for a transport manager who will act on it today.

                The contributions are already decomposed for you: rate_effect is "this entity got \
                worse or better", mix_effect is "volume moved toward or away from this entity". \
                Read them and say which of the two is actually driving the movement — if mix effects \
                are small, say plainly that this is a performance change and NOT a redistribution of \
                volume, and do not offer a volume-shift explanation the numbers do not support.

                Be specific about what a human should do differently tomorrow. Distinguish causes \
                that need different remedies.

                WRITE FOR A READER WHO HAS NEVER SEEN THIS SYSTEM. The keys in the payload are \
                internal field names, not vocabulary: never write rate_effect, mix_effect, robust_z, \
                metric ids like cost_per_trip, or dimension names like trip_direction in your prose. \
                Say "the trips themselves got slower" rather than "rate_effect was -2.41", "the \
                morning/evening split" rather than "trip_direction", and "a far bigger swing than \
                this normally moves" rather than quoting a z-score. A statistic the reader cannot \
                interpret is not evidence to them; it is a request that they trust you.

                HARD CONSTRAINT: every number in your prose must appear verbatim in the payload above. \
                Do not add, derive, average, round differently, or estimate any figure. If you want to \
                say something you cannot support with a supplied number, say it qualitatively instead.""");

        root.put("response_format", """
                Reply with ONLY a JSON object, no prose and no code fence:
                {"hypothesis":"one line","explanation":"2-4 short paragraphs of markdown",\
                "evidence":[{"claim":"the sentence","metric_id":"...","entity":"..."}]}""");

        return root.toPrettyString();
    }

    // ---- response --------------------------------------------------------------------------------

    private Explanation parse(String raw) {
        String extracted = ClaudeClient.extractJsonObject(raw);
        if (extracted == null || extracted.isBlank()) {
            return null;
        }
        try {
            JsonNode node = json.readTree(extracted);
            String explanation = node.path("explanation").asText("").trim();
            if (explanation.isEmpty()) {
                return null;
            }
            String hypothesis = node.path("hypothesis").asText("").trim();

            List<Evidence> evidence = new ArrayList<>();
            for (JsonNode e : node.path("evidence")) {
                String claim = e.path("claim").asText(null);
                if (claim != null && !claim.isBlank()) {
                    evidence.add(new Evidence(
                            claim.trim(),
                            e.path("metric_id").asText(null),
                            e.path("entity").asText(null)));
                }
            }
            return new Explanation(explanation, evidence, hypothesis);
        } catch (Exception e) {
            log.warn("Reasoning response was not parseable JSON: {}", e.toString());
            return null;
        }
    }

    private static double round(double v) {
        return Double.isFinite(v) ? Math.round(v * 100.0) / 100.0 : 0.0;
    }
}
