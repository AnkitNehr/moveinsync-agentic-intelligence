package com.moveinsync.mi.metric;

import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.ingest.DuckDbService;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.policy.SlaPolicy;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.mock.env.MockEnvironment;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalDouble;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * End-to-end verification of the metric layer against the real extracts.
 *
 * <p>Every expected figure below was computed independently against the raw CSVs before the Java
 * was written, so this asserts agreement between two implementations rather than pinning whatever
 * the code happens to produce. It reads roughly 3.2 million rows and takes about a minute, so it is
 * opt-in: run with {@code -Dmi.dataset=true} when the extracts are present under
 * {@code data/raw}.
 */
@EnabledIfSystemProperty(named = "mi.dataset", matches = "true")
@DisplayName("Metric layer against the real dataset")
class MetricLayerVerificationTest {

    private static final double TOLERANCE = 5e-4;

    private static DuckDbService duckDb;
    private static MetricCatalog catalog;
    private static MetricQueryService metrics;
    private static BenchmarkService benchmarks;

    @BeforeAll
    static void boot() {
        Path raw = Paths.get("data/raw").toAbsolutePath();
        assumeTrue(Files.isDirectory(raw), "dataset not present at " + raw);

        duckDb = new DuckDbService(raw.toString(), true);
        duckDb.createViews();

        catalog = new MetricCatalog();
        metrics = new MetricQueryService(catalog, duckDb);

        MockEnvironment environment = new MockEnvironment()
                .withProperty("app.industry.ota", "0.93")
                .withProperty("app.industry.noshow", "0.06");
        benchmarks = new BenchmarkService(catalog, metrics, new SlaPolicy(0.95, 1.0, 15, 25.0), environment);
    }

    @AfterAll
    static void shutdown() {
        if (duckDb != null) {
            duckDb.close();
        }
    }

    @Test
    @DisplayName("catalog loads all eight metrics and every definition validates")
    void catalogLoads() {
        assertEquals(
                List.of("cab_noncompliance", "cost_per_km", "cost_per_trip", "delay_p90",
                        "driver_noncompliance", "escort_compliance", "noshow_rate", "occupancy",
                        "ota"),
                catalog.ids());
        assertEquals(List.of("bills", "trips"), catalog.sourceViews());
        catalog.all().forEach(MetricDefinition::validate);
        assertEquals(List.of("trips"), List.of(catalog.get("ota").sourceView()));
    }

    @Test
    @DisplayName("OTA reproduces the reference series: 95.31 / 92.46 / 94.69")
    void otaMatchesReference() {
        assertEquals(0.953141, global("ota", "2026-05"), TOLERANCE);
        assertEquals(0.924555, global("ota", "2026-06"), TOLERANCE);
        assertEquals(0.946870, global("ota", "2026-07"), TOLERANCE);
    }

    @Test
    @DisplayName("the June drop concentrates on LOGIN, BUS and MANUAL, not on vendors")
    void juneDropIsConcentrated() {
        assertEquals(-5.17, deltaPts("ota", "trip_direction", "LOGIN"), 0.05);
        assertEquals(-0.77, deltaPts("ota", "trip_direction", "LOGOUT"), 0.05);
        assertEquals(-6.25, deltaPts("ota", "product_type", "BUS"), 0.05);
        assertEquals(-2.20, deltaPts("ota", "product_type", "CAB"), 0.05);
        assertEquals(-6.22, deltaPts("ota", "route_source", "MANUAL"), 0.05);
        assertEquals(-2.20, deltaPts("ota", "route_source", "AUTO"), 0.05);
    }

    @Test
    @DisplayName("cost metrics reproduce the reference series and exclude the OverHead rows")
    void costMatchesReference() {
        assertEquals(1310.71, global("cost_per_trip", "2026-05"), 0.01);
        assertEquals(1339.44, global("cost_per_trip", "2026-06"), 0.01);
        assertEquals(1355.61, global("cost_per_trip", "2026-07"), 0.01);

        // Credit notes (negative trip_cost) are excluded from this unit cost, so these are the
        // post-FILTER figures. Recomputed straight from bill_data.csv rather than read off the
        // implementation: May moves 77.29 -> 86.60 because 169 May credit lines total -15,480,950.24;
        // June is unchanged (no negative lines); July moves 78.49 -> 78.51 on 20 lines (-21,847.50).
        assertEquals(86.5954, global("cost_per_km", "2026-05"), 0.01);
        assertEquals(80.2389, global("cost_per_km", "2026-06"), 0.01);
        assertEquals(78.5061, global("cost_per_km", "2026-07"), 0.01);
    }

