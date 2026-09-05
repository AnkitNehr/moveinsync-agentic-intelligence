package com.moveinsync.mi.anomaly;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSeriesPort;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.metrics.spi.ObservationPort;
import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * The generic detection engine: every metric, every dimension, every period pair.
 *
 * <p>Nothing in this class knows what OTA is, that June was bad, or that bus routes exist. It walks
 * the catalog, slices each metric by each of its declared grains, compares the current period against
 * the prior one, and emits a {@link Finding} wherever the movement is
 * statistically unusual and large enough to matter. The demo narratives are outputs of that sweep,
 * not cases coded into it — which is the whole point, because a system that only finds the
 * degradations someone anticipated is a dashboard with extra steps.
 *
 * <h2>Two z-scores, not one</h2>
 *
 * <p>Three monthly extracts give at most three points per series, and a MAD over three points is
 * close to meaningless. So each movement is scored two ways and the stronger signal wins:
 *
 * <ul>
 *   <li><b>Temporal</b> — the entity's current value against its own history. Only used once the
 *       series has {@code min-history-points}; correct when available and the natural reading of
 *       "unusual".</li>
 *   <li><b>Cross-sectional</b> — the entity's movement against the distribution of movements across
 *       its sibling entities in the same period. Available immediately, and it answers the question
 *       a short history cannot: everything drifted, but did <em>this</em> one drift differently?
 *       LOGIN falling 5.17 points is unremarkable against two months of history and glaring against
 *       LOGOUT's 0.77 in the same month.</li>
 * </ul>
 *
 * <h2>The volume gate</h2>
 *
 * <p>Sorting segments by absolute movement without a volume gate surfaces noise every time. In this
 * data {@code trip_nodal = 'SHUTTLE'} carries 244 trips across the whole quarter and shows a 26.6
 * point swing; {@code product_type = 'SPOT_2.0'} carries 702. Both are arithmetic on a handful of
 * trips. Slices below the gate are skipped before any statistic is computed, rather than being
 * computed and then filtered, so an under-sampled slice can never leak into a cross-sectional
 * distribution and distort the scores of legitimate ones.
 */
@Service
public class AnomalyScanner {

    private static final Logger log = LoggerFactory.getLogger(AnomalyScanner.class);

    private static final double EPSILON = 1e-12;

    private final MetricCatalogPort catalog;
    private final MetricSeriesPort series;
    private final ObservationPort observations;
    private final AttributionService attribution;

    private final long globalMinSample;
    private final double robustZThreshold;
    private final double materialDeltaPts;
    private final double materialRelativeChange;
    private final int historyLookback;
    private final int minHistoryPoints;

    public AnomalyScanner(
            MetricCatalogPort catalog,
            MetricSeriesPort series,
            ObservationPort observations,
            AttributionService attribution,
            @Value("${app.scanner.min-sample:500}") long globalMinSample,
            @Value("${app.scanner.robust-z-threshold:2.0}") double robustZThreshold,
            @Value("${app.scanner.material-delta-pts:1.0}") double materialDeltaPts,
            @Value("${app.scanner.material-relative-change:0.10}") double materialRelativeChange,
            @Value("${app.scanner.history-lookback:12}") int historyLookback,
            @Value("${app.scanner.min-history-points:4}") int minHistoryPoints) {
        this.catalog = catalog;
        this.series = series;
        this.observations = observations;
        this.attribution = attribution;
        this.globalMinSample = Math.max(0L, globalMinSample);
        this.robustZThreshold = robustZThreshold;
        this.materialDeltaPts = materialDeltaPts;
        this.materialRelativeChange = materialRelativeChange;
        this.historyLookback = Math.max(2, historyLookback);
        this.minHistoryPoints = Math.max(2, minHistoryPoints);
    }

    /**
     * Scans the entire catalog for movements between two periods.
     *
     * <p>Findings are returned unscored — {@code score} is left at zero for
     * {@link CandidateRanker} to populate. Detection and prioritisation are separate concerns:
     * mixing them would mean re-running the sweep every time a suppression or an actionability
     * weight changes.
     *
     * @param period      current period label, e.g. {@code 2026-06}
     * @param priorPeriod comparison period label, e.g. {@code 2026-05}
     * @return every significant, volume-gated movement found; unordered, never null
     */
    public List<Finding> scan(String period, String priorPeriod) {
        List<Finding> findings = new ArrayList<>();
        AtomicInteger seriesEvaluated = new AtomicInteger();

        for (MetricSpec spec : catalog.metrics()) {
            AttributionResult attributed = attribution.attribute(spec, period, priorPeriod, spec.grains());
            long minSample = Math.max(globalMinSample, spec.minSample());

            for (String dimension : spec.grains()) {
                try {
                    findings.addAll(scanDimension(
                            spec, dimension, period, priorPeriod, minSample, attributed, seriesEvaluated));
                } catch (RuntimeException e) {
                    // One malformed dimension must not abort the sweep; the remaining metrics still
                    // carry usable signal and a partial scan beats no scan.
                    log.warn("Scan failed for metric {} on dimension {}: {}", spec.id(), dimension, e.toString());
                }
            }
        }

        log.info("Scan {} vs {}: {} series evaluated, {} findings", period, priorPeriod,
                seriesEvaluated.get(), findings.size());
        return findings;
    }

