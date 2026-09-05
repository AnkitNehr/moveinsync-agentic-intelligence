package com.moveinsync.mi.anomaly;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Finds entities that are persistently poor, as opposed to newly worse.
 *
 * <h2>The gap this closes</h2>
 *
 * <p>{@link AnomalyScanner} admits a series on movement and nothing else: every route in its
 * significance test reads a delta — the movement's robust z, whether the delta is adverse, the size
 * of the delta, the delta relative to the prior value. That is the correct design for an incident
 * pipeline, because an incident is something that <em>happened</em> and a page at 07:00 should be
 * about a change.
 *
 * <p>It also means a segment that has been bad for as long as the data runs is invisible. Nothing
 * moved, so nothing fires, so nobody is told. Vendor "Isha Mikhailov Travel" makes the point on the
 * supplied dataset: last of 21 on no-shows at roughly six times the cohort median, last of 16 on
 * night escort coverage, and no incident open against it in any period. It is not deteriorating. It
 * is simply, and consistently, the worst — and a reporting layer that never mentions that is
 * answering a narrower question than the one its users have.
 *
 * <h2>Why this is separate from the incident pipeline</h2>
 *
 * <p>These are deliberately not {@code Finding}s and never become incidents. An incident carries a
 * movement, a prior period, an attribution and a policy verdict; a standing outlier has none of
 * those, because nothing changed. Forcing it through the same pipeline would produce incidents
 * titled "rose +0.00" with an empty decomposition, and would flood a list whose value depends on
 * every row being worth acting on today.
 *
 * <p>They are a different question — "who is quietly bad?" rather than "what changed?" — so they get
 * a different surface. Both are needed; neither substitutes for the other.
 *
 * <h2>Gating</h2>
 *
 * <p>Cross-sectional outliers are common, so the bar is deliberately higher than the movement
 * scanner's. Three conditions must all hold: the slice clears the metric's own volume gate, its
 * value is on the <em>adverse</em> side of the cohort median, and it sits at least
 * {@code app.standing.min-z} robust deviations from that median. Being unusually good is not a
 * finding.
 */
@Service
public class StandingOutlierScanner {

    private static final Logger log = LoggerFactory.getLogger(StandingOutlierScanner.class);

    /** Cohorts smaller than this cannot support an outlier claim — a median of two means nothing. */
    private static final int MIN_COHORT = 5;

    /** Smallest gap on a rate metric worth reporting: one percentage point. */
    private static final double MIN_RATE_GAP = 0.01;

    private static final double EPSILON = 1e-9;

    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final double minZ;
    private final double minRelativeGap;
    private final int limit;

    public StandingOutlierScanner(
            MetricCatalog catalog,
            MetricQueryService metrics,
            @Value("${app.standing.min-z:3.5}") double minZ,
            @Value("${app.standing.min-relative-gap:0.25}") double minRelativeGap,
            @Value("${app.standing.limit:20}") int limit) {
        this.catalog = catalog;
        this.metrics = metrics;
        this.minZ = Double.isFinite(minZ) ? Math.abs(minZ) : 3.5;
        this.minRelativeGap = Double.isFinite(minRelativeGap) ? Math.abs(minRelativeGap) : 0.25;
        this.limit = Math.max(1, limit);
    }

    /**
     * One persistently poor segment.
     *
     * @param metricId      the metric it is poor on
     * @param metricLabel   that metric's display name
     * @param dimension     the grain it was found on, e.g. {@code vendor}
     * @param entity        the segment itself
     * @param value         its value in the requested period
     * @param cohortMedian  the median across its peers
     * @param rank          its position in the cohort, 1 being best in the metric's own direction
     * @param cohortSize    how many peers cleared the volume gate
     * @param robustZ       distance from the cohort median, in robust deviations; always adverse
     * @param sampleSize    trips behind the value
     */
    public record StandingOutlier(
            String metricId,
            String metricLabel,
            String dimension,
            String entity,
            double value,
            double cohortMedian,
            int rank,
            int cohortSize,
            double robustZ,
            long sampleSize) {}

