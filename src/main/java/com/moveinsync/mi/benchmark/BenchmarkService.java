package com.moveinsync.mi.benchmark;

import com.moveinsync.mi.anomaly.RobustStats;
import com.moveinsync.mi.incident.MetricRecheckPort;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.metrics.spi.ObservationPort;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import com.moveinsync.mi.policy.SlaPolicy;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * The benchmark engine: turns a number into an interpretable one by attaching all four reference
 * frames.
 *
 * <p>92.46% means nothing on its own. Against last month's 95.31% it is a 2.85-point drop. Against
 * the 95% contractual target it is a breach. Against the other business units in the same month it
 * is mid-pack. Against the 93% industry benchmark it is roughly par. Those four readings support
 * four different decisions, and a platform that reports the number without them has moved the
 * interpretation problem onto the reader — which is the gap this system exists to close.
 *
 * <h2>Present or explicitly unavailable, never silently absent</h2>
 *
 * <p>Every frame is always constructed. A metric with no configured target gets
 * {@link Sla#notApplicable()}, not a missing field; a global aggregate with no siblings gets
 * {@link Peer#none()}; a series too short to score gets a {@link Trend} with a real prior and delta
 * but a null z. The distinction between "compared and fine" and "could not compare" is exactly the
 * distinction that matters when a human is deciding whether to trust the finding, and JSON that
 * simply omits a key destroys it.
 *
 * <h2>Robust statistics, and the fallback when the series is too short</h2>
 *
 * <p>Z-scores use median and MAD rather than mean and standard deviation, because this data is full
 * of outliers that would inflate a standard deviation until nothing looked anomalous —
 * {@code delay_minutes} reaches 10,644, and distance goes negative. But robustness does not create
 * history: three monthly extracts yield two period-over-period deltas, and no dispersion estimate
 * survives that. Rather than reporting a fabricated z or silently reporting none, this engine falls
 * back to a <em>cross-sectional</em> comparison — scoring an entity's delta against the distribution
 * of its siblings' deltas in the same period — and records which basis it used in the observation's
 * caveats. That fallback is what makes the June story computable: LOGIN fell 5.17 points while
 * LOGOUT fell 0.77, and against the spread of sibling deltas that gap is unmistakable even with no
 * usable time series at all.
 */
@Service
public class BenchmarkService implements ObservationPort, MetricRecheckPort {

    private static final Logger log = LoggerFactory.getLogger(BenchmarkService.class);

    /** Periods pulled when scoring a trend. Generous; the fact store currently holds three. */
    public static final int HISTORY_LOOKBACK = 12;

    /**
     * Period-over-period deltas required before a temporal z-score is trusted.
     *
     * <p>Three deltas means four periods. Below that a MAD is a coin flip: with two points it is
     * simply half their difference, and any third observation scores as either 0 or huge.
     */
    public static final int MIN_TEMPORAL_DELTAS = 3;

    /** Sibling deltas required before the cross-sectional fallback is trusted. */
    public static final int MIN_COHORT_FOR_Z = 5;

    /**
     * Cohort members required before a peer frame is reported at all.
     *
     * <p>Two, not three. A z-score needs a distribution, but a rank and a median do not: on
     * {@code trip_direction} there are exactly two members, and "LOGIN is 2 of 2, below a cohort
     * median it sits 4.4 points under" is precisely the comparison that makes the June story
     * legible. Only a cohort of one — the entity compared against itself — is meaningless.
     */
    public static final int MIN_COHORT_FOR_PEER = 2;

    /** |z| at which the trend component of severity saturates. */
    private static final double Z_SATURATION = 3.0;

    /**
     * Weight applied to a movement in the favourable direction.
     *
     * <p>Not zero. No-show rate fell from 9.44% to 5.81% over the quarter, which is a large, real
     * movement worth understanding — possibly a policy that worked and should be copied. But a good
     * surprise does not compete for attention with a breach, so it enters severity at roughly a
     * third weight.
     */
    private static final double FAVOURABLE_WEIGHT = 0.35;

    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final SlaPolicy slaPolicy;
    private final Environment environment;

    public BenchmarkService(
            MetricCatalog catalog,
            MetricQueryService metrics,
            SlaPolicy slaPolicy,
            Environment environment) {
        this.catalog = catalog;
        this.metrics = metrics;
        this.slaPolicy = slaPolicy;
        this.environment = environment;
    }

    /**
     * Checks at boot that every declared reference key actually resolves.
     *
     * <p>A metric declaring {@code sla_key: sla.ota} that the policy engine has no rule for would
     * report "no target applies" forever — an unarmed SLA that looks identical to a metric which
     * legitimately has none. Same for a benchmark key with no property behind it. Both are warned
     * about once, loudly, at startup rather than discovered when an incident fails to escalate.
     */
    @PostConstruct
    void verifyReferenceWiring() {
        for (MetricDefinition definition : catalog.all()) {
            if (definition.slaKey() != null && slaPolicy.ruleFor(definition.id()).isEmpty()) {
                log.warn("Metric '{}' declares sla_key '{}' but SlaPolicy has no rule for that metric id. "
                                + "Its SLA frame will report NOT APPLICABLE and no breach will ever fire.",
                        definition.id(), definition.slaKey());
            }
            if (definition.industryKey() != null && industryBenchmark(definition).isEmpty()) {
                log.warn("Metric '{}' declares industry_key '{}' but property '{}' is not set. "
                                + "Its industry frame will report as unavailable.",
                        definition.id(), definition.industryKey(), definition.industryPropertyKey());
            }
        }
    }

    // ---- ObservationPort ------------------------------------------------------------------------

    @Override
    public MetricObservation observe(
            String metricId,
            String grain,
            String entity,
            String period,
            Double value,
            long sampleSize,
            double coverage) {

        Optional<MetricDefinition> maybe = catalog.find(metricId);
        String resolvedGrain = MetricDefinition.isGlobal(grain) ? MetricSpec.GLOBAL : grain;
        String resolvedEntity = entity == null ? MetricSpec.ALL : entity;

        if (maybe.isEmpty()) {
            // An unknown metric still gets a well-formed observation. Downstream must never have to
            // null-check References, and a missing catalog entry is a wiring bug to be seen, not a
            // reason to hand back something structurally different.
            log.warn("Observation requested for unknown metric '{}'; emitting an unreferenced observation.", metricId);
            return new MetricObservation(metricId, resolvedGrain, resolvedEntity, period, value, sampleSize,
                    References.empty(), 0.0, Quality.unknown());
        }

        MetricDefinition definition = maybe.get();
        Double usable = (value != null && Double.isFinite(value)) ? value : null;

        TrendResult trend = trend(definition, resolvedGrain, resolvedEntity, period, usable);
        Sla sla = sla(definition, usable);
        Peer peer = peer(definition, resolvedGrain, resolvedEntity, period, usable);
        Industry industry = industry(definition);
        double severity = severity(definition, usable, trend.trend(), sla);

        Quality quality = metrics.qualityFor(metricId, usable, sampleSize, coverage);
        if (trend.caveat() != null) {
            List<String> caveats = new ArrayList<>(quality.caveats());
            caveats.add(trend.caveat());
            quality = new Quality(quality.coverage(), quality.confidence(), caveats);
        }

        return new MetricObservation(
                metricId,
                resolvedGrain,
                resolvedEntity,
                period,
                usable,
                sampleSize,
                new References(trend.trend(), sla, peer, industry),
                severity,
                quality);
    }

    /**
     * Measures and contextualises in one call — the convenience entry point for the agent tool
     * surface, the chat endpoint and the console.
     *
     * @param metricId  stable metric identifier
     * @param grain     logical dimension, or {@code global}
     * @param entity    dimension member, or {@code ALL}
     * @param period    period label, e.g. {@code 2026-06}
     * @return a fully referenced observation; the value is null when the volume gate suppressed it
     */
    public MetricObservation observe(String metricId, String grain, String entity, String period) {
        MetricSlice slice = metrics.measure(metricId, grain, entity, period);
        return observe(metricId, grain, slice.entity(), period, slice.value(), slice.sampleSize(), slice.coverage());
    }

    /** Every entity on one dimension, each fully contextualised. Powers the vendor scorecard view. */
    public List<MetricObservation> observeAll(String metricId, String grain, String period) {
        return metrics.slices(metricId, grain, period).stream()
                .map(slice -> observe(metricId, grain, slice.entity(), period,
                        slice.value(), slice.sampleSize(), slice.coverage()))
                .toList();
    }

    // ---- MetricRecheckPort ----------------------------------------------------------------------

    /**
     * Re-measures a metric so the follow-up loop can ask "did it recover?".
     *
     * <p>Returns empty when the metric cannot be computed — most importantly when the segment has
     * fallen below its volume gate. A suppressed slice is not a recovered slice, and returning an
     * observation with a null value here would let the scheduler close a follow-up on the strength
     * of a number nobody computed.
     */
    @Override
    public Optional<MetricObservation> recheck(String metricId, String dimension, String entity, String period) {
        String resolvedPeriod = period != null ? period : metrics.latestPeriod(metricId).orElse(null);
        if (resolvedPeriod == null) {
            log.debug("Recheck of {} skipped: no period available", metricId);
            return Optional.empty();
        }
        MetricSlice slice = metrics.measure(metricId, dimension, entity, resolvedPeriod);
        if (!slice.measured()) {
            return Optional.empty();
        }
        return Optional.of(observe(metricId, dimension, slice.entity(), resolvedPeriod,
                slice.value(), slice.sampleSize(), slice.coverage()));
    }

    // ---- frame 1: trend -------------------------------------------------------------------------

    /**
     * Prior value, delta and robust z-score.
     *
     * <p>The prior is measured directly against the preceding period rather than read off the end of
     * the history series, because history omits periods that fell below the volume gate and "the
     * previous month" and "the most recent month I was allowed to measure" are different claims.
     */
    private TrendResult trend(MetricDefinition definition, String grain, String entity, String period, Double value) {
        String priorPeriod = MetricQueryService.previousPeriod(period);
        if (priorPeriod == null) {
            return new TrendResult(Trend.none(), null);
        }

        MetricSlice priorSlice = metrics.measure(definition.id(), grain, entity, priorPeriod);
        Double prior = priorSlice.measured() ? priorSlice.value() : null;
        if (value == null || prior == null) {
            // Half a comparison is still worth reporting: the prior alone tells a reader where the
            // series was, even when the current period is suppressed.
            return new TrendResult(new Trend(prior, null, null), null);
        }

        double delta = value - prior;
        ZScore z = robustZ(definition, grain, entity, period, delta);
        return new TrendResult(new Trend(prior, delta, z.value()), z.caveat());
    }

    /**
     * Robust z-score of a delta: temporal when the series supports it, cross-sectional when it does
     * not, and explicitly unavailable when neither does.
     */
    private ZScore robustZ(MetricDefinition definition, String grain, String entity, String period, double delta) {
        List<Double> series = metrics.history(definition.id(), grain, entity, period, HISTORY_LOOKBACK);
        double[] priorDeltas = deltasOf(series);
        // The last delta in the series is the one being scored; score it against the ones before it.
        if (priorDeltas.length - 1 >= MIN_TEMPORAL_DELTAS) {
            double[] reference = new double[priorDeltas.length - 1];
            System.arraycopy(priorDeltas, 0, reference, 0, reference.length);
            return new ZScore(RobustStats.robustZ(delta, reference), null);
        }

        if (!MetricSpec.GLOBAL.equals(grain)) {
            double[] cohortDeltas = cohortDeltas(definition, grain, period);
            if (cohortDeltas.length >= MIN_COHORT_FOR_Z) {
                double z = RobustStats.robustZ(delta, cohortDeltas);
                return new ZScore(z, ("Robust z computed cross-sectionally against %d sibling %s deltas: only %d "
                        + "usable periods of history exist, which is too few for a temporal MAD.")
                        .formatted(cohortDeltas.length, grain, series.size()));
            }
        }

        return new ZScore(null, ("Robust z unavailable: %d periods of history and no usable peer cohort on '%s'. "
                + "The delta is reported without a significance score rather than with a fabricated one.")
                .formatted(series.size(), grain));
    }

    /** Period-over-period deltas of a series, oldest first. */
    private static double[] deltasOf(List<Double> series) {
        if (series.size() < 2) {
            return new double[0];
        }
        double[] deltas = new double[series.size() - 1];
        for (int i = 1; i < series.size(); i++) {
            deltas[i - 1] = series.get(i) - series.get(i - 1);
        }
        return deltas;
    }

    /** Every sibling entity's delta into this period, for the cross-sectional fallback. */
    private double[] cohortDeltas(MetricDefinition definition, String grain, String period) {
        String priorPeriod = MetricQueryService.previousPeriod(period);
        if (priorPeriod == null) {
            return new double[0];
        }
        Map<String, double[]> current = metrics.series(definition.id(), grain, period);
        Map<String, double[]> prior = metrics.series(definition.id(), grain, priorPeriod);

        List<Double> deltas = new ArrayList<>(current.size());
        for (Map.Entry<String, double[]> entry : current.entrySet()) {
            double[] before = prior.get(entry.getKey());
            if (before != null) {
                deltas.add(entry.getValue()[0] - before[0]);
            }
        }
        return RobustStats.toArray(deltas);
    }

    // ---- frame 2: SLA ---------------------------------------------------------------------------

    /**
     * Contractual target comparison, delegated to {@link SlaPolicy}.
     *
     * <p>Delegated rather than reimplemented so the benchmark engine and the policy engine cannot
     * disagree about whether a number breached — a disagreement that would surface as an incident
     * narrating a breach next to a decision refusing to escalate it.
     */
    private Sla sla(MetricDefinition definition, Double value) {
        if (definition.slaKey() == null) {
            return Sla.notApplicable();
        }
        return slaPolicy.toSla(definition.id(), value);
    }

    // ---- frame 3: peer --------------------------------------------------------------------------

    /**
     * Cohort comparison against sibling entities on the same dimension in the same period.
     *
     * <p>This is the frame that separates "this vendor got worse" from "the whole fleet got worse",
     * and it is the one most often missing from mobility reporting. A vendor whose OTA fell three
     * points in a month when every vendor fell three points has a demand problem, not a vendor
     * problem, and escalating to them wastes the relationship.
     */
    private Peer peer(MetricDefinition definition, String grain, String entity, String period, Double value) {
        if (MetricSpec.GLOBAL.equals(grain) || MetricSpec.ALL.equals(entity)) {
            return Peer.none();
        }

        Map<String, double[]> cohort = metrics.series(definition.id(), grain, period);
        if (cohort.size() < MIN_COHORT_FOR_PEER) {
            return Peer.none();
        }

        double[] values = RobustStats.toArray(cohort.values().stream().map(v -> v[0]).toList());
        double median = RobustStats.median(values);
        if (!Double.isFinite(median)) {
            return Peer.none();
        }
        if (value == null) {
            // The cohort is still informative even when this entity's own value was suppressed.
            return new Peer(median, null, null);
        }

        // Rank 1 is best, which depends on the metric's direction: highest OTA wins, lowest cost wins.
        Comparator<Map.Entry<String, double[]>> byValue =
                Comparator.comparingDouble(e -> e.getValue()[0]);
        List<String> ranked = cohort.entrySet().stream()
                .sorted(definition.higherIsBetter() ? byValue.reversed() : byValue)
                .map(Map.Entry::getKey)
                .toList();

        int position = ranked.indexOf(entity) + 1;
        int size = ranked.size();
        if (position == 0) {
            return new Peer(median, null, null);
        }
        // Best of N is the 100th percentile, worst is the 0th.
        double percentile = size == 1 ? 100.0 : (double) (size - position) / (size - 1) * 100.0;
        return new Peer(median, position + " of " + size, percentile);
    }

    // ---- frame 4: industry ----------------------------------------------------------------------

    /**
     * External benchmark, resolved from {@code app.industry.*}.
     *
     * <p>Only two metrics have a defensible published benchmark here (OTA at 93%, no-show at 6%).
     * The rest report {@link Industry#none()}. Inventing a plausible-looking benchmark for the
     * others would be the single easiest way to make this system dishonest, since nobody downstream
     * can tell a configured constant from a researched one.
     */
    private Industry industry(MetricDefinition definition) {
        return industryBenchmark(definition)
                .map(benchmark -> new Industry(benchmark, "config:" + definition.industryPropertyKey()))
                .orElseGet(Industry::none);
    }

    private Optional<Double> industryBenchmark(MetricDefinition definition) {
        String key = definition.industryPropertyKey();
        if (key == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(environment.getProperty(key, Double.class));
    }

    // ---- severity -------------------------------------------------------------------------------

    /**
     * Normalised 0.0-1.0 urgency, blending statistical surprise with contractual consequence.
     *
     * <p>The two are combined as a noisy-OR, {@code 1 - (1 - trend)(1 - sla)}, so either one alone
     * can raise severity and both together compound without ever exceeding 1. A metric that moved
     * sharply but breaches nothing still deserves attention; so does a standing breach that did not
     * move this month. Multiplying them would have zeroed out both cases.
     *
     * <p>The SLA component saturates at {@link SlaPolicy#CRITICAL_THRESHOLD}, reusing the policy
     * engine's own calibration: June's 92.46% OTA is a 2.67% relative gap and scores 0.53, while
     * July's 94.69% is a 0.33% gap and scores 0.07. That is the intended discrimination — June is
     * the month worth waking someone for.
     *
     * @param value the observed value; a null value always scores 0, because an unmeasurable metric
     *              is not an urgent one
     */
    public double severity(MetricDefinition definition, Double value, Trend trend, Sla sla) {
        if (value == null || !Double.isFinite(value)) {
            return 0.0;
        }

        double trendScore = 0.0;
        if (trend != null && trend.robustZ() != null && Double.isFinite(trend.robustZ())) {
            double magnitude = Math.clamp(Math.abs(trend.robustZ()) / Z_SATURATION, 0.0, 1.0);
            boolean adverse = trend.delta() != null && definition.isAdverse(trend.delta());
            trendScore = adverse ? magnitude : magnitude * FAVOURABLE_WEIGHT;
        }

        double slaScore = 0.0;
        // An advisory SLA is reported but never scored. escort_compliance carries a 100% target
        // against a denominator that over-counts, so scoring it would pin the metric at CRITICAL in
        // every period and drown the findings that actually moved.
        if (!definition.slaAdvisory() && sla != null && sla.breached() && sla.target() != null) {
            double relativeGap = slaPolicy.ruleFor(definition.id())
                    .map(rule -> slaPolicy.relativeGap(rule, value))
                    .orElse(0.0);
            slaScore = Math.clamp(relativeGap / SlaPolicy.CRITICAL_THRESHOLD, 0.0, 1.0);
        }

        return Math.clamp(1.0 - (1.0 - trendScore) * (1.0 - slaScore), 0.0, 1.0);
    }

    /** A trend plus the note explaining how — or whether — its z-score was derived. */
    private record TrendResult(Trend trend, String caveat) {
    }

    /** A nullable z-score plus the caveat describing its basis. */
    private record ZScore(Double value, String caveat) {
    }
}