    /**
     * Scans one metric on one dimension in two passes: gate first, then score against the surviving
     * population.
     */
    private List<Finding> scanDimension(
            MetricSpec spec,
            String dimension,
            String period,
            String priorPeriod,
            long minSample,
            AttributionResult attributed,
            AtomicInteger seriesEvaluated) {

        List<MetricSlice> currentSlices = slicesFor(spec.id(), dimension, period);
        List<MetricSlice> priorSlices = slicesFor(spec.id(), dimension, priorPeriod);
        if (currentSlices.isEmpty() || priorSlices.isEmpty()) {
            return List.of();
        }
        Map<String, MetricSlice> prior = index(priorSlices);

        // Pass one: gate, then collect the movements that survive. The cross-sectional reference
        // distribution is built only from gated slices, so noise from tiny segments never becomes
        // the yardstick that legitimate segments are measured against.
        List<Movement> movements = new ArrayList<>();
        for (MetricSlice currentSlice : currentSlices) {
            MetricSlice priorSlice = prior.get(currentSlice.entity());
            if (priorSlice == null) {
                continue;
            }
            seriesEvaluated.incrementAndGet();

            if (currentSlice.sampleSize() < minSample || priorSlice.sampleSize() < minSample) {
                log.trace("Gated {}/{}/{}: sample {}/{} below {}", spec.id(), dimension,
                        currentSlice.entity(), currentSlice.sampleSize(), priorSlice.sampleSize(), minSample);
                continue;
            }
            if (!currentSlice.measured() || !priorSlice.measured()) {
                continue;
            }
            movements.add(new Movement(currentSlice, priorSlice, currentSlice.value() - priorSlice.value()));
        }
        if (movements.isEmpty()) {
            return List.of();
        }

        double[] deltaDistribution = movements.stream().mapToDouble(Movement::delta).toArray();

        // Pass two: score and emit.
        List<Finding> findings = new ArrayList<>();
        for (Movement movement : movements) {
            double robustZ = scoreMovement(spec, dimension, period, movement, deltaDistribution);
            double deltaPts = toPoints(spec, movement.delta());

            if (!significant(spec, movement, deltaPts, robustZ)) {
                continue;
            }
            findings.add(buildFinding(spec, dimension, period, priorPeriod, movement, deltaPts, robustZ, attributed));
        }
        return findings;
    }

    /**
     * Scores a movement, preferring the temporal z-score when the series is long enough and otherwise
     * falling back to the cross-sectional one. When both are available the larger magnitude is taken:
     * a movement that is unusual on either reading deserves a look, and requiring both to agree would
     * suppress exactly the fleet-wide shifts and single-entity breaks the two tests exist to catch.
     */
    private double scoreMovement(
            MetricSpec spec, String dimension, String period, Movement movement, double[] deltaDistribution) {

        double crossSectional = deltaDistribution.length >= 3
                ? RobustStats.robustZ(movement.delta(), deltaDistribution)
                : 0.0;

        double temporal = 0.0;
        List<Double> history = safeHistory(spec.id(), dimension, movement.entity(), period);
        if (history.size() > minHistoryPoints) {
            // The port returns history inclusive of the period being scored. That final point must be
            // dropped before it becomes the yardstick: leaving a value inside its own reference
            // distribution pulls the median toward itself and shrinks its own z-score, so the larger
            // the anomaly the more it suppresses its own detection.
            double[] baseline = RobustStats.toArray(history.subList(0, history.size() - 1));
            if (baseline.length >= minHistoryPoints) {
                temporal = RobustStats.robustZ(movement.current().value(), baseline);
            }
        }

        return Math.abs(temporal) >= Math.abs(crossSectional) ? temporal : crossSectional;
    }

    /**
     * Whether a movement is worth emitting.
     *
     * <p>Two independent routes qualify. A statistically unusual movement passes on {@code robustZ}
     * in either direction — an improvement can be as informative as a decline, and the collapse of
     * {@code EMPLOYEE_SIGN_OFF_TIME_VIOLATION} alerts from 7,670 in May to 46 in June is a 99.7% fall
     * that almost certainly reflects an instrumentation change rather than a fixed process. A
     * direction-only filter would discard it. Separately, a movement that is materially large and in
     * the adverse direction passes regardless of its z-score, because a real degradation should not
     * need to be statistically surprising to be reported.
     */
    private boolean significant(MetricSpec spec, Movement movement, double deltaPts, double robustZ) {
        if (Math.abs(robustZ) >= robustZThreshold) {
            return true;
        }
        if (!spec.isAdverse(movement.delta())) {
            return false;
        }
        if (spec.rateMetric()) {
            return Math.abs(deltaPts) >= materialDeltaPts;
        }
        double base = Math.abs(movement.prior().value());
        return base > EPSILON && Math.abs(movement.delta()) / base >= materialRelativeChange;
    }

