package com.moveinsync.mi.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.moveinsync.mi.agent.guard.NumericValidator;
import com.moveinsync.mi.anomaly.StandingOutlierScanner;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.llm.ClaudeClient;
import com.moveinsync.mi.llm.ModelClient;
import com.moveinsync.mi.llm.ModelTier;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.fallback.BuiltInChatRouter;
import com.moveinsync.mi.pipeline.spi.ChatPort;
import com.moveinsync.mi.pipeline.spi.UsageLedger;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Service;

/**
 * The conversational tier: a model that chooses <em>which</em> number to fetch, never what it is.
 *
 * <h2>Where this sits</h2>
 *
 * <p>Keyword resolution answers the common questions for nothing — no model call, no tokens, and by
 * construction the same figure the dashboard shows. That path runs first and is never bypassed:
 * "what is the no-show rate" must not cost money or vary between askings.
 *
 * <p>But keyword matching always has a tail. "Which of our southern offices has the worst punctuality
 * on the early shift" names three constraints no regex was written for, and the honest deterministic
 * answer is a refusal. This class is what happens after that refusal instead of the refusal shipping.
 *
 * <h2>The loop</h2>
 *
 * <p>The model is handed the catalog and a small set of tools, and answers in JSON: either a tool it
 * wants run, or its final prose. Java executes the tool against the same metric layer everything else
 * uses, feeds the result back, and repeats up to {@link #MAX_ROUNDS} times.
 *
 * <p>Tools are described in the prompt rather than through any provider's native function-calling
 * API, because four providers are supported and they disagree about that API. A JSON contract in the
 * prompt works identically on all of them, which is the same reason {@code ModelClient} exposes only
 * text in and text out.
 *
 * <h2>Why the answer is still trustworthy</h2>
 *
 * <p>Two properties hold, and neither depends on the model behaving:
 *
 * <ol>
 *   <li><strong>Every number is computed by Java.</strong> The model selects a metric, a dimension,
 *       an entity and a period. It never supplies a value. Tool results come from
 *       {@code MetricQueryService} — the same code path as the dashboard and the nightly run.
 *   <li><strong>The prose is validated before it ships.</strong> Every figure in the final answer is
 *       checked against the numbers the tools actually returned. A model that paraphrases a figure
 *       into something plausible but different is caught and the answer is refused, because a wrong
 *       number a user can quote in a meeting is worse than no answer.
 * </ol>
 *
 * <p>So the question "does the model's output go straight to the user unchecked" has a firm no. It
 * goes to a guard that holds the tool results and can prove what was and was not supplied.
 */
@Service
@Order(0)
public class LlmChatAgent implements ChatPort {

    private static final Logger log = LoggerFactory.getLogger(LlmChatAgent.class);

    /** Conversational lookups are the cheap tier: the reasoning was done before the question. */
    private static final ModelTier TIER = ModelTier.CHEAP;

    /**
     * Tool calls allowed per question.
     *
     * <p>Three covers the realistic shapes — discover what entities exist, read one, compare against
     * a ranking — while bounding a bad run to three cheap calls. A model that has not answered by
     * then is looping, and looping quietly is how a conversational endpoint becomes expensive.
     */
    private static final int MAX_ROUNDS = 3;

    private static final int MAX_TOKENS = 1200;

    /** Rows returned to the model from a listing tool. Enough to choose from, not enough to bloat. */
    private static final int TOOL_ROW_LIMIT = 25;

    private final ModelClient model;
    private final NumericValidator validator;
    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final BenchmarkService benchmarks;
    private final AttributionService attribution;
    private final IncidentStore incidents;
    private final MetricFormat format;
    private final StandingOutlierScanner standing;
    private final BuiltInChatRouter deterministic;
    private final ObjectMapper json = new ObjectMapper();