    @Test
    @DisplayName("the remaining five metrics reproduce their reference values")
    void otherMetricsMatchReference() {
        assertEquals(27.0, global("delay_p90", "2026-06"), TOLERANCE);
        assertEquals(0.094379, global("noshow_rate", "2026-05"), TOLERANCE);
        assertEquals(0.058071, global("noshow_rate", "2026-07"), TOLERANCE);
        assertEquals(0.579321, global("occupancy", "2026-05"), TOLERANCE);
        assertEquals(0.460980, global("escort_compliance", "2026-05"), TOLERANCE);
        assertEquals(0.001561, global("driver_noncompliance", "2026-05"), TOLERANCE);
    }

    @Test
    @DisplayName("cost_per_km never escapes the distance-based segment")
    void costPerKmIsRegimeGuarded() {
        MetricDefinition definition = catalog.get("cost_per_km");
        assertEquals("billing_regime", definition.segmentBy());
        assertEquals(List.of("DISTANCE_BASED"), definition.validSegments());
        assertFalse(definition.grains().contains("billing_regime"));

        // The fixed-rate segment's naive figure is 4,947 per km. If the guard ever leaks, the global
        // value moves by orders of magnitude, so this bound is a canary rather than a tight assertion.
        assertTrue(global("cost_per_km", "2026-06") < 200.0);
    }

    @Test
    @DisplayName("the volume gate suppresses tiny segments instead of reporting their swing")
    void volumeGateSuppressesTinySegments() {
        // trip_nodal = SHUTTLE is 244 trips across the quarter and showed a bogus -26.6pt swing.
        MetricSlice shuttle = metrics.measure("ota", "trip_nodal", "SHUTTLE", "2026-06");
        assertTrue(shuttle.sampleSize() < catalog.get("ota").minSample(),
                "expected SHUTTLE to be under the gate, saw " + shuttle.sampleSize() + " rows");
        assertNull(shuttle.value(), "a segment under the gate must not carry a value");
        assertFalse(shuttle.measured());

        // Suppressed, but not omitted: the attribution engine still needs its volume.
        assertTrue(metrics.slices("ota", "trip_nodal", "2026-06").stream()
                .anyMatch(s -> s.entity().equals("SHUTTLE")));
        assertFalse(metrics.series("ota", "trip_nodal", "2026-06").containsKey("SHUTTLE"));

        assertEquals(OptionalDouble.empty(), metrics.value("ota", "trip_nodal", "SHUTTLE", "2026-06"));
        assertEquals(MetricQueryService.CONFIDENCE_INSUFFICIENT_SAMPLE,
                metrics.observation("ota", "trip_nodal", "SHUTTLE", "2026-06").quality().confidence());
        assertNull(metrics.observation("ota", "trip_nodal", "SHUTTLE", "2026-06").value());
    }

    @Test
    @DisplayName("all four reference frames are present on every observation")
    void allFourFramesArePresent() {
        MetricObservation login = benchmarks.observe("ota", "trip_direction", "LOGIN", "2026-06");
        assertNotNull(login.references().trend());
        assertNotNull(login.references().sla());
        assertNotNull(login.references().peer());
        assertNotNull(login.references().industry());

        assertNotNull(login.references().trend().prior());
        assertEquals(-0.0517, login.references().trend().delta(), 0.001);

        assertEquals(0.95, login.references().sla().target());
        assertTrue(login.references().sla().breached());
        assertEquals(0.93, login.references().industry().benchmark());
        assertEquals("config:app.industry.ota", login.references().industry().source());

        assertNotNull(login.references().peer().cohortMedian());
        assertEquals("2 of 2", login.references().peer().rank());
        assertEquals(0.0, login.references().peer().percentile(), 1e-9);
        assertTrue(login.severity() > 0.0 && login.severity() <= 1.0);
    }

    @Test
    @DisplayName("a two-member dimension gets no z-score, and says why")
    void twoMemberCohortRefusesToScore() {
        // trip_direction has exactly two members. Three monthly periods cannot support a temporal
        // MAD, and a cohort of two cannot support a cross-sectional one either. The honest answer is
        // no score — the comparison still reaches the reader through the peer frame, which ranks
        // LOGIN 2 of 2. Manufacturing a z out of two points would be the easy, wrong alternative.
        MetricObservation login = benchmarks.observe("ota", "trip_direction", "LOGIN", "2026-06");
        assertNull(login.references().trend().robustZ());
        assertTrue(login.quality().caveats().stream().anyMatch(c -> c.contains("Robust z unavailable")),
                "an unavailable z must explain itself: " + login.quality().caveats());
    }