    private Finding buildFinding(
            MetricSpec spec,
            String dimension,
            String period,
            String priorPeriod,
            Movement movement,
            double deltaPts,
            double robustZ,
            AttributionResult attributed) {

        MetricObservation observation = observe(
                spec, dimension, movement.entity(), period, movement.current());

        return new Finding(
                findingId(spec.id(), dimension, movement.entity(), period),
                spec.id(),
                dimension,
                movement.entity(),
                period,
                priorPeriod,
                movement.current().value(),
                movement.prior().value(),
                deltaPts,
                movement.current().sampleSize(),
                robustZ,
                0.0,
                observation,
                contributionsFor(dimension, attributed));
    }

    /**
     * Attaches the decomposition that explains this finding's own movement.
     *
     * <p>A finding on the un-sliced aggregate gets the winning dimension's split, because the
     * question it raises is "where did this come from". A finding already scoped to a dimension gets
     * that dimension's split, so its contributions are the siblings it was actually compared against
     * rather than an unrelated dimension's entities.
     */
    private List<Contribution> contributionsFor(String dimension, AttributionResult attributed) {
        Optional<DimensionAttribution> chosen = MetricSpec.GLOBAL.equals(dimension)
                ? attributed.winner()
                : attributed.forDimension(dimension);
        return chosen.map(DimensionAttribution::contributions).orElseGet(List::of);
    }

    /**
     * Delegates to the benchmark engine, degrading to a bare observation rather than failing the scan.
     *
     * <p>A finding without reference frames is weaker but still true; losing the whole sweep because
     * one benchmark lookup threw would be worse.
     */
    private MetricObservation observe(
            MetricSpec spec, String dimension, String entity, String period, MetricSlice slice) {
        try {
            MetricObservation observation = observations.observe(
                    spec.id(), dimension, entity, period, slice.value(), slice.sampleSize(), slice.coverage());
            if (observation != null) {
                return observation;
            }
            log.warn("Benchmark engine returned null for {}/{}/{}", spec.id(), dimension, entity);
        } catch (RuntimeException e) {
            log.warn("Benchmark lookup failed for {}/{}/{}: {}", spec.id(), dimension, entity, e.toString());
        }
        return new MetricObservation(
                spec.id(), dimension, entity, period, slice.value(), slice.sampleSize(),
                References.empty(), 0.0,
                new Quality(slice.coverage(), "LOW", List.of("reference frames unavailable")));
    }

    /** Rate metrics are stored as proportions; deltas are reported in points so 0.9531 to 0.9246 reads as -2.85. */
    private static double toPoints(MetricSpec spec, double delta) {
        return spec.rateMetric() ? delta * 100.0 : delta;
    }

    private List<MetricSlice> slicesFor(String metricId, String dimension, String period) {
        if (MetricSpec.GLOBAL.equals(dimension)) {
            return series.overall(metricId, period).map(List::of).orElseGet(List::of);
        }
        List<MetricSlice> slices = series.slices(metricId, dimension, period);
        return slices == null ? List.of() : slices;
    }

    private List<Double> safeHistory(String metricId, String dimension, String entity, String period) {
        try {
            List<Double> history = series.history(metricId, dimension, entity, period, historyLookback);
            return history == null ? List.of() : history;
        } catch (RuntimeException e) {
            log.debug("History unavailable for {}/{}/{}: {}", metricId, dimension, entity, e.toString());
            return List.of();
        }
    }

    private static Map<String, MetricSlice> index(List<MetricSlice> slices) {
        Map<String, MetricSlice> byEntity = new HashMap<>();
        for (MetricSlice slice : slices) {
            if (slice != null && slice.entity() != null) {
                byEntity.put(slice.entity(), slice);
            }
        }
        return byEntity;
    }

    /**
     * Deterministic finding id. Stability across runs is what lets the triage agent recognise a
     * movement it has already raised instead of opening a duplicate incident every cycle.
     */
    static String findingId(String metricId, String dimension, String entity, String period) {
        return String.join(":", slug(metricId), slug(dimension), slug(entity), slug(period));
    }

    private static String slug(String value) {
        if (value == null || value.isBlank()) {
            return "na";
        }
        return value.trim().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_");
    }

    /** One entity's period-over-period movement, carrying both slices so callers keep sample and coverage. */
    private record Movement(MetricSlice current, MetricSlice prior, double delta) {
        String entity() {
            return current.entity();
        }
    }
}