    public LlmChatAgent(
            ModelClient model,
            NumericValidator validator,
            MetricCatalog catalog,
            MetricQueryService metrics,
            BenchmarkService benchmarks,
            AttributionService attribution,
            MetricFormat format,
            IncidentStore incidents,
            StandingOutlierScanner standing) {
        this.model = model;
        this.validator = validator;
        this.catalog = catalog;
        this.metrics = metrics;
        this.benchmarks = benchmarks;
        this.attribution = attribution;
        this.format = format;
        this.incidents = incidents;
        this.standing = standing;
        // Owns its own deterministic router rather than asking the container for one: PortRegistry
        // constructs BuiltInChatRouter inline, so there is no bean to inject, and a second instance
        // is stateless anyway.
        this.deterministic = new BuiltInChatRouter(catalog, metrics, benchmarks, attribution, format, incidents);
    }

    @Override
    public String tier() {
        return model.isAvailable() ? TIER.modelId() : deterministic.tier();
    }

    @Override
    public Answer ask(String question, String defaultPeriod) {
        Answer direct = deterministic.ask(question, defaultPeriod);

        // The deterministic path wins whenever it can answer. Cheaper, instant, and identical to the
        // dashboard by construction — there is no version of "ask the model instead" that improves on
        // that for a question the catalog already understands.
        if (direct == null || !direct.declined() || !model.isAvailable()) {
            return direct;
        }

        log.info("Deterministic router declined '{}'; escalating to {}", question, model.providerName());
        try {
            Answer answered = converse(question, defaultPeriod);
            return answered == null ? direct : answered;
        } catch (Exception e) {
            log.warn("Conversational tier failed ({}); returning the deterministic refusal.", e.toString());
            return direct;
        }
    }

    // ---- the tool loop ---------------------------------------------------------------------------

    private Answer converse(String question, String defaultPeriod) {
        // Everything the tools hand back is collected here. It is both what the model is allowed to
        // say and the proof of what it was given, so the guard at the end has something real to
        // check against rather than a promise.
        Set<Double> allowedValues = new HashSet<>();
        Set<String> allowedLiterals = new LinkedHashSet<>();
        List<Evidence> citations = new ArrayList<>();
        StringBuilder transcript = new StringBuilder();

        long promptTokens = 0;
        long completionTokens = 0;
        long calls = 0;
        String lastTool = null;

        for (int round = 1; round <= MAX_ROUNDS; round++) {
            // The last round is not offered tools. Without this the model can spend every round
            // fetching and never answer, and the user gets a refusal built from data that was
            // successfully retrieved — the worst of both paths, paid for in full.
            boolean finalRound = round == MAX_ROUNDS;
            String request = buildRequest(question, defaultPeriod, transcript.toString(), finalRound);
            String raw = model.complete(TIER, systemPrefix(), request, MAX_TOKENS);
            calls++;
            promptTokens += estimateTokens(request);
            completionTokens += estimateTokens(raw);

            JsonNode node = readJson(raw);
            if (node == null) {
                // The raw text matters here. "Unparseable" with no sample is not a diagnosis, and
                // this is the boundary where a provider's formatting habits show up.
                log.warn("Conversational tier returned unparseable JSON on round {} of {}: {}",
                        round, MAX_ROUNDS, raw == null ? "null" : abbreviate(raw));
                return null;
            }

            if (node.hasNonNull("answer")) {
                String prose = node.path("answer").asText("").trim();
                if (prose.isEmpty()) {
                    return null;
                }
                return guard(prose, allowedValues, allowedLiterals, citations, lastTool,
                        new UsageLedger.Usage(promptTokens, completionTokens, calls, 0.0));
            }

            String tool = node.path("tool").asText(null);
            if (tool == null) {
                return null;
            }
            lastTool = tool;
            String result = runTool(tool, node.path("args"), defaultPeriod,
                    allowedValues, allowedLiterals, citations);
            transcript.append("\nTOOL ").append(tool).append(" RETURNED:\n").append(result).append('\n');
        }

        // Out of rounds without an answer. Returning null hands the caller back the deterministic
        // refusal, which is honest, rather than whatever half-formed text the last round produced.
        log.warn("Conversational tier used all {} rounds without answering '{}'", MAX_ROUNDS, question);
        return null;
    }

