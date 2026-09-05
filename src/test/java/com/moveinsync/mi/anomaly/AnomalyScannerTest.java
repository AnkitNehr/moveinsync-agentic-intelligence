package com.moveinsync.mi.anomaly;

import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.config.RankingProperties;
import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSeriesPort;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.metrics.spi.ObservationPort;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Covers the two behaviours the detection pipeline lives or dies on: the volume gate, and the
 * multiplicative ranking score.
 */
class AnomalyScannerTest {

    private static final String METRIC = "ota";
    private static final String MAY = "2026-05";
    private static final String JUNE = "2026-06";
    private static final long MIN_SAMPLE = 500L;

    private final FakeSeries series = new FakeSeries();
    private final RankingProperties properties = new RankingProperties();

    private MetricSpec spec(String... grains) {
        return new MetricSpec(METRIC, "On-Time Arrival", List.of(grains),
                MetricSpec.HIGHER_IS_BETTER, "sla.ota", 30L, true, 1);
    }

    private AnomalyScanner scanner(MetricSpec spec) {
        MetricCatalogPort catalog = new FakeCatalog(spec);
        AttributionService attribution = new AttributionService(catalog, series, MIN_SAMPLE);
        return new AnomalyScanner(catalog, series, new FakeObservations(), attribution,
                MIN_SAMPLE, 2.0, 1.0, 0.10, 12, 4);
    }

    @Nested
    @DisplayName("volume gate")
    class VolumeGate {

        @Test
        @DisplayName("suppresses a huge swing on an under-sampled segment")
        void suppressesTinySegments() {
            series.overall(MAY, 0.9531, 188_992);
            series.overall(JUNE, 0.9246, 210_669);
            // trip_nodal 'SHUTTLE' swings 26.6 points on 82 trips in the month. Without a gate this
            // is the single largest movement in the dataset and would top every ranking.
            series.slice("trip_nodal", MAY, "SHUTTLE", 0.9800, 82);
            series.slice("trip_nodal", JUNE, "SHUTTLE", 0.7140, 81);
            series.slice("trip_nodal", MAY, "NA", 0.9531, 188_910);
            series.slice("trip_nodal", JUNE, "NA", 0.9246, 210_588);

            List<Finding> findings = scanner(spec("trip_nodal")).scan(JUNE, MAY);

            assertThat(findings).extracting(Finding::entity).doesNotContain("SHUTTLE");
        }

        @Test
        @DisplayName("an under-sampled segment cannot skew the cross-sectional distribution")
        void gatedSegmentsAreExcludedFromTheReferenceDistribution() {
            series.overall(MAY, 0.95, 100_000);
            series.overall(JUNE, 0.94, 100_000);
            for (int i = 0; i < 4; i++) {
                series.slice("office", MAY, "office-" + i, 0.95, 20_000);
                series.slice("office", JUNE, "office-" + i, 0.945, 20_000);
            }
            // SPOT_2.0-sized segment: a wild swing on 200 trips.
            series.slice("office", MAY, "tiny", 0.95, 200);
            series.slice("office", JUNE, "tiny", 0.40, 200);

            List<Finding> findings = scanner(spec("office")).scan(JUNE, MAY);

            assertThat(findings)
                    .as("the gated segment is excluded, and the remaining offices moved uniformly")
                    .isEmpty();
        }
    }

    @Nested
    @DisplayName("detection")
    class Detection {

        @Test
        @DisplayName("emits a material adverse movement and drops an immaterial one")
        void emitsMaterialMovements() {
            series.overall(MAY, 0.9531, 188_992);
            series.overall(JUNE, 0.9246, 210_669);
            series.slice("trip_direction", MAY, "LOGIN", 0.9340, 89_326);
            series.slice("trip_direction", MAY, "LOGOUT", 0.9700, 99_666);
            series.slice("trip_direction", JUNE, "LOGIN", 0.8823, 99_583);
            series.slice("trip_direction", JUNE, "LOGOUT", 0.9623, 111_086);

            List<Finding> findings = scanner(spec("trip_direction")).scan(JUNE, MAY);

            assertThat(findings).extracting(Finding::entity).containsExactly("LOGIN");
            Finding login = findings.getFirst();
            assertThat(login.deltaPts())
                    .as("rate deltas are reported in points, not proportions")
                    .isCloseTo(-5.17, within(0.01));
            assertThat(login.sampleSize()).isEqualTo(99_583L);
            assertThat(login.score()).as("scoring is the ranker's job, not the scanner's").isZero();
            assertThat(login.contributions())
                    .as("the finding carries its own dimension's decomposition")
                    .extracting(com.moveinsync.mi.model.Contribution::entity)
                    .containsExactlyInAnyOrder("LOGIN", "LOGOUT");
        }

