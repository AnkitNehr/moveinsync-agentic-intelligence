package com.moveinsync.mi.attribution;

import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSeriesPort;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Proves the claim the attribution engine is built on: ranking dimensions finds the signal that a
 * vendor-only decomposition misses entirely.
 *
 * <p>The fixture reproduces the shape of the real May-to-June on-time movement — a 2.85 point fall
 * that is invisible in vendor data and concentrated in trip direction and route source. A
 * vendor-first tool run on this data would decompose the movement, find it spread evenly across 23
 * vendors, and report that nothing in particular happened.
 */
class AttributionServiceTest {

    private static final String METRIC = "ota";
    private static final String MAY = "2026-05";
    private static final String JUNE = "2026-06";

    private static final double MAY_OTA = 0.9531;
    private static final double JUNE_OTA = 0.9246;
    private static final long MAY_TRIPS = 188_992L;
    private static final long JUNE_TRIPS = 210_669L;

    private final FakeSeries series = new FakeSeries();
    private final MetricSpec spec = new MetricSpec(
            METRIC, "On-Time Arrival",
            List.of("global", "trip_direction", "route_source", "vendor_id"),
            MetricSpec.HIGHER_IS_BETTER, "sla.ota", 30L, true, 1);
    private final AttributionService service =
            new AttributionService(new FakeCatalog(spec), series, 500L);

    private AttributionResult attribute() {
        series.overall(MAY, MAY_OTA, MAY_TRIPS);
        series.overall(JUNE, JUNE_OTA, JUNE_TRIPS);

        // trip_direction: LOGIN -5.17pts vs LOGOUT -0.77pts. Strongly differentiated.
        series.slice("trip_direction", MAY, "LOGIN", 0.9340, 89_326);
        series.slice("trip_direction", MAY, "LOGOUT", 0.9700, 99_666);
        series.slice("trip_direction", JUNE, "LOGIN", 0.8823, 99_583);
        series.slice("trip_direction", JUNE, "LOGOUT", 0.9623, 111_086);

        // route_source: MANUAL -6.22pts vs AUTO -2.20pts. Differentiated, but MANUAL is a small
        // share, so it explains less of the total than trip_direction does.
        series.slice("route_source", MAY, "MANUAL", 0.9200, 30_560);
        series.slice("route_source", MAY, "AUTO", 0.9600, 158_432);
        series.slice("route_source", JUNE, "MANUAL", 0.8578, 34_065);
        series.slice("route_source", JUNE, "AUTO", 0.9380, 176_604);

        // vendor_id: all 23 vendors decline in lockstep with the fleet, shares static. Arithmetically
        // a valid decomposition; causally worthless.
        for (int i = 0; i < 23; i++) {
            series.slice("vendor_id", MAY, "vendor-" + i, MAY_OTA, MAY_TRIPS / 23);
            series.slice("vendor_id", JUNE, "vendor-" + i, JUNE_OTA, JUNE_TRIPS / 23);
        }

        return service.attribute(spec, JUNE, MAY, spec.grains());
    }

    @Test
    @DisplayName("ranks the differentiated dimensions above the uniform vendor split")
    void ranksDimensionsByExplanatoryPower() {
        AttributionResult result = attribute();

        assertThat(result.ranked()).extracting(DimensionAttribution::dimension)
                .containsExactly("trip_direction", "route_source", "vendor_id");

        assertThat(result.winner()).isPresent();
        assertThat(result.winner().orElseThrow().dimension()).isEqualTo("trip_direction");
        assertThat(result.actualDelta()).isCloseTo(JUNE_OTA - MAY_OTA, within(1e-12));
    }

    @Test
    @DisplayName("a uniform decline scores near-zero explanatory power however it is sliced")
    void uniformDeclineExplainsNothing() {
        AttributionResult result = attribute();

        DimensionAttribution vendor = result.forDimension("vendor_id").orElseThrow();
        DimensionAttribution direction = result.forDimension("trip_direction").orElseThrow();

        assertThat(vendor.dispersion())
                .as("every vendor moved exactly as the fleet did, so the dimension adds no information")
                .isCloseTo(0.0, within(1e-9));
        assertThat(vendor.explanatoryPower()).isLessThan(0.05);
        assertThat(direction.explanatoryPower()).isGreaterThan(0.5);
        assertThat(direction.dispersion()).isGreaterThan(vendor.dispersion());
    }

    @Test
    @DisplayName("static vendor shares produce a negligible mix effect")
    void vendorMixEffectIsNegligible() {
        DimensionAttribution vendor = attribute().forDimension("vendor_id").orElseThrow();

        double totalMix = vendor.contributions().stream()
                .mapToDouble(com.moveinsync.mi.model.Contribution::mixEffect).sum();

        assertThat(Math.abs(totalMix))
                .as("no volume shifted between vendors, so no narrative may claim it did")
                .isLessThan(1e-6);
    }

    @Test
    @DisplayName("every dimension's decomposition reconciles to the aggregate movement")
    void allDimensionsReconcile() {
        AttributionResult result = attribute();

        assertThat(result.ranked()).isNotEmpty();
        // Each dimension covers the full trip population here, so every decomposition must close
        // against the reported aggregate delta with no coverage gap.
        assertThat(result.ranked()).allSatisfy(d ->
                assertThat(d.reconciliationError())
                        .as("dimension %s must reconcile", d.dimension())
                        .isLessThan(1e-3));
    }

    @Test
    @DisplayName("names LOGIN as the leading contributor")
    void identifiesLeadingContributor() {
        DimensionAttribution direction = attribute().forDimension("trip_direction").orElseThrow();

        assertThat(direction.leader()).isNotNull();
        assertThat(direction.leader().entity()).isEqualTo("LOGIN");
        assertThat(direction.leader().rateEffect())
                .as("LOGIN's own decline, not a volume shift, is what moved the fleet")
                .isLessThan(direction.leader().mixEffect());
    }

    @Test
    @DisplayName("suppresses segments below the volume gate")
    void appliesVolumeGate() {
        series.overall(MAY, MAY_OTA, MAY_TRIPS);
        series.overall(JUNE, JUNE_OTA, JUNE_TRIPS);
        // trip_nodal 'SHUTTLE' carries 244 trips across the whole quarter and swings 26.6 points.
        // Below the 500-trip gate it must never enter the decomposition.
        series.slice("trip_nodal", MAY, "SHUTTLE", 0.9800, 81);
        series.slice("trip_nodal", JUNE, "SHUTTLE", 0.7140, 82);
        series.slice("trip_nodal", MAY, "NA", 0.9531, 188_911);
        series.slice("trip_nodal", JUNE, "NA", 0.9246, 210_587);

        AttributionResult result = service.attribute(spec, JUNE, MAY, List.of("trip_nodal"));

        assertThat(result.ranked())
                .as("only NA clears the gate, and a single-entity split is not an explanation")
                .isEmpty();
    }

    /** In-memory series, keyed by dimension and period. */
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
}