    /**
     * The last gate. Every figure in the prose must be one a tool actually returned.
     *
     * <p>This is what makes the tier safe to expose. The model chose the data and wrote the sentence;
     * it did not supply a single number, and if it has introduced one — by rounding differently,
     * averaging two rows, or inventing outright — the answer is discarded rather than shown. A wrong
     * figure a manager can quote in a meeting is worse than no figure.
     */
    private Answer guard(
            String prose,
            Set<Double> allowedValues,
            Set<String> allowedLiterals,
            List<Evidence> citations,
            String tool,
            UsageLedger.Usage usage) {

        NumericValidator.ValidationResult check = validator.validate(
                prose, new NumericValidator.NumericContext(allowedValues, allowedLiterals));
        if (!check.ok()) {
            log.warn("Conversational answer contained unsupported numbers {}; refusing it.",
                    check.offendingList());
            return null;
        }
        return new Answer(
                prose,
                new ResolvedCall(tool == null ? "converse" : tool, "llm", null, null, null),
                citations,
                usage,
                false);
    }

    // ---- tools -----------------------------------------------------------------------------------

    /**
     * Runs one tool and records everything it returned as permissible for the final answer.
     *
     * @return a compact text rendering for the model; never null, so a bad tool name teaches the
     *         model what it did wrong rather than ending the conversation
     */
    private String runTool(
            String tool,
            JsonNode args,
            String defaultPeriod,
            Set<Double> allowedValues,
            Set<String> allowedLiterals,
            List<Evidence> citations) {

        String metricId = text(args, "metric");
        String dimension = text(args, "dimension");
        String entity = text(args, "entity");
        String period = text(args, "period");
        if (period == null || period.isBlank()) {
            period = defaultPeriod;
        }

        try {
            return switch (tool.toLowerCase(Locale.ROOT)) {
                case "list_metrics" -> listMetrics();
                case "list_entities" -> listEntities(metricId, dimension, period, allowedValues, allowedLiterals);
                case "observe" -> observe(metricId, dimension, entity, period,
                        allowedValues, allowedLiterals, citations);
                case "profile" -> profile(dimension, entity, period,
                        allowedValues, allowedLiterals, citations);
                case "attribute" -> attribute(metricId, dimension, period,
                        allowedValues, allowedLiterals, citations);
                case "rank" -> rank(metricId, dimension, period,
                        allowedValues, allowedLiterals, citations);
                case "standing_outliers" -> standingOutliers(period, allowedValues, allowedLiterals, citations);
                default -> "ERROR: no such tool. Available: list_metrics, list_entities, observe, profile, "
                        + "attribute, rank, standing_outliers.";
            };
        } catch (RuntimeException e) {
            log.debug("Tool {} failed: {}", tool, e.toString());
            return "ERROR: " + e.getMessage() + ". Try different arguments, or answer from what you have.";
        }
    }

    private String listMetrics() {
        StringBuilder out = new StringBuilder();
        for (MetricDefinition d : catalog.all()) {
            out.append(d.id()).append(" (").append(d.label()).append(") — grains: ")
                    .append(String.join(", ", d.sliceableGrains())).append('\n');
        }
        return out.toString();
    }