        @Test
        @DisplayName("flags a cross-sectional outlier even when it is small in absolute terms")
        void flagsCrossSectionalOutlier() {
            series.overall(MAY, 0.95, 100_000);
            series.overall(JUNE, 0.945, 100_000);
            for (int i = 0; i < 4; i++) {
                series.slice("office", MAY, "steady-" + i, 0.95, 20_000);
                series.slice("office", JUNE, "steady-" + i, 0.945, 20_000);
            }
            series.slice("office", MAY, "Denver", 0.95, 20_000);
            series.slice("office", JUNE, "Denver", 0.87, 20_000);

            List<Finding> findings = scanner(spec("office")).scan(JUNE, MAY);

            assertThat(findings).extracting(Finding::entity).containsExactly("Denver");
            assertThat(Math.abs(findings.getFirst().robustZ())).isGreaterThan(2.0);
        }

        @Test
        @DisplayName("finding ids are stable across runs so triage can dedupe")
        void findingIdsAreStable() {
            series.overall(MAY, 0.9531, 188_992);
            series.overall(JUNE, 0.9246, 210_669);
            series.slice("trip_direction", MAY, "LOGIN", 0.9340, 89_326);
            series.slice("trip_direction", MAY, "LOGOUT", 0.9700, 99_666);
            series.slice("trip_direction", JUNE, "LOGIN", 0.8823, 99_583);
            series.slice("trip_direction", JUNE, "LOGOUT", 0.9623, 111_086);

            AnomalyScanner scanner = scanner(spec("trip_direction"));
            assertThat(scanner.scan(JUNE, MAY)).extracting(Finding::id)
                    .isEqualTo(scanner.scan(JUNE, MAY).stream().map(Finding::id).toList());
            assertThat(scanner.scan(JUNE, MAY).getFirst().id()).isEqualTo("ota:trip_direction:login:2026_06");
        }

        @Test
        @DisplayName("a benchmark engine failure degrades the finding instead of aborting the scan")
        void survivesBenchmarkFailure() {
            series.overall(MAY, 0.9531, 188_992);
            series.overall(JUNE, 0.9246, 210_669);
            series.slice("trip_direction", MAY, "LOGIN", 0.9340, 89_326);
            series.slice("trip_direction", MAY, "LOGOUT", 0.9700, 99_666);
            series.slice("trip_direction", JUNE, "LOGIN", 0.8823, 99_583);
            series.slice("trip_direction", JUNE, "LOGOUT", 0.9623, 111_086);

            MetricSpec spec = spec("trip_direction");
            MetricCatalogPort catalog = new FakeCatalog(spec);
            AnomalyScanner scanner = new AnomalyScanner(catalog, series,
                    (m, g, e, p, v, s, c) -> {
                        throw new IllegalStateException("benchmark engine down");
                    },
                    new AttributionService(catalog, series, MIN_SAMPLE),
                    MIN_SAMPLE, 2.0, 1.0, 0.10, 12, 4);

            List<Finding> findings = scanner.scan(JUNE, MAY);

            assertThat(findings).hasSize(1);
            assertThat(findings.getFirst().observation().quality().caveats())
                    .contains("reference frames unavailable");
        }
    }

    @Nested
    @DisplayName("ranking")
    class Ranking {

        private final CandidateRanker ranker =
                new CandidateRanker(new FakeCatalog(spec("vendor_id")), properties);

        private Finding finding(String id, String dimension, double deltaPts, long sampleSize) {
            MetricObservation observation = new MetricObservation(
                    METRIC, dimension, id, JUNE, 0.90, sampleSize,
                    new References(new Trend(0.95, -0.05, -3.0), Sla.notApplicable(),
                            Peer.none(), Industry.none()),
                    0.8, new Quality(1.0, "HIGH", List.of()));
            return new Finding(id, METRIC, dimension, id, JUNE, MAY, 0.90, 0.95,
                    deltaPts, sampleSize, -3.0, 0.0, observation, List.of());
        }

        @Test
        @DisplayName("an unactionable dimension ranks below an actionable one of equal magnitude")
        void actionabilityDominatesEqualMagnitude() {
            Finding vendor = finding("vendor-1", "vendor_id", -5.0, 10_000);
            Finding fuel = finding("DIESEL", "actual_cab_fuel_type", -5.0, 10_000);

            List<Finding> ranked = ranker.rank(List.of(fuel, vendor));

            assertThat(ranked).extracting(Finding::entity).containsExactly("vendor-1", "DIESEL");
            // Identical on every other term, so the score ratio is exactly the actionability ratio.
            assertThat(ranked.get(1).score() / ranked.getFirst().score())
                    .isCloseTo(0.3, within(1e-9));
        }

