package com.moveinsync.mi.pipeline.fallback;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.spi.ChatPort;
import com.moveinsync.mi.pipeline.spi.UsageLedger;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Routes a natural-language question onto a metric-layer call using keyword resolution rather than a
 * model.
 *
 * <p>The contract this satisfies is the interesting part. A chat endpoint is where an analytics
 * platform most easily becomes dishonest: the fluent thing to do with an unmappable question is to
 * answer it anyway. This implementation cannot, because it has no text generator — it resolves the
 * question to a metric id, a dimension, an entity and a period, asks the metric layer for the number,
 * and renders the answer from the returned {@link MetricObservation}. Every figure in the reply is
 * therefore the same figure the dashboard shows, by construction rather than by discipline.
 *
 * <p>When it cannot find a metric in the question it declines with
 * {@link ChatPort#DECLINE_REASON}. That is the correct outcome, not a degraded one: the alternative
 * is to pick the nearest catalog entry and answer a question nobody asked.
 *
 * <p>Entity resolution is done against the data, not against a hard-coded list. Candidate entity
 * names are read from the metric layer for the metric's own grains in the requested period, so
 * "Denver", "LOGIN", "MANUAL" and a vendor id all resolve without anyone enumerating them — and a
 * name that no longer appears in the data stops resolving, which is the behaviour you want.
 *
 * <p>Not a Spring bean; {@code PortRegistry} constructs it so it can never compete for injection
 * with an LLM-backed {@link ChatPort}.
 */
public final class BuiltInChatRouter implements ChatPort {

    private static final Logger log = LoggerFactory.getLogger(BuiltInChatRouter.class);

    /** Tier label recorded in the audit trail. */
    public static final String TIER = "deterministic";

    /** Metric-layer operation names reported on {@link ResolvedCall#tool()}. */
    public static final String TOOL_OBSERVE = "observe";
    public static final String TOOL_ATTRIBUTE = "attribute";

    private static final Pattern PERIOD_LABEL = Pattern.compile("\\b(20\\d{2})[-/](0[1-9]|1[0-2])\\b");
    private static final Pattern YEAR = Pattern.compile("\\b(20\\d{2})\\b");

    /** Words that turn "what is X" into "why did X move" and switch the tool to attribution. */
    private static final List<String> ATTRIBUTION_WORDS =
            List.of("why", "cause", "caused", "driver", "drove", "explain", "attribut", "blame",
                    "responsible", "reason", "breakdown", "decompos");

    /**
     * Question words that alone carry no metric. Present so that a question consisting only of these
     * declines rather than accidentally matching a metric label through a stray substring.
     */
    private static final int MIN_TOKEN_LENGTH = 3;

    private static final Map<String, String> MONTHS = months();

    /**
     * Hand-written synonyms, checked after catalog ids and labels.
     *
     * <p>Kept small and explicit. Each entry exists because it is what an operator actually types:
     * nobody asks about {@code noshow_rate}, they ask about no-shows.
     */
    private static final Map<String, String> SYNONYMS = synonyms();

    /**
     * Words that mean "rank these and tell me the extreme one" rather than "give me a number".
     * "Which office had the worst OTA" is a different question from "what was OTA", and answering
     * the second when asked the first is worse than declining — it looks like an answer.
     */
    private static final List<String> SUPERLATIVES =
            List.of("worst", "best", "highest", "lowest", "top ", "bottom", "most", "least",
                    "which ", "who ", "rank", "compare");

    /** Natural phrasing to the grain it means, longest first so "business unit" beats "unit". */
    private static final Map<String, String> DIMENSION_WORDS = dimensionWords();

    /**
     * Plain-English names for grains. A transport manager does not think in column names, and
     * "trip_direction" on screen is a tell that nobody translated the schema into English.
     */
    private static final Map<String, String> DIMENSION_LABELS = Map.of(
            "trip_direction", "the morning/evening split",
            "product_type", "the type of vehicle",
            "route_source", "how the route was planned",
            "business_unit", "business unit",
            "shift_type", "shift",
            "trip_nodal", "pickup type",
            "slab_name", "billing slab",
            "office", "office",
            "vendor", "vendor",
            "contract", "contract");

    /** Codes that appear in the data but mean nothing to a reader without a gloss. */
    private static final Map<String, String> ENTITY_GLOSS = Map.of(
            "LOGIN", "morning pickups",
            "LOGOUT", "evening drop-offs",
            "BUS", "buses",
            "CAB", "cabs",
            "MANUAL", "hand-planned routes",
            "AUTO", "system-planned routes",
            "NODAL", "nodal-point pickups",
            "HOME", "home pickups",
            "SHUTTLE", "shuttle trips",
            "SPOT_2.0", "spot-booked trips");

    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final BenchmarkService benchmarks;
    private final AttributionService attribution;
    private final MetricFormat format;

    public BuiltInChatRouter(
            MetricCatalog catalog,
            MetricQueryService metrics,
            BenchmarkService benchmarks,
            AttributionService attribution,
            MetricFormat format) {
        this.catalog = catalog;
        this.metrics = metrics;
        this.benchmarks = benchmarks;
        this.attribution = attribution;
        this.format = format;
    }

    @Override
    public Answer ask(String question, String defaultPeriod) {
        if (question == null || question.isBlank()) {
            return Answer.decline("", catalog.ids());
        }
        String normalised = question.toLowerCase(Locale.ROOT);

        String metricId = resolveMetric(normalised);
        if (metricId == null) {
            log.info("Declining chat question: no catalog metric resolved from '{}'", question);
            return Answer.decline(question, catalog.ids());
        }

        String period = resolvePeriod(normalised, defaultPeriod, metricId);
        if (period == null) {
            return new Answer(
                    "I can compute `" + metricId + "` but the fact store holds no periods for it yet, so "
                            + "there is nothing to report. Run ingest first.",
                    new ResolvedCall(TOOL_OBSERVE, metricId, MetricSpec.GLOBAL, MetricSpec.ALL, "n/a"),
                    List.of(),
                    UsageLedger.Usage.ZERO,
                    false);
        }

        boolean wantsAttribution = ATTRIBUTION_WORDS.stream().anyMatch(normalised::contains);
        Slice slice = resolveEntity(metricId, period, normalised);

        // "Which office had the worst OTA" asks for a ranking, not a number. Returning the global
        // figure would look like an answer while silently ignoring both "office" and "worst", so
        // this is checked before the plain observation path — but only when no specific entity was
        // named, since "OTA for Denver Office" is a lookup even if it contains a ranking word.
        if (MetricSpec.GLOBAL.equals(slice.dimension()) && !wantsAttribution) {
            String rankGrain = resolveRankedDimension(metricId, normalised);
            if (rankGrain != null) {
                return rankingAnswer(metricId, period, rankGrain, normalised);
            }
        }

        return wantsAttribution
                ? attributionAnswer(metricId, period, slice)
                : observationAnswer(metricId, period, slice);
    }

    /**
     * Returns the grain to rank by when the question is a superlative about a dimension, else null.
     * Both halves must be present: "worst" alone has nothing to rank, and "office" alone is a filter
     * rather than a ranking request.
     */
    private String resolveRankedDimension(String metricId, String normalisedQuestion) {
        boolean superlative = SUPERLATIVES.stream().anyMatch(normalisedQuestion::contains);
        if (!superlative) {
            return null;
        }
        List<String> grains = catalog.find(metricId)
                .map(MetricDefinition::sliceableGrains)
                .orElse(List.of());

        for (Map.Entry<String, String> entry : DIMENSION_WORDS.entrySet()) {
            if (normalisedQuestion.contains(entry.getKey()) && grains.contains(entry.getValue())) {
                return entry.getValue();
            }
        }
        return null;
    }

    /**
     * Ranks every entity in a grain and reports the extreme one the question asked for, plus enough
     * of the tail to make it interpretable. Direction-aware: "worst" means the lowest on-time rate
     * but the highest cost, which is exactly why direction is declared in the catalog.
     */
    private Answer rankingAnswer(String metricId, String period, String grain, String normalisedQuestion) {
        boolean wantsBest = normalisedQuestion.contains("best")
                || normalisedQuestion.contains("highest")
                || normalisedQuestion.contains("most");
        boolean higherIsBetter = catalog.find(metricId)
                .map(MetricDefinition::higherIsBetter)
                .orElse(true);
        // "worst" on a higher-is-better metric means ascending; on cost it means descending.
        boolean ascending = wantsBest != higherIsBetter;

        List<MetricSlice> ranked;
        try {
            ranked = metrics.slices(metricId, grain, period).stream()
                    .filter(MetricSlice::measured)
                    .sorted(ascending
                            ? Comparator.comparingDouble(MetricSlice::value)
                            : Comparator.comparingDouble((MetricSlice s) -> s.value()).reversed())
                    .toList();
        } catch (RuntimeException e) {
            log.warn("Ranking failed for {} by {}: {}", metricId, grain, e.toString());
            return observationAnswer(metricId, period, Slice.global());
        }

        if (ranked.isEmpty()) {
            return observationAnswer(metricId, period, Slice.global());
        }

        MetricSlice leader = ranked.getFirst();
        String label = format.label(metricId);
        String dimensionLabel = DIMENSION_LABELS.getOrDefault(grain, grain.replace('_', ' '));
        List<Evidence> citations = new ArrayList<>();
        StringBuilder answer = new StringBuilder(512);

        String headline = "%s had the %s %s in %s, at %s across %,d trips.".formatted(
                glossed(leader.entity()),
                wantsBest ? "best" : "worst",
                label.toLowerCase(Locale.ROOT),
                friendlyPeriod(period),
                format.value(metricId, leader.value()),
                leader.sampleSize());
        answer.append(headline).append(' ');
        citations.add(new Evidence(headline, metricId, leader.entity()));

        if (ranked.size() > 1) {
            MetricSlice other = ranked.get(ranked.size() - 1);
            String spread = "For comparison, %s was %s at %s, and the middle of the %d %ss sits at %s."
                    .formatted(
                            glossed(other.entity()),
                            wantsBest ? "the weakest" : "the strongest",
                            format.value(metricId, other.value()),
                            ranked.size(),
                            dimensionLabel,
                            format.value(metricId, median(ranked)));
            answer.append(spread).append(' ');
            citations.add(new Evidence(spread, metricId, other.entity()));
        }

        if (ranked.size() > 2) {
            String runners = ranked.stream().skip(1).limit(3)
                    .map(s -> glossed(s.entity()) + " " + format.value(metricId, s.value()))
                    .collect(Collectors.joining(", "));
            answer.append("Next after ").append(glossed(leader.entity())).append(": ")
                    .append(runners).append('.');
        }

        return new Answer(
                answer.toString().trim(),
                new ResolvedCall(TOOL_OBSERVE, metricId, grain, leader.entity(), period),
                citations,
                UsageLedger.Usage.ZERO,
                false);
    }

    private static double median(List<MetricSlice> sorted) {
        List<Double> values = sorted.stream()
                .map(MetricSlice::value)
                .sorted()
                .toList();
        int n = values.size();
        return n % 2 == 1 ? values.get(n / 2) : (values.get(n / 2 - 1) + values.get(n / 2)) / 2.0;
    }

    /**
     * The size of a movement without its sign, for sentences where a verb already says the
     * direction. {@code format.effect} always signs its output, which is right in a table and wrong
     * next to the word "fell".
     */
    private String magnitude(String metricId, double value) {
        String formatted = format.effect(metricId, Math.abs(value));
        return formatted.startsWith("+") || formatted.startsWith("-")
                ? formatted.substring(1)
                : formatted;
    }

    /** Adds a plain-English gloss to codes that mean nothing on their own. */
    private static String glossed(String entity) {
        String gloss = entity == null ? null : ENTITY_GLOSS.get(entity);
        return gloss == null ? entity : entity + " (" + gloss + ")";
    }

    /** "2026-06" reads as a database key; "June 2026" reads as a month. */
    private static String friendlyPeriod(String period) {
        if (period == null || period.length() != 7 || period.charAt(4) != '-') {
            return String.valueOf(period);
        }
        String[] names = {"January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"};
        try {
            int month = Integer.parseInt(period.substring(5));
            return names[month - 1] + " " + period.substring(0, 4);
        } catch (RuntimeException e) {
            return period;
        }
    }

    @Override
    public String tier() {
        return TIER;
    }

    // ---- observe ----------------------------------------------------------------------------------

    private Answer observationAnswer(String metricId, String period, Slice slice) {
        MetricObservation observation = benchmarks.observe(metricId, slice.dimension(), slice.entity(), period);
        List<Evidence> citations = new ArrayList<>();
        StringBuilder answer = new StringBuilder(512);

        String subject = describeSubject(metricId, slice);

        if (observation.value() == null) {
            String claim = ("%s in %s could not be measured: %,d rows matched, which is below the "
                    + "minimum sample for this metric. That is not a zero and must not be read as one.")
                    .formatted(subject, period, observation.sampleSize());
            answer.append(claim);
            citations.add(new Evidence(claim, metricId, slice.entity()));
            appendQuality(answer, observation);
            return new Answer(answer.toString().trim(),
                    new ResolvedCall(TOOL_OBSERVE, metricId, slice.dimension(), slice.entity(), period),
                    citations, UsageLedger.Usage.ZERO, false);
        }

        String headline = "%s in %s was %s across %,d trips.".formatted(
                subject, period, format.value(metricId, observation.value()), observation.sampleSize());
        answer.append(headline).append(' ');
        citations.add(new Evidence(headline, metricId, slice.entity()));

        References references = observation.references();
        if (references != null) {
            appendTrend(answer, citations, metricId, slice, period, references.trend());
            appendSla(answer, citations, metricId, slice, references.sla());
            appendPeer(answer, citations, metricId, slice, references.peer());
            appendIndustry(answer, citations, metricId, slice, references.industry());
        }
        appendQuality(answer, observation);

        return new Answer(
                answer.toString().trim(),
                new ResolvedCall(TOOL_OBSERVE, metricId, slice.dimension(), slice.entity(), period),
                citations,
                UsageLedger.Usage.ZERO,
                false);
    }

    private void appendTrend(
            StringBuilder answer, List<Evidence> citations,
            String metricId, Slice slice, String period, Trend trend) {

        if (trend == null || trend.prior() == null) {
            return;
        }
        String priorPeriod = MetricQueryService.previousPeriod(period);
        String claim = trend.delta() == null
                ? "The prior period (%s) measured %s.".formatted(
                        priorPeriod, format.value(metricId, trend.prior()))
                : "Against %s that is %s, from %s.".formatted(
                        priorPeriod,
                        format.effect(metricId, trend.delta()),
                        format.value(metricId, trend.prior()));
        answer.append(claim).append(' ');
        citations.add(new Evidence(claim, metricId, slice.entity()));

        if (trend.robustZ() != null && Double.isFinite(trend.robustZ())) {
            String zClaim = "That movement scores %.1f robust z against its reference distribution."
                    .formatted(trend.robustZ());
            answer.append(zClaim).append(' ');
            citations.add(new Evidence(zClaim, metricId, slice.entity()));
        }
    }

    private void appendSla(
            StringBuilder answer, List<Evidence> citations, String metricId, Slice slice, Sla sla) {
        if (sla == null || sla.target() == null) {
            return;
        }
        String claim = sla.breached()
                ? "It breaches the configured target of %s.".formatted(format.value(metricId, sla.target()))
                : "It clears the configured target of %s.".formatted(format.value(metricId, sla.target()));
        answer.append(claim).append(' ');
        citations.add(new Evidence(claim, metricId, slice.entity()));
    }

    private void appendPeer(
            StringBuilder answer, List<Evidence> citations, String metricId, Slice slice, Peer peer) {
        if (peer == null || peer.cohortMedian() == null || peer.rank() == null) {
            return;
        }
        String claim = "Against its cohort on %s it ranks %s, with a cohort median of %s.".formatted(
                slice.dimension(), peer.rank(), format.value(metricId, peer.cohortMedian()));
        answer.append(claim).append(' ');
        citations.add(new Evidence(claim, metricId, slice.entity()));
    }

    private void appendIndustry(
            StringBuilder answer, List<Evidence> citations, String metricId, Slice slice, Industry industry) {
        if (industry == null || industry.benchmark() == null) {
            return;
        }
        String claim = "The configured external benchmark is %s%s.".formatted(
                format.value(metricId, industry.benchmark()),
                industry.source() == null ? "" : " (" + industry.source() + ")");
        answer.append(claim).append(' ');
        citations.add(new Evidence(claim, metricId, slice.entity()));
    }

    private void appendQuality(StringBuilder answer, MetricObservation observation) {
        if (observation.quality() == null) {
            return;
        }
        // Full coverage needs no sentence — saying "100.0% coverage" on every answer trains the
        // reader to skip the line, which is exactly when you need them to notice a partial one.
        double coverage = observation.quality().coverage();
        if (coverage >= 0.999) {
            return;
        }
        answer.append("Based on %.0f%% of the underlying records, so treat this as indicative."
                .formatted(coverage * 100.0));
    }

    // ---- attribute --------------------------------------------------------------------------------

    private Answer attributionAnswer(String metricId, String period, Slice slice) {
        String priorPeriod = MetricQueryService.previousPeriod(period);
        AttributionResult result = attribution.attribute(metricId, period, priorPeriod);

        List<Evidence> citations = new ArrayList<>();
        StringBuilder answer = new StringBuilder(768);

        if (result.ranked().isEmpty()) {
            String claim = ("No dimension of %s cleared the volume gate with enough entities to decompose "
                    + "the %s movement, so I will not name a driver. That is a coverage limit, not "
                    + "evidence that the movement is uniform.")
                    .formatted(format.label(metricId), period);
            answer.append(claim);
            citations.add(new Evidence(claim, metricId, MetricSpec.ALL));
            return new Answer(answer.toString(),
                    new ResolvedCall(TOOL_ATTRIBUTE, metricId, MetricSpec.GLOBAL, MetricSpec.ALL, period),
                    citations, UsageLedger.Usage.ZERO, false);
        }

        DimensionAttribution winner = result.ranked().getFirst();

        // Written for a transport manager, not an analyst. The maths is unchanged; the vocabulary is
        // not. "Explanatory power 0.83, concentration 1.00 across 2 entities" is true and useless to
        // the person who has to act on it before the morning shift.
        // The verb already carries the direction, so the number must not repeat it — "fell +2.86"
        // reads as a contradiction and undermines every figure next to it.
        String movement = "%s %s %s between %s and %s.".formatted(
                format.label(metricId),
                result.actualDelta() < 0 ? "fell" : "rose",
                magnitude(metricId, result.actualDelta()),
                friendlyPeriod(priorPeriod),
                friendlyPeriod(period));
        answer.append(movement).append(' ');
        citations.add(new Evidence(movement, metricId, MetricSpec.ALL));

        String dimensionLabel =
                DIMENSION_LABELS.getOrDefault(winner.dimension(), winner.dimension().replace('_', ' '));
        String winnerClaim = ("The change is concentrated rather than spread evenly. Of the %d ways this "
                + "can be broken down, %s explains it best.").formatted(result.ranked().size(), dimensionLabel);
        answer.append(winnerClaim).append(' ');
        citations.add(new Evidence(winnerClaim, metricId, winner.dimension()));

        List<Contribution> top = winner.contributions().stream().limit(3).toList();
        if (!top.isEmpty()) {
            StringBuilder contributors = new StringBuilder();
            for (Contribution contribution : top) {
                if (!contributors.isEmpty()) {
                    contributors.append("; ");
                }
                contributors.append("%s accounts for %s".formatted(
                        glossed(contribution.entity()),
                        format.effect(metricId, contribution.total())));
                citations.add(new Evidence(
                        "%s contributed %s to the movement.".formatted(
                                contribution.entity(), format.effect(metricId, contribution.total())),
                        metricId, contribution.entity()));
            }
            answer.append("Breaking it down: ").append(contributors).append(". ");

            // The rate-vs-mix distinction is the whole point of the decomposition, and it is the one
            // thing a reader cannot infer from the totals. Say it in words, not in column names.
            Contribution lead = top.getFirst();
            double rate = Math.abs(lead.rateEffect());
            double mix = Math.abs(lead.mixEffect());
            if (rate + mix > 0) {
                String cause = rate >= mix
                        ? ("This is a performance change, not a volume change: of %s's %s, %s is the "
                                + "trips themselves getting worse and only %s comes from how many trips "
                                + "it handled. Moving volume around will not fix it.")
                                .formatted(lead.entity(),
                                        format.effect(metricId, lead.total()),
                                        format.effect(metricId, lead.rateEffect()),
                                        format.effect(metricId, lead.mixEffect()))
                        : ("This is mostly a volume shift, not a performance drop: of %s's %s, %s comes "
                                + "from it handling a different share of trips and only %s from the trips "
                                + "themselves changing. Look at how work is being allocated.")
                                .formatted(lead.entity(),
                                        format.effect(metricId, lead.total()),
                                        format.effect(metricId, lead.mixEffect()),
                                        format.effect(metricId, lead.rateEffect()));
                answer.append(cause).append(' ');
                citations.add(new Evidence(cause, metricId, lead.entity()));
            }
        }

        String reconciliation = winner.reconciles(1e-6)
                ? "The parts add up to the whole, so nothing is unaccounted for."
                : ("%s of the movement is unaccounted for — that is volume held back by the "
                        + "minimum-sample gate, not an arithmetic error.")
                        .formatted(format.effect(metricId, winner.reconciliationError()));
        answer.append(reconciliation);
        citations.add(new Evidence(reconciliation, metricId, winner.dimension()));

        return new Answer(
                answer.toString().trim(),
                new ResolvedCall(TOOL_ATTRIBUTE, metricId, winner.dimension(),
                        winner.leader() == null ? MetricSpec.ALL : winner.leader().entity(), period),
                citations,
                UsageLedger.Usage.ZERO,
                false);
    }

    // ---- resolution -------------------------------------------------------------------------------

    /**
     * Finds the catalog metric a question is about.
     *
     * <p>Checked in order of specificity: exact id, id with separators relaxed, the human label, then
     * the synonym table. Returns null rather than a best guess when nothing matches — the caller
     * turns that into a decline.
     */
    String resolveMetric(String normalisedQuestion) {
        for (MetricDefinition definition : catalog.all()) {
            if (normalisedQuestion.contains(definition.id().toLowerCase(Locale.ROOT))) {
                return definition.id();
            }
        }
        for (MetricDefinition definition : catalog.all()) {
            String relaxed = definition.id().replace('_', ' ');
            if (relaxed.length() >= MIN_TOKEN_LENGTH && normalisedQuestion.contains(relaxed)) {
                return definition.id();
            }
            String label = definition.label().toLowerCase(Locale.ROOT);
            if (normalisedQuestion.contains(label)) {
                return definition.id();
            }
        }
        for (Map.Entry<String, String> entry : SYNONYMS.entrySet()) {
            if (normalisedQuestion.contains(entry.getKey()) && catalog.find(entry.getValue()).isPresent()) {
                return entry.getValue();
            }
        }
        return null;
    }

    /**
     * Resolves the period: an explicit {@code yyyy-MM} label, a month name, the caller's default, or
     * the latest period the metric actually has data for.
     */
    String resolvePeriod(String normalisedQuestion, String defaultPeriod, String metricId) {
        Matcher explicit = PERIOD_LABEL.matcher(normalisedQuestion);
        if (explicit.find()) {
            return explicit.group(1) + "-" + explicit.group(2);
        }

        List<String> available = metrics.periods(metricId);
        String fallbackYear = available.isEmpty()
                ? null
                : available.get(available.size() - 1).substring(0, 4);

        for (Map.Entry<String, String> month : MONTHS.entrySet()) {
            if (!normalisedQuestion.contains(month.getKey())) {
                continue;
            }
            Matcher year = YEAR.matcher(normalisedQuestion);
            String resolvedYear = year.find() ? year.group(1) : fallbackYear;
            if (resolvedYear != null) {
                return resolvedYear + "-" + month.getValue();
            }
        }

        if (defaultPeriod != null && !defaultPeriod.isBlank()) {
            return defaultPeriod;
        }
        return available.isEmpty() ? null : available.get(available.size() - 1);
    }

    /**
     * Finds the dimension and entity named in the question, by matching against the entity values the
     * metric layer actually reports for this metric in this period.
     *
     * <p>Longer entity names win, so "Clearwater Campus" is not shadowed by a shorter member whose
     * name is a substring of it. When nothing matches, the global aggregate is the honest default.
     */
    Slice resolveEntity(String metricId, String period, String normalisedQuestion) {
        Optional<MetricDefinition> definition = catalog.find(metricId);
        if (definition.isEmpty()) {
            return Slice.global();
        }

        Slice best = Slice.global();
        int bestLength = 0;
        for (String grain : definition.get().sliceableGrains()) {
            List<MetricSlice> slices;
            try {
                slices = metrics.slices(metricId, grain, period);
            } catch (RuntimeException e) {
                log.debug("Entity resolution skipped grain {} for {}: {}", grain, metricId, e.toString());
                continue;
            }
            for (MetricSlice slice : slices) {
                String entity = slice.entity();
                if (entity == null || entity.length() < MIN_TOKEN_LENGTH) {
                    continue;
                }
                String needle = entity.toLowerCase(Locale.ROOT);
                if (normalisedQuestion.contains(needle) && needle.length() > bestLength) {
                    best = new Slice(grain, entity);
                    bestLength = needle.length();
                }
            }
        }
        return best;
    }

    private String describeSubject(String metricId, Slice slice) {
        if (MetricSpec.GLOBAL.equals(slice.dimension())) {
            return format.label(metricId) + " overall";
        }
        return "%s for %s = %s".formatted(format.label(metricId), slice.dimension(), slice.entity());
    }

    /** A resolved dimension/entity pair. {@link #global()} is the un-sliced aggregate. */
    record Slice(String dimension, String entity) {
        static Slice global() {
            return new Slice(MetricSpec.GLOBAL, MetricSpec.ALL);
        }
    }

    private static Map<String, String> months() {
        Map<String, String> table = new LinkedHashMap<>();
        table.put("january", "01");
        table.put("february", "02");
        table.put("march", "03");
        table.put("april", "04");
        // "may" is also an English modal verb; it is checked last so a question like "may we see June"
        // resolves to June. LinkedHashMap preserves that ordering.
        table.put("june", "06");
        table.put("july", "07");
        table.put("august", "08");
        table.put("september", "09");
        table.put("october", "10");
        table.put("november", "11");
        table.put("december", "12");
        table.put("may", "05");
        // Collections.unmodifiableMap, not Map.copyOf: Map.copyOf does not preserve iteration order,
        // and the ordering above is load-bearing.
        return Collections.unmodifiableMap(table);
    }

    /**
     * How a person names a dimension, mapped to the grain it means. Insertion order matters: the
     * longest phrases are checked first so "business unit" is not shadowed by "unit".
     */
    private static Map<String, String> dimensionWords() {
        Map<String, String> table = new LinkedHashMap<>();
        table.put("business unit", "business_unit");
        table.put("route source", "route_source");
        table.put("product type", "product_type");
        table.put("trip direction", "trip_direction");
        table.put("billing slab", "slab_name");
        table.put("pickup type", "trip_nodal");
        table.put("contract", "contract");
        table.put("offices", "office");
        table.put("office", "office");
        table.put("campus", "office");
        table.put("site", "office");
        table.put("vendors", "vendor");
        table.put("vendor", "vendor");
        table.put("supplier", "vendor");
        table.put("shifts", "shift_type");
        table.put("shift", "shift_type");
        table.put("direction", "trip_direction");
        table.put("slab", "slab_name");
        return Collections.unmodifiableMap(table);
    }

    private static Map<String, String> synonyms() {
        Map<String, String> table = new LinkedHashMap<>();
        table.put("on-time", "ota");
        table.put("on time", "ota");
        table.put("ontime", "ota");
        table.put("punctual", "ota");
        table.put("no-show", "noshow_rate");
        table.put("no show", "noshow_rate");
        table.put("noshow", "noshow_rate");
        table.put("cost per km", "cost_per_km");
        table.put("cost per kilometre", "cost_per_km");
        table.put("cost per kilometer", "cost_per_km");
        table.put("cost per trip", "cost_per_trip");
        table.put("spend", "cost_per_trip");
        table.put("billing", "cost_per_trip");
        table.put("delay", "delay_p90");
        table.put("late", "delay_p90");
        table.put("occupancy", "occupancy");
        table.put("seat", "occupancy");
        table.put("utilisation", "occupancy");
        table.put("utilization", "occupancy");
        table.put("escort", "escort_compliance");
        table.put("marshal", "escort_compliance");
        table.put("driver compliance", "driver_noncompliance");
        table.put("non-compliance", "driver_noncompliance");
        table.put("noncompliance", "driver_noncompliance");
        return Collections.unmodifiableMap(table);
    }
}
