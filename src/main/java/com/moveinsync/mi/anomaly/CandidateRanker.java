package com.moveinsync.mi.anomaly;

import com.moveinsync.mi.config.RankingProperties;
import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * Decides which detected movements deserve a human, and in what order.
 *
 * <p>The scanner is deliberately generous — it emits everything statistically unusual across every
 * metric and dimension. That set is far too large to act on, and passing it to an LLM would be both
 * expensive and useless. This is the funnel: a deterministic score that reduces a broad sweep to a
 * short, ordered list.
 *
 * <pre>
 *   score = severity x confidence x actionability x persistence x (1 - suppression)
 * </pre>
 *
 * <p>The terms are multiplicative rather than additive, and that is the important design choice. A
 * sum lets one large term carry a finding that is worthless on another axis — a huge, statistically
 * certain movement on a dimension nobody can act on would still rank highly. A product means any term
 * near zero vetoes the finding outright, which is the behaviour actually wanted: an unactionable
 * finding is noise no matter how severe, and a suppressed one is noise no matter how novel.
 *
 * <p>{@code actionability} is the term most systems omit and the one that keeps this from becoming an
 * alert firehose. It carries no statistical information at all; it encodes whether a movement has an
 * owner and a lever. See {@link RankingProperties#getActionability()}.
 */
@Service
public class CandidateRanker {

    private static final Logger log = LoggerFactory.getLogger(CandidateRanker.class);

    private static final double EPSILON = 1e-12;

    /** Below this a finding is treated as vetoed and dropped rather than ranked last. */
    private static final double SCORE_FLOOR = 1e-6;

    private final MetricCatalogPort catalog;
    private final RankingProperties properties;

    public CandidateRanker(MetricCatalogPort catalog, RankingProperties properties) {
        this.catalog = catalog;
        this.properties = properties;
    }

    /**
     * Scores and ranks findings with no memory: every series is treated as newly observed.
     *
     * @param findings raw scanner output
     * @return the top-N scored findings, highest score first
     */
    public List<Finding> rank(List<Finding> findings) {
        return rank(findings, RankingContext.empty(), properties.getTopN());
    }

    /**
     * Scores and ranks findings against operator feedback and prior-period history.
     *
     * @param findings raw scanner output
     * @param context  suppressions and consecutive-period counts from agent memory
     * @return the top-N scored findings, highest score first
     */
    public List<Finding> rank(List<Finding> findings, RankingContext context) {
        return rank(findings, context, properties.getTopN());
    }

    /**
     * Scores and ranks findings, returning at most {@code topN}.
     *
     * <p>Returns rebuilt {@link Finding} records carrying their computed score; the inputs are not
     * mutated, so a caller can re-rank the same sweep under different contexts — which is exactly
     * what the console does when an operator dismisses something.
     *
     * @param findings raw scanner output; may be null or empty
     * @param context  suppressions and consecutive-period counts
     * @param topN     maximum findings to return
     * @return scored findings, highest score first; never null
     */
    public List<Finding> rank(List<Finding> findings, RankingContext context, int topN) {
        if (findings == null || findings.isEmpty()) {
            return List.of();
        }
        RankingContext ctx = context == null ? RankingContext.empty() : context;

        List<Finding> scored = new ArrayList<>(findings.size());
        for (Finding finding : findings) {
            double score = score(finding, ctx);
            if (score <= SCORE_FLOOR) {
                continue;
            }
            scored.add(withScore(finding, score));
        }

        scored.sort(Comparator
                .comparingDouble((Finding f) -> -f.score())
                // Ties broken by magnitude then by id, so repeated runs on unchanged data produce an
                // identical ordering. The triage agent's idempotency depends on that stability.
                .thenComparingDouble(f -> -Math.abs(f.deltaPts()))
                .thenComparing(Finding::id));

        int limit = Math.min(Math.max(1, topN), scored.size());
        List<Finding> top = List.copyOf(scored.subList(0, limit));
        log.info("Ranked {} findings, {} scored above floor, returning top {}",
                findings.size(), scored.size(), top.size());
        return top;
    }

    /**
     * Computes the composite score for a single finding.
     *
     * @param finding the finding to score
     * @param context suppressions and consecutive-period counts
     * @return score in {@code [0, 1]}
     */
    public double score(Finding finding, RankingContext context) {
        double severity = severity(finding);
        double confidence = confidence(finding);
        double actionability = properties.actionabilityFor(finding.dimension());
        double persistence = persistence(finding, context);
        double suppression = context.suppressionFor(finding);

        double score = severity * confidence * actionability * persistence * (1.0 - suppression);

        if (log.isTraceEnabled()) {
            log.trace("Score {}: severity={} confidence={} actionability={} persistence={} suppression={} -> {}",
                    finding.id(), severity, confidence, actionability, persistence, suppression, score);
        }
        return Double.isFinite(score) ? Math.clamp(score, 0.0, 1.0) : 0.0;
    }

    /**
     * Severity, taken from the benchmark engine where available.
     *
     * <p>Falls back to a robust-z-derived value when the observation is missing or carries no
     * severity, so a finding is never silently zeroed out by an upstream gap. The fallback saturates
     * at a z of 5: beyond that the movement is unambiguously anomalous and further magnitude adds no
     * decision-relevant information.
     */
    private double severity(Finding finding) {
        MetricObservation observation = finding.observation();
        if (observation != null && Double.isFinite(observation.severity()) && observation.severity() > 0.0) {
            return Math.clamp(observation.severity(), 0.0, 1.0);
        }
        double magnitude = Math.min(Math.abs(finding.robustZ()) / 5.0, 1.0);
        // An adverse movement of equal magnitude matters more than a favourable one, but a favourable
        // movement is not free of interest: a metric that improves impossibly fast is usually an
        // instrumentation change, which is worth surfacing.
        boolean adverse = catalog.find(finding.metricId())
                .map(spec -> spec.isAdverse(finding.current() - finding.prior()))
                .orElse(true);
        return adverse ? magnitude : magnitude * 0.5;
    }

    /**
     * Confidence, driven by sample size on a log scale and discounted by data coverage.
     *
     * <p>Log scaling matches how trust in a rate actually behaves: the jump from 50 to 500 trips is
     * decisive, the jump from 5,000 to 50,000 is not. Capping at
     * {@link RankingProperties#getConfidenceSaturation()} stops the highest-volume segments from
     * dominating the ranking purely by being large, which would bury a severe problem in a smaller
     * but perfectly well-sampled office.
     */
    private double confidence(Finding finding) {
        long sampleSize = Math.max(0L, finding.sampleSize());
        double saturation = properties.getConfidenceSaturation();
        double sampleFactor = sampleSize == 0
                ? 0.0
                : Math.clamp(Math.log1p(sampleSize) / Math.log1p(saturation), 0.0, 1.0);

        double coverage = Optional.ofNullable(finding.observation())
                .map(MetricObservation::quality)
                .map(q -> Double.isFinite(q.coverage()) ? Math.clamp(q.coverage(), 0.0, 1.0) : 1.0)
                .orElse(1.0);

        double floor = properties.getCoverageFloor();
        return sampleFactor * (floor + (1.0 - floor) * coverage);
    }

    /**
     * Persistence: how established the problem is.
     *
     * <p>Prefers an explicit count from agent memory. Without memory — a first run, or a series never
     * seen before — it derives one from the SLA reference: if the metric breaches its target now and
     * the prior value also breached, the problem has run at least two periods. That derivation is
     * cheap and correct, and it means persistence still discriminates on a cold start instead of
     * flattening to a constant and silently dropping out of the score.
     */
    private double persistence(Finding finding, RankingContext context) {
        Integer known = context.consecutiveFor(finding);
        int consecutive = known != null ? Math.max(1, known) : derivedConsecutive(finding);
        double value = properties.getPersistenceBase() + properties.getPersistenceStep() * (consecutive - 1);
        return Math.clamp(value, 0.0, 1.0);
    }

    /**
     * Infers consecutive adverse periods from the SLA frame: 2 when both the current and prior values
     * breach the target, 1 otherwise.
     */
    private int derivedConsecutive(Finding finding) {
        References references = Optional.ofNullable(finding.observation())
                .map(MetricObservation::references)
                .orElse(null);
        if (references == null) {
            return 1;
        }
        Sla sla = references.sla();
        Trend trend = references.trend();
        if (sla == null || !sla.breached() || sla.target() == null || trend == null || trend.prior() == null) {
            return 1;
        }

        Optional<MetricSpec> spec = catalog.find(finding.metricId());
        if (spec.isEmpty()) {
            return 1;
        }
        double target = sla.target();
        double prior = trend.prior();
        boolean priorBreached = MetricSpec.HIGHER_IS_BETTER.equals(spec.get().direction())
                ? prior < target - EPSILON
                : prior > target + EPSILON;
        return priorBreached ? 2 : 1;
    }

    private static Finding withScore(Finding finding, double score) {
        return new Finding(
                finding.id(),
                finding.metricId(),
                finding.dimension(),
                finding.entity(),
                finding.period(),
                finding.priorPeriod(),
                finding.current(),
                finding.prior(),
                finding.deltaPts(),
                finding.sampleSize(),
                finding.robustZ(),
                score,
                finding.observation(),
                finding.contributions());
    }
}