    @Test
    @DisplayName("a wide dimension falls back to a cross-sectional z and records the basis")
    void wideCohortFallsBackCrossSectionally() {
        // 19 offices give the fallback a real distribution to work against.
        MetricObservation denver = benchmarks.observe("ota", "office", "Denver Office", "2026-06");
        assertNotNull(denver.references().trend().robustZ());
        assertTrue(denver.references().trend().robustZ() < 0.0,
                "Denver fell 4.15 points; the z must carry that sign");
        assertTrue(denver.quality().caveats().stream().anyMatch(c -> c.contains("cross-sectionally")),
                "the fallback must be declared in the caveats: " + denver.quality().caveats());
        assertTrue(denver.severity() > 0.0);
    }

    @Test
    @DisplayName("frames that cannot be computed are present and null, never omitted")
    void unavailableFramesAreExplicit() {
        MetricObservation global = benchmarks.observe("occupancy", MetricSpec.GLOBAL, MetricSpec.ALL, "2026-06");
        assertNull(global.references().sla().target(), "occupancy has no configured target");
        assertFalse(global.references().sla().breached());
        assertNull(global.references().peer().cohortMedian(), "the global aggregate has no siblings");
        assertNull(global.references().industry().benchmark(), "occupancy has no industry benchmark");
        assertNotNull(global.references().trend().prior());
    }

    @Test
    @DisplayName("escort compliance reports its SLA but keeps it out of severity")
    void escortSlaIsAdvisory() {
        MetricObservation escort = benchmarks.observe("escort_compliance", MetricSpec.GLOBAL, MetricSpec.ALL, "2026-06");
        assertTrue(catalog.get("escort_compliance").slaAdvisory());
        assertEquals(1.0, escort.references().sla().target());
        assertTrue(escort.references().sla().breached());
        // Reported as breached, but a standing approximation must not pin severity at maximum.
        assertTrue(escort.severity() < 0.5, "advisory SLA leaked into severity: " + escort.severity());
    }

    @Test
    @DisplayName("history returns only periods that exist and never zero-pads")
    void historyIsHonest() {
        List<Double> history = metrics.history("ota", MetricSpec.GLOBAL, MetricSpec.ALL, "2026-07", 12);
        assertEquals(3, history.size());
        assertEquals(0.953141, history.get(0), TOLERANCE);
        assertEquals(0.946870, history.get(2), TOLERANCE);
        assertEquals(List.of("2026-05", "2026-06", "2026-07"), metrics.periods("ota"));
        assertEquals(Optional.of("2026-07"), metrics.latestPeriod("ota"));
    }

    @Test
    @DisplayName("peer ranking is direction-aware")
    void peerRankingRespectsDirection() {
        // Higher is better: the best office ranks 1 and sits at the 100th percentile.
        MetricObservation best = bestOn("ota", "office", "2026-06");
        assertTrue(best.references().peer().rank().startsWith("1 of "));
        assertEquals(100.0, best.references().peer().percentile(), 1e-9);
    }

    // ---- helpers --------------------------------------------------------------------------------

    private static double global(String metricId, String period) {
        return metrics.value(metricId, MetricSpec.GLOBAL, MetricSpec.ALL, period).orElseThrow(
                () -> new AssertionError("no value for " + metricId + " in " + period));
    }

    /** Period-over-period movement of a slice, in points. */
    private static double deltaPts(String metricId, String dimension, String entity) {
        double june = metrics.value(metricId, dimension, entity, "2026-06").orElseThrow();
        double may = metrics.value(metricId, dimension, entity, "2026-05").orElseThrow();
        return (june - may) * 100.0;
    }

    private static MetricObservation bestOn(String metricId, String dimension, String period) {
        Map<String, double[]> series = metrics.series(metricId, dimension, period);
        String winner = series.entrySet().stream()
                .max((a, b) -> Double.compare(a.getValue()[0], b.getValue()[0]))
                .orElseThrow()
                .getKey();
        return benchmarks.observe(metricId, dimension, winner, period);
    }
}