        @Test
        @DisplayName("confidence rises with sample size but saturates")
        void confidenceIsLogScaledAndCapped() {
            Finding small = finding("a", "vendor_id", -5.0, 600);
            Finding large = finding("b", "vendor_id", -5.0, 5_000);
            Finding huge = finding("c", "vendor_id", -5.0, 500_000);

            List<Finding> ranked = ranker.rank(List.of(small, large, huge));
            Map<String, Double> scores = new LinkedHashMap<>();
            ranked.forEach(f -> scores.put(f.entity(), f.score()));

            assertThat(scores.get("a")).isLessThan(scores.get("b"));
            assertThat(scores.get("c"))
                    .as("beyond saturation extra volume must not buy more rank")
                    .isEqualTo(scores.get("b"));
        }

        @Test
        @DisplayName("a fully suppressed finding is dropped, not merely demoted")
        void suppressionRemovesFindings() {
            Finding dismissed = finding("vendor-1", "vendor_id", -5.0, 10_000);
            Finding kept = finding("vendor-2", "vendor_id", -5.0, 10_000);
            RankingContext context = new RankingContext(
                    Map.of(RankingContext.key(dismissed), 1.0), Map.of());

            assertThat(ranker.rank(List.of(dismissed, kept), context))
                    .extracting(Finding::entity).containsExactly("vendor-2");
        }

        @Test
        @DisplayName("partial suppression demotes without removing")
        void partialSuppressionDemotes() {
            Finding damped = finding("vendor-1", "vendor_id", -5.0, 10_000);
            Finding kept = finding("vendor-2", "vendor_id", -5.0, 10_000);
            RankingContext context = new RankingContext(
                    Map.of(RankingContext.key(damped), 0.5), Map.of());

            List<Finding> ranked = ranker.rank(List.of(damped, kept), context);
            assertThat(ranked).extracting(Finding::entity).containsExactly("vendor-2", "vendor-1");
            assertThat(ranked.get(1).score()).isCloseTo(ranked.getFirst().score() * 0.5, within(1e-9));
        }

        @Test
        @DisplayName("a recurring problem outranks a first-time one")
        void persistencePromotesRepeatOffenders() {
            Finding repeat = finding("vendor-1", "vendor_id", -5.0, 10_000);
            Finding fresh = finding("vendor-2", "vendor_id", -5.0, 10_000);
            RankingContext context = new RankingContext(
                    Map.of(), Map.of(RankingContext.key(repeat), 3));

            assertThat(ranker.rank(List.of(fresh, repeat), context))
                    .extracting(Finding::entity).containsExactly("vendor-1", "vendor-2");
        }

        @Test
        @DisplayName("returns at most topN and is stable across repeated runs")
        void limitsAndOrdersDeterministically() {
            List<Finding> findings = new ArrayList<>();
            for (int i = 0; i < 40; i++) {
                findings.add(finding("vendor-" + i, "vendor_id", -5.0, 1_000 + i));
            }

            List<Finding> first = ranker.rank(findings, RankingContext.empty(), 5);
            List<Finding> second = ranker.rank(findings, RankingContext.empty(), 5);

            assertThat(first).hasSize(5);
            assertThat(first).extracting(Finding::id).isEqualTo(second.stream().map(Finding::id).toList());
        }

        @Test
        @DisplayName("empty input yields an empty ranking")
        void handlesEmptyInput() {
            assertThat(ranker.rank(List.of())).isEmpty();
            assertThat(ranker.rank(null)).isEmpty();
        }
    }

    private static final class FakeSeries implements MetricSeriesPort {
        private final Map<String, List<MetricSlice>> slices = new LinkedHashMap<>();
        private final Map<String, MetricSlice> overall = new LinkedHashMap<>();

        void slice(String dimension, String period, String entity, double value, long sampleSize) {
            slices.computeIfAbsent(dimension + "|" + period, k -> new ArrayList<>())
                    .add(new MetricSlice(entity, value, sampleSize, 1.0));
        }

        void overall(String period, double value, long sampleSize) {
            overall.put(period, new MetricSlice(MetricSpec.ALL, value, sampleSize, 1.0));
        }

        @Override
        public List<MetricSlice> slices(String metricId, String dimension, String period) {
            return slices.getOrDefault(dimension + "|" + period, List.of());
        }

        @Override
        public Optional<MetricSlice> overall(String metricId, String period) {
            return Optional.ofNullable(overall.get(period));
        }

        @Override
        public List<Double> history(String m, String d, String e, String p, int lookback) {
            return List.of();
        }
    }

    private record FakeCatalog(MetricSpec spec) implements MetricCatalogPort {
        @Override
        public List<MetricSpec> metrics() {
            return List.of(spec);
        }

        @Override
        public Optional<MetricSpec> find(String metricId) {
            return spec.id().equals(metricId) ? Optional.of(spec) : Optional.empty();
        }
    }

    private static final class FakeObservations implements ObservationPort {
        @Override
        public MetricObservation observe(String metricId, String grain, String entity, String period,
                                         Double value, long sampleSize, double coverage) {
            return new MetricObservation(metricId, grain, entity, period, value, sampleSize,
                    References.empty(), 0.7, new Quality(coverage, "HIGH", List.of()));
        }
    }
}