    private String listEntities(
            String metricId, String dimension, String period,
            Set<Double> allowedValues, Set<String> allowedLiterals) {
        if (metricId == null || dimension == null) {
            return "ERROR: list_entities needs metric and dimension.";
        }
        List<MetricSlice> all = metrics.slices(metricId, dimension, period).stream()
                .filter(MetricSlice::measured)
                .toList();
        if (all.isEmpty()) {
            return "no entities on that dimension in " + period;
        }

        // The count is stated, not left for the model to work out. Counting is arithmetic, and a
        // model that counts is supplying a figure no tool returned — which the guard correctly
        // rejects, so "how many vendors are there" would be refused on data we are holding. The tool
        // that knows the answer is the one that should say it.
        int total = all.size();
        allowedValues.add((double) total);
        StringBuilder out = new StringBuilder();
        out.append(total).append(" entities on ").append(dimension).append(" in ").append(period);
        if (total > TOOL_ROW_LIMIT) {
            out.append(" (first ").append(TOOL_ROW_LIMIT).append(" named)");
        }
        out.append(":\n");
        for (MetricSlice s : all.stream().limit(TOOL_ROW_LIMIT).toList()) {
            allowedLiterals.add(s.entity());
            out.append(s.entity()).append('\n');
        }
        return out.toString();
    }

    private String resolveEntityFuzzy(String metricId, String dimension, String candidate, String period) {
        if (candidate == null || candidate.isBlank() || dimension == null) {
            return candidate;
        }
        String cleanCand = candidate.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();
        List<MetricSlice> slices;
        try {
            slices = metrics.slices(metricId, dimension, period);
        } catch (RuntimeException e) {
            return candidate;
        }
        for (MetricSlice s : slices) {
            if (s.entity() == null) continue;
            String cleanEnt = s.entity().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();
            if (cleanEnt.equals(cleanCand) || cleanEnt.contains(cleanCand)) {
                return s.entity();
            }
            for (String tok : cleanCand.split("\\s+")) {
                if (tok.length() >= 4 && cleanEnt.contains(tok)) {
                    return s.entity();
                }
            }
        }
        return candidate;
    }

    private String observe(
            String metricId, String dimension, String entity, String period,
            Set<Double> allowedValues, Set<String> allowedLiterals, List<Evidence> citations) {

        if (metricId == null) {
            return "ERROR: observe needs a metric.";
        }
        if (dimension != null && entity != null && !entity.equalsIgnoreCase("ALL")) {
            entity = resolveEntityFuzzy(metricId, dimension, entity, period);
        }
        var observation = benchmarks.observe(
                metricId,
                dimension == null ? "global" : dimension,
                entity == null ? "ALL" : entity,
                period);
        if (observation == null || observation.value() == null) {
            return "no value for that combination in " + period;
        }
        record(allowedValues, allowedLiterals, observation.value(), period, entity);
        String rendered = "%s for %s = %s in %s across %,d trips".formatted(
                format.label(metricId),
                dimension == null ? "the fleet" : dimension,
                format.value(metricId, observation.value()),
                period,
                observation.sampleSize());
        allowedValues.add((double) observation.sampleSize());
        citations.add(new Evidence(rendered, metricId, entity == null ? "ALL" : entity));
        return rendered;
    }

