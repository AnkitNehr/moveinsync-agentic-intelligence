package com.moveinsync.mi.attribution;

import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSeriesPort;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.Contribution;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Decomposes a metric movement across every available dimension and ranks the dimensions by how well
 * each one explains it.
 *
 * <h2>Why scan every dimension</h2>
 *
 * <p>The obvious design is to decompose by vendor and report the worst vendor. On this data that
 * design returns nothing. Between May and June the campus on-time rate falls 2.85 points, and vendor
 * volume share barely moves at all — the largest share shift across 23 vendors is 0.79 points, so the
 * mix effect is approximately zero and no vendor stands out on rate either. A vendor-only attribution
 * engine would decompose that movement, find it evenly spread, and report a confident all-clear.
 *
 * <p>The signal is on dimensions a vendor-shaped tool never looks at: LOGIN trips fell 5.17 points
 * against LOGOUT's 0.77, BUS fell 6.25 against CAB's 2.20, and MANUAL-routed trips fell 6.22 against
 * AUTO's 2.20. Those three are the same underlying story — manually planned morning bus routes — and
 * it is only visible because the decomposition is run across the full dimension list and ranked,
 * never pointed at a dimension chosen in advance.
 *
 * <h2>How dimensions are ranked</h2>
 *
 * <p>Every dimension reconciles to the same delta, so summed contribution cannot rank them. Three
 * properties are combined instead, each in {@code [0, 1]}:
 *
 * <ul>
 *   <li><b>Explained</b> — how much of the aggregate delta the top-3 entities account for. This is
 *       the primary term: a dimension whose leading members carry the whole movement localises it.</li>
 *   <li><b>Concentration</b> — the share of gross entity movement those top 3 carry. Separates
 *       "three entities did this" from "thirty entities each did a little and three happen to be
 *       largest".</li>
 *   <li><b>Dispersion</b> — how differently entities moved relative to the aggregate. This is the
 *       term that stops the ranking degenerating. Explained and concentration both saturate at 1.0
 *       for any dimension with three or fewer members, so on their own a binary dimension always
 *       wins. Dispersion asks the question that actually matters: did the members move differently
 *       from each other? If every entity declined in step with the total, the dimension has restated
 *       the aggregate rather than explained it, and it scores near zero however concentrated it
 *       looks.</li>
 * </ul>
 *
 * <p>Dispersion enters through a floor rather than as a plain multiplier, so a genuinely concentrated
 * dimension is not zeroed out by a modest dispersion reading, while a uniform one is still pushed
 * well down the ranking.
 */
@Service
public class AttributionService {

    private static final Logger log = LoggerFactory.getLogger(AttributionService.class);

    /** Number of leading entities whose combined contribution defines "explained". */
    static final int TOP_K = 3;

    /**
     * Weight retained by a dimension with zero dispersion. Uniform movement is heavily penalised but
     * not eliminated, because a uniform decline across a dimension is still worth reporting when no
     * dimension anywhere shows structure.
     */
    static final double DISPERSION_FLOOR = 0.25;

    private static final double EPSILON = 1e-12;

    private final MetricCatalogPort catalog;
    private final MetricSeriesPort series;
    private final MixRateDecomposer decomposer = new MixRateDecomposer();
    private final long globalMinSample;

    public AttributionService(
            MetricCatalogPort catalog,
            MetricSeriesPort series,
            @Value("${app.scanner.min-sample:500}") long globalMinSample) {
        this.catalog = catalog;
        this.series = series;
        this.globalMinSample = Math.max(0L, globalMinSample);
    }

    /**
     * Attributes a metric's period-over-period movement across all of its catalog grains.
     *
     * @param metricId    metric to decompose
     * @param period      current period label
     * @param priorPeriod comparison period label
     * @return ranked decompositions, best explanation first; empty when the metric is unknown or
     *         unmeasurable in either period
     */
    public AttributionResult attribute(String metricId, String period, String priorPeriod) {
        Optional<MetricSpec> spec = catalog.find(metricId);
        if (spec.isEmpty()) {
            log.debug("Attribution skipped: metric {} not in catalog", metricId);
            return AttributionResult.empty(metricId, period, priorPeriod);
        }
        return attribute(spec.get(), period, priorPeriod, spec.get().grains());
    }