    /**
     * Whether the gap from the cohort median is big enough for anyone to care.
     *
     * <p>A z-score alone is not enough, and the driver-compliance cohort shows why: nearly every
     * vendor sits at 0.00%, so the median absolute deviation is almost zero and a vendor at 0.01%
     * scores a robust z of 158. That is arithmetically correct and operationally worthless — a
     * hundredth of a percentage point is a rounding artefact, not a vendor problem. Left ungated it
     * occupied the top three rows and pushed a vendor with six times the cohort no-show rate to
     * seventh.
     *
     * <p>{@link CandidateRanker} guards the same trap on the movement side. The two thresholds are
     * separate on purpose: what counts as material depends on the unit, and a rate needs an absolute
     * floor in points where an unbounded quantity like delay minutes is better judged in proportion.
     */
    private boolean material(MetricDefinition definition, double value, double median) {
        double gap = Math.abs(value - median);
        if (definition.rateMetric()) {
            // Rates live on 0..1, so a percentage-point floor is the honest test. Anything under a
            // point apart is noise however extreme it looks against a flat cohort.
            return gap >= MIN_RATE_GAP;
        }
        double base = Math.abs(median);
        // With a median at zero there is no proportion to take, so any adverse non-zero value counts.
        return base < EPSILON ? gap > EPSILON : gap / base >= minRelativeGap;
    }

    /**
     * Scans every metric and grain for segments that are far worse than their peers.
     *
     * @param period period to read; no prior period is needed, which is the whole point
     * @return outliers, worst first, capped at {@code app.standing.limit}
     */
    public List<StandingOutlier> scan(String period) {
        List<StandingOutlier> found = new ArrayList<>();

        for (MetricDefinition definition : catalog.all()) {
            for (String grain : definition.sliceableGrains()) {
                List<MetricSlice> cohort;
                try {
                    cohort = metrics.slices(definition.id(), grain, period).stream()
                            .filter(MetricSlice::measured)
                            .filter(s -> s.sampleSize() >= definition.minSample())
                            .toList();
                } catch (RuntimeException e) {
                    log.debug("Standing scan skipped {}/{}: {}", definition.id(), grain, e.toString());
                    continue;
                }
                if (cohort.size() < MIN_COHORT) {
                    continue;
                }

                double[] values = cohort.stream().mapToDouble(MetricSlice::value).toArray();
                double median = RobustStats.median(values);
                double mad = RobustStats.mad(values);
                if (!(mad > 0)) {
                    // A cohort where every peer sits on the same value has no outliers by
                    // construction. Reporting one would be dividing by nothing.
                    continue;
                }

                boolean higherIsBetter = definition.higherIsBetter();
                List<MetricSlice> ordered = cohort.stream()
                        .sorted(higherIsBetter
                                ? Comparator.comparingDouble((MetricSlice s) -> s.value()).reversed()
                                : Comparator.comparingDouble(MetricSlice::value))
                        .toList();

                for (MetricSlice slice : cohort) {
                    double z = RobustStats.robustZ(slice.value(), median, mad);
                    // Adverse side only. On a higher-is-better metric that is below the median; on a
                    // lower-is-better metric it is above. Being exceptionally good is not a finding,
                    // and reporting it here would bury the segments that need attention.
                    boolean adverse = higherIsBetter ? z < 0 : z > 0;
                    if (!adverse || Math.abs(z) < minZ) {
                        continue;
                    }
                    if (!material(definition, slice.value(), median)) {
                        continue;
                    }
                    found.add(new StandingOutlier(
                            definition.id(),
                            definition.label(),
                            grain,
                            slice.entity(),
                            slice.value(),
                            median,
                            ordered.indexOf(slice) + 1,
                            ordered.size(),
                            z,
                            slice.sampleSize()));
                }
            }
        }

        found.sort(Comparator.comparingDouble((StandingOutlier o) -> -Math.abs(o.robustZ())));
        List<StandingOutlier> capped = found.stream().limit(limit).toList();
        log.info("Standing outliers in {}: {} found, reporting {}", period, found.size(), capped.size());
        return capped;
    }
}