    private String profile(
            String dimension, String entity, String period,
            Set<Double> allowedValues, Set<String> allowedLiterals, List<Evidence> citations) {
        if (entity == null || entity.isBlank()) {
            return "ERROR: profile needs an entity.";
        }

        String resolvedDimension = dimension;
        String resolvedEntity = entity;
        String cleanCand = entity.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();

        if (resolvedDimension == null || resolvedDimension.isBlank()) {
            for (MetricDefinition d : catalog.all()) {
                for (String grain : d.sliceableGrains()) {
                    List<MetricSlice> slices;
                    try {
                        slices = metrics.slices(d.id(), grain, period);
                    } catch (RuntimeException e) {
                        continue;
                    }
                    for (MetricSlice s : slices) {
                        if (s.entity() == null) continue;
                        String cleanEnt = s.entity().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();
                        if (cleanEnt.contains(cleanCand)) {
                            resolvedDimension = grain;
                            resolvedEntity = s.entity();
                            break;
                        }
                        for (String tok : cleanCand.split("\\s+")) {
                            if (tok.length() >= 4 && cleanEnt.contains(tok)) {
                                resolvedDimension = grain;
                                resolvedEntity = s.entity();
                                break;
                            }
                        }
                        if (resolvedDimension != null) break;
                    }
                    if (resolvedDimension != null) break;
                }
                if (resolvedDimension != null) break;
            }
        } else {
            for (MetricDefinition d : catalog.all()) {
                if (d.supports(resolvedDimension)) {
                    List<MetricSlice> slices = metrics.slices(d.id(), resolvedDimension, period);
                    for (MetricSlice s : slices) {
                        if (s.entity() == null) continue;
                        String cleanEnt = s.entity().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();
                        if (cleanEnt.contains(cleanCand)) {
                            resolvedEntity = s.entity();
                            break;
                        }
                        for (String tok : cleanCand.split("\\s+")) {
                            if (tok.length() >= 4 && cleanEnt.contains(tok)) {
                                resolvedEntity = s.entity();
                                break;
                            }
                        }
                        if (!resolvedEntity.equals(entity)) break;
                    }
                    break;
                }
            }
        }

        if (resolvedDimension == null) {
            resolvedDimension = "vendor";
        }

        StringBuilder out = new StringBuilder();
        out.append("Profile for ").append(resolvedDimension).append(" ").append(resolvedEntity)
                .append(" in ").append(period).append(":\n");
        allowedLiterals.add(resolvedEntity);
        if (period != null) {
            allowedLiterals.add(period);
        }

        for (MetricDefinition d : catalog.all()) {
            if (!d.supports(resolvedDimension)) {
                continue;
            }
            List<MetricSlice> cohort = metrics.slices(d.id(), resolvedDimension, period).stream()
                    .filter(MetricSlice::measured)
                    .toList();
            String finalEnt = resolvedEntity;
            MetricSlice mine = cohort.stream()
                    .filter(s -> finalEnt.equalsIgnoreCase(s.entity()))
                    .findFirst()
                    .orElse(null);
            if (mine == null || mine.value() == null) {
                continue;
            }
            boolean higherIsBetter = d.higherIsBetter();
            List<MetricSlice> ordered = cohort.stream()
                    .sorted(higherIsBetter
                            ? java.util.Comparator.comparingDouble((MetricSlice s) -> s.value()).reversed()
                            : java.util.Comparator.comparingDouble(MetricSlice::value))
                    .toList();
            int rank = ordered.indexOf(mine) + 1;
            double med = median(ordered);

            record(allowedValues, allowedLiterals, mine.value(), period, resolvedEntity);
            record(allowedValues, allowedLiterals, med, null, null);
            allowedValues.add((double) rank);
            allowedValues.add((double) ordered.size());

            String line = "%s: %s (rank %d of %d, cohort median %s)".formatted(
                    d.label(),
                    format.value(d.id(), mine.value()),
                    rank,
                    ordered.size(),
                    format.value(d.id(), med));
            out.append("• ").append(line).append('\n');
            citations.add(new Evidence(line, d.id(), resolvedEntity));
        }
        return out.toString();
    }

    private static double median(List<MetricSlice> ordered) {
        if (ordered.isEmpty()) {
            return 0.0;
        }
        int n = ordered.size();
        if (n % 2 == 1) {
            return ordered.get(n / 2).value();
        }
        return (ordered.get(n / 2 - 1).value() + ordered.get(n / 2).value()) / 2.0;
    }