    /**
     * Attributes a movement across an explicit dimension list.
     *
     * @param spec        metric definition, supplying the volume gate and direction
     * @param period      current period label
     * @param priorPeriod comparison period label
     * @param dimensions  dimensions to decompose across; {@code global} is skipped as it has no parts
     * @return ranked decompositions, best explanation first
     */
    public AttributionResult attribute(
            MetricSpec spec, String period, String priorPeriod, List<String> dimensions) {

        Optional<Double> current = measuredValue(spec.id(), period);
        Optional<Double> prior = measuredValue(spec.id(), priorPeriod);
        if (current.isEmpty() || prior.isEmpty()) {
            log.debug("Attribution skipped for {}: aggregate unmeasurable in {} or {}",
                    spec.id(), period, priorPeriod);
            return AttributionResult.empty(spec.id(), period, priorPeriod);
        }

        double actualDelta = current.get() - prior.get();
        long minSample = effectiveMinSample(spec);

        List<DimensionAttribution> ranked = new ArrayList<>();
        for (String dimension : dimensions) {
            if (MetricSpec.GLOBAL.equals(dimension)) {
                continue;
            }
            decomposeDimension(spec, dimension, period, priorPeriod, actualDelta, minSample)
                    .ifPresent(ranked::add);
        }

        ranked.sort(Comparator
                .comparingDouble((DimensionAttribution d) -> -d.explanatoryPower())
                .thenComparing(DimensionAttribution::dimension));

        if (log.isDebugEnabled() && !ranked.isEmpty()) {
            DimensionAttribution top = ranked.getFirst();
            log.debug("Attribution for {} {} vs {}: delta={} winner={} power={} leader={}",
                    spec.id(), period, priorPeriod, actualDelta, top.dimension(),
                    top.explanatoryPower(), top.leader() == null ? "none" : top.leader().entity());
        }
        return new AttributionResult(spec.id(), period, priorPeriod, actualDelta, List.copyOf(ranked));
    }

    /**
     * Decomposes one dimension and scores how well it explains the movement.
     *
     * @return the decomposition, or empty when fewer than two entities cleared the volume gate —
     *         a single-entity decomposition is just the aggregate wearing a label
     */
    private Optional<DimensionAttribution> decomposeDimension(
            MetricSpec spec,
            String dimension,
            String period,
            String priorPeriod,
            double actualDelta,
            long minSample) {

        Map<String, MetricSlice> currentSlices = index(series.slices(spec.id(), dimension, period));
        Map<String, MetricSlice> priorSlices = index(series.slices(spec.id(), dimension, priorPeriod));
        if (currentSlices.isEmpty() && priorSlices.isEmpty()) {
            return Optional.empty();
        }

        Set<String> entities = new LinkedHashSet<>(currentSlices.keySet());
        entities.addAll(priorSlices.keySet());

        Map<String, double[]> base = new HashMap<>();
        Map<String, double[]> current = new HashMap<>();
        long sampleSize = 0L;

        for (String entity : entities) {
            MetricSlice c = currentSlices.get(entity);
            MetricSlice p = priorSlices.get(entity);

            // Volume gate. An entity must clear min_sample in at least one period to enter the
            // decomposition; below that its rate is noise, and this is what suppresses the tiny
            // segments that otherwise dominate any ranking by absolute movement (trip_nodal
            // 'SHUTTLE' at 244 trips produced a spurious 26.6-point swing).
            long currentSample = c == null ? 0L : c.sampleSize();
            long priorSample = p == null ? 0L : p.sampleSize();
            if (Math.max(currentSample, priorSample) < minSample) {
                continue;
            }
            // An unmeasurable rate cannot be decomposed. The entity is dropped rather than
            // zero-filled, and the resulting shortfall surfaces as reconciliation error instead of
            // being quietly absorbed into other entities' contributions.
            boolean currentMeasured = c != null && c.measured();
            boolean priorMeasured = p != null && p.measured();
            if (!currentMeasured && !priorMeasured) {
                continue;
            }

            if (priorMeasured) {
                base.put(entity, MixRateDecomposer.slice(p.value(), priorSample));
            }
            if (currentMeasured) {
                current.put(entity, MixRateDecomposer.slice(c.value(), currentSample));
                sampleSize += currentSample;
            }
        }

        Set<String> decomposed = new LinkedHashSet<>(base.keySet());
        decomposed.addAll(current.keySet());
        if (decomposed.size() < 2) {
            return Optional.empty();
        }

        List<Contribution> contributions = decomposer.decompose(base, current);
        double reconciliationError = decomposer.reconciliationError(contributions, actualDelta);

        double concentration = concentration(contributions);
        double explainedDelta = topKTotal(contributions);
        double explained = ratio(explainedDelta, actualDelta);
        double dispersion = dispersion(base, current, actualDelta);
        double power = explained * concentration * (DISPERSION_FLOOR + (1 - DISPERSION_FLOOR) * dispersion);

        return Optional.of(new DimensionAttribution(
                dimension,
                actualDelta,
                explainedDelta,
                power,
                concentration,
                dispersion,
                reconciliationError,
                decomposed.size(),
                sampleSize,
                contributions));
    }