    private String attribute(
            String metricId, String dimension, String period,
            Set<Double> allowedValues, Set<String> allowedLiterals, List<Evidence> citations) {
        if (metricId == null) {
            return "ERROR: attribute needs a metric.";
        }
        List<String> available = metrics.periods(metricId);
        if (available.isEmpty()) {
            return "no data for metric " + metricId;
        }
        String targetPeriod = period == null ? available.get(available.size() - 1) : period;
        int idx = available.indexOf(targetPeriod);
        String priorPeriod = idx > 0 ? available.get(idx - 1) : null;
        if (priorPeriod == null) {
            return "no prior period to compare against for " + targetPeriod;
        }

        var result = attribution.attribute(metricId, targetPeriod, priorPeriod);
        if (result == null || result.ranked().isEmpty()) {
            return "no significant movement to attribute for " + metricId + " in " + targetPeriod;
        }
        var top = result.winner().orElse(result.ranked().get(0));
        StringBuilder out = new StringBuilder();
        out.append(format.label(metricId)).append(" moved by ")
                .append(format.effect(metricId, result.actualDelta()))
                .append(" from ").append(priorPeriod).append(" to ").append(targetPeriod)
                .append(". Top explaining dimension is ").append(top.dimension()).append(":\n");

        allowedValues.add(Math.abs(result.actualDelta()));
        allowedLiterals.add(priorPeriod);
        allowedLiterals.add(targetPeriod);

        for (var c : top.contributions().stream().limit(5).toList()) {
            allowedValues.add(Math.abs(c.total()));
            allowedValues.add(Math.abs(c.rateEffect()));
            allowedValues.add(Math.abs(c.mixEffect()));
            allowedLiterals.add(c.entity());
            String line = "• %s: total impact %s (rate %s, mix %s)".formatted(
                    c.entity(),
                    format.effect(metricId, c.total()),
                    format.effect(metricId, c.rateEffect()),
                    format.effect(metricId, c.mixEffect()));
            out.append(line).append('\n');
            citations.add(new Evidence(line, metricId, c.entity()));
        }
        return out.toString();
    }

    private String rank(
            String metricId, String dimension, String period,
            Set<Double> allowedValues, Set<String> allowedLiterals, List<Evidence> citations) {

        if (metricId == null || dimension == null) {
            return "ERROR: rank needs metric and dimension.";
        }
        MetricDefinition definition = catalog.find(metricId).orElse(null);
        if (definition == null) {
            return "ERROR: unknown metric " + metricId;
        }
        boolean higherIsBetter = definition.higherIsBetter();
        List<MetricSlice> ordered = metrics.slices(metricId, dimension, period).stream()
                .filter(MetricSlice::measured)
                .sorted(higherIsBetter
                        ? java.util.Comparator.comparingDouble((MetricSlice s) -> s.value()).reversed()
                        : java.util.Comparator.comparingDouble(MetricSlice::value))
                .limit(TOOL_ROW_LIMIT)
                .toList();

        StringBuilder out = new StringBuilder("ranked best to worst on ")
                .append(format.label(metricId)).append(" in ").append(period).append(":\n");
        for (MetricSlice s : ordered) {
            record(allowedValues, allowedLiterals, s.value(), period, s.entity());
            allowedValues.add((double) s.sampleSize());
            String line = "%s %s (%,d trips)".formatted(
                    s.entity(), format.value(metricId, s.value()), s.sampleSize());
            out.append(line).append('\n');
            citations.add(new Evidence(line, metricId, s.entity()));
        }
        return out.toString();
    }

    private String standingOutliers(
            String period, Set<Double> allowedValues, Set<String> allowedLiterals, List<Evidence> citations) {
        var found = standing.scan(period);
        if (found.isEmpty()) {
            return "no segment is a standing outlier in " + period;
        }
        StringBuilder out = new StringBuilder("persistently poor segments in ").append(period).append(":\n");
        for (var o : found) {
            record(allowedValues, allowedLiterals, o.value(), period, o.entity());
            allowedValues.add(o.cohortMedian());
            allowedValues.add((double) o.rank());
            allowedValues.add((double) o.cohortSize());
            String line = "%s on %s: %s versus a cohort median of %s (%d of %d)".formatted(
                    o.entity(), o.metricLabel(),
                    format.value(o.metricId(), o.value()),
                    format.value(o.metricId(), o.cohortMedian()),
                    o.rank(), o.cohortSize());
            out.append(line).append('\n');
            citations.add(new Evidence(line, o.metricId(), o.entity()));
        }
        return out.toString();
    }