    /**
     * Signed total contribution of the leading {@link #TOP_K} entities. Contributions arrive sorted
     * by absolute magnitude, so this is a prefix sum.
     */
    private static double topKTotal(List<Contribution> contributions) {
        double sum = 0.0;
        for (int i = 0; i < Math.min(TOP_K, contributions.size()); i++) {
            sum += contributions.get(i).total();
        }
        return sum;
    }

    /** Share of gross entity movement carried by the leading {@link #TOP_K} entities. */
    private static double concentration(List<Contribution> contributions) {
        double gross = 0.0;
        for (Contribution c : contributions) {
            gross += Math.abs(c.total());
        }
        if (gross <= EPSILON) {
            return 0.0;
        }
        double top = 0.0;
        for (int i = 0; i < Math.min(TOP_K, contributions.size()); i++) {
            top += Math.abs(contributions.get(i).total());
        }
        return Math.clamp(top / gross, 0.0, 1.0);
    }

    /**
     * Volume-weighted mean absolute deviation of per-entity rate movements from the aggregate
     * movement, normalised by the volume-weighted mean absolute movement.
     *
     * <p>Zero when every entity moved exactly as the aggregate did — the dimension adds nothing.
     * Approaches one when entity movements are large but the aggregate is near flat, which is the
     * shape of an offsetting split where one member deteriorated while another improved.
     *
     * <p>Only entities measured in both periods contribute, since an entity present in a single
     * period has no rate movement to compare.
     */
    private static double dispersion(
            Map<String, double[]> base, Map<String, double[]> current, double actualDelta) {

        double weightTotal = 0.0;
        for (String entity : current.keySet()) {
            if (base.containsKey(entity)) {
                weightTotal += current.get(entity)[MixRateDecomposer.WEIGHT];
            }
        }
        if (weightTotal <= EPSILON) {
            return 0.0;
        }

        double deviation = 0.0;
        double movement = 0.0;
        for (Map.Entry<String, double[]> entry : current.entrySet()) {
            double[] priorSlice = base.get(entry.getKey());
            if (priorSlice == null) {
                continue;
            }
            double weight = entry.getValue()[MixRateDecomposer.WEIGHT] / weightTotal;
            double entityDelta = entry.getValue()[MixRateDecomposer.RATE] - priorSlice[MixRateDecomposer.RATE];
            deviation += weight * Math.abs(entityDelta - actualDelta);
            movement += weight * Math.abs(entityDelta);
        }

        double scale = Math.max(movement, Math.abs(actualDelta));
        if (scale <= EPSILON) {
            return 0.0;
        }
        return Math.clamp(deviation / scale, 0.0, 1.0);
    }

    /** Fraction of the aggregate movement explained, clamped so offsetting effects cannot exceed 1. */
    private static double ratio(double explained, double actualDelta) {
        if (Math.abs(actualDelta) <= EPSILON) {
            return 0.0;
        }
        return Math.clamp(Math.abs(explained) / Math.abs(actualDelta), 0.0, 1.0);
    }

    /**
     * The stricter of the metric's own gate and the platform-wide floor.
     *
     * <p>The catalog defaults to 30, which is the right floor for a route-level metric but far too
     * permissive for the monthly grain this scanner runs at. Taking the maximum lets a metric raise
     * its own bar without letting it lower the platform's.
     */
    private long effectiveMinSample(MetricSpec spec) {
        return Math.max(globalMinSample, spec.minSample());
    }

    private Optional<Double> measuredValue(String metricId, String period) {
        return series.overall(metricId, period)
                .filter(MetricSlice::measured)
                .map(MetricSlice::value);
    }

    private static Map<String, MetricSlice> index(List<MetricSlice> slices) {
        if (slices == null || slices.isEmpty()) {
            return Map.of();
        }
        Map<String, MetricSlice> byEntity = new HashMap<>();
        for (MetricSlice slice : slices) {
            if (slice != null && slice.entity() != null) {
                byEntity.put(slice.entity(), slice);
            }
        }
        return byEntity;
    }
}