    /** Adds a value and its labels to the permitted set, in every form the model might write it. */
    private void record(
            Set<Double> allowedValues, Set<String> allowedLiterals,
            Double value, String period, String entity) {
        if (value != null && Double.isFinite(value)) {
            allowedValues.add(value);
            // Rates are read as percentages, so the percentage form has to be permitted too or every
            // correctly-written answer is rejected for saying 94.69 where the payload held 0.9469.
            allowedValues.add(value * 100.0);
        }
        if (period != null) {
            allowedLiterals.add(period);
        }
        if (entity != null) {
            allowedLiterals.add(entity);
        }
    }

    // ---- prompt ----------------------------------------------------------------------------------

    private String systemPrefix() {
        return """
                You answer questions about an enterprise campus-transport fleet by calling tools.

                YOU NEVER SUPPLY A NUMBER. You choose which number to fetch; the platform computes it.
                Every figure in your final answer must have appeared verbatim in a tool result. If you
                cannot support a figure, describe it qualitatively instead. Answers containing figures
                no tool returned are discarded and the user is told nothing, so inventing one helps
                no one.

                Reply with ONLY a JSON object, no prose outside it and no code fence. Either:
                  {"tool":"<name>","args":{...}}
                or, once you can answer:
                  {"answer":"your reply in plain English"}

                TOOLS
                  list_metrics   {}                                       what can be measured
                  list_entities  {metric, dimension, period}              what exists on a dimension
                  observe        {metric, dimension?, entity?, period?}   one value, with its trips
                  profile        {entity, dimension?, period?}            full profile across all metrics for an entity
                  attribute      {metric, dimension, period?}             why a metric moved across a dimension
                  rank           {metric, dimension, period}              ordered best to worst
                  standing_outliers {period}                              persistently poor segments

                Write for a transport manager. No metric ids, no column names, no jargon: say "the
                08:00 shift", not "shift_type = 08:00". Name the period you used. If the tools cannot
                answer the question, say so plainly rather than approximating.""";
    }

    private String buildRequest(
            String question, String defaultPeriod, String transcript, boolean finalRound) {
        ObjectNode root = json.createObjectNode();
        root.put("question", question);
        root.put("default_period", defaultPeriod == null ? "latest" : defaultPeriod);
        if (finalRound) {
            root.put("instruction", "This is your last turn. Do NOT request another tool. Reply with "
                    + "{\"answer\":\"...\"} using only what the tool results above already contain. If "
                    + "they do not answer the question, say plainly that the data available cannot "
                    + "answer it — that is a valid and useful answer.");
        }

        ArrayNode ms = root.putArray("metrics");
        for (MetricDefinition d : catalog.all()) {
            ObjectNode n = ms.addObject();
            n.put("id", d.id());
            n.put("label", d.label());
            n.put("dimensions", String.join(", ", d.sliceableGrains()));
        }
        if (!transcript.isBlank()) {
            root.put("tool_results_so_far", transcript);
        }
        return root.toPrettyString();
    }

    // ---- helpers ---------------------------------------------------------------------------------

    private static String text(JsonNode args, String field) {
        if (args == null || !args.hasNonNull(field)) {
            return null;
        }
        String value = args.path(field).asText("").trim();
        return value.isEmpty() ? null : value;
    }

    private JsonNode readJson(String raw) {
        String extracted = ClaudeClient.extractJsonObject(raw);
        if (extracted == null || extracted.isBlank()) {
            return null;
        }
        try {
            return json.readTree(extracted);
        } catch (Exception e) {
            return null;
        }
    }

    /** Rough token count for the ledger. The providers report real usage; this covers the gap. */
    private static long estimateTokens(String text) {
        return text == null ? 0L : Math.max(1L, text.length() / 4L);
    }

    /** Enough of a response to diagnose a formatting problem, not enough to flood the log. */
    private static String abbreviate(String text) {
        String flat = text.replaceAll("\\s+", " ").trim();
        return flat.length() <= 300 ? flat : flat.substring(0, 300) + "…";
    }
}
