package com.moveinsync.mi.metric;

import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.policy.SlaPolicy;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Catalog tests that need no dataset, so they run on every build.
 *
 * <p>The shipped YAML is parsed and validated here. A mistyped key, a grain with no column, or a
 * {@code segment_by} without valid values fails the build in under a second rather than surfacing
 * as a silently missing metric during a 06:00 agent run.
 */
@DisplayName("Metric catalog")
class MetricCatalogTest {

    private final MetricCatalog catalog = new MetricCatalog();

    @Test
    @DisplayName("ships exactly the eight metrics, all valid")
    void shipsEightValidMetrics() {
        assertEquals(
                List.of("cost_per_km", "cost_per_trip", "delay_p90", "driver_noncompliance",
                        "escort_compliance", "noshow_rate", "occupancy", "ota"),
                catalog.ids());
        catalog.all().forEach(MetricDefinition::validate);
        assertEquals(8, catalog.size());
    }

    @Test
    @DisplayName("every metric declares a global grain, a direction and a positive gate")
    void everyMetricIsScannable() {
        for (MetricDefinition definition : catalog.all()) {
            assertTrue(definition.grains().contains(MetricSpec.GLOBAL), definition.id() + " has no global grain");
            assertTrue(definition.minSample() > 0, definition.id() + " has no volume gate");
            assertNotNull(definition.formula(), definition.id() + " has no formula");
            assertFalse(definition.caveats().isEmpty(), definition.id() + " declares no data-quality caveats");
            assertTrue(definition.higherIsBetter() || MetricSpec.LOWER_IS_BETTER.equals(definition.direction()));
        }
    }

    @Test
    @DisplayName("every declared SLA key has a rule behind it in the policy engine")
    void slaKeysAreWired() {
        SlaPolicy policy = new SlaPolicy(0.95, 1.0, 15, 25.0);
        List<String> withSla = catalog.all().stream()
                .filter(d -> d.slaKey() != null)
                .map(MetricDefinition::id)
                .toList();
        assertEquals(List.of("cost_per_km", "escort_compliance", "ota"), withSla);
        // A declared target with no rule behind it is an unarmed SLA that looks identical to a
        // metric which legitimately has none. That must not ship.
        withSla.forEach(id -> assertTrue(policy.ruleFor(id).isPresent(), "no SLA rule for " + id));
    }

    @Nested
    @DisplayName("cost_per_km regime guard")
    class CostPerKmGuard {

        @Test
        @DisplayName("is declared, and billing_regime is not also a grain")
        void guardIsDeclared() {
            MetricDefinition definition = catalog.get("cost_per_km");
            assertEquals("billing_regime", definition.segmentBy());
            assertEquals(List.of("DISTANCE_BASED"), definition.validSegments());
            // Slicing by the column that decides whether the metric is defined would emit a
            // FIXED_RATE row whose cost per km is 4,947 and meaningless.
            assertFalse(definition.grains().contains("billing_regime"));
        }

        @Test
        @DisplayName("cost_per_trip is defined everywhere, so it may slice on regime")
        void costPerTripHasNoGuard() {
            MetricDefinition definition = catalog.get("cost_per_trip");
            assertNull(definition.segmentBy());
            assertTrue(definition.grains().contains("billing_regime"));
        }
    }

    @Nested
    @DisplayName("validation")
    class Validation {

        @Test
        @DisplayName("rejects a segment_by with no valid segments")
        void rejectsUnguardedSegment() {
            IllegalStateException e = assertThrows(IllegalStateException.class,
                    () -> definitionWithSegment("billing_regime", List.of()).validate());
            assertTrue(e.getMessage().contains("valid_segments"));
        }

        @Test
        @DisplayName("rejects a grain that is not an identifier")
        void rejectsInjectedGrain() {
            IllegalStateException e = assertThrows(IllegalStateException.class,
                    () -> definition(List.of(MetricSpec.GLOBAL, "office; DROP TABLE trips")).validate());
            assertTrue(e.getMessage().contains("not an identifier"));
        }

        @Test
        @DisplayName("rejects a metric with no global grain")
        void rejectsMissingGlobal() {
            assertThrows(IllegalStateException.class, () -> definition(List.of("office")).validate());
        }

        private MetricDefinition definition(List<String> grains) {
            return new MetricDefinition("probe", "Probe", null, 1, "trips", "avg(on_time)", null,
                    "month", MetricSpec.HIGHER_IS_BETTER, "rate", true, null, false, null,
                    500, grains, null, null, null, null, List.of(), List.of());
        }

        private MetricDefinition definitionWithSegment(String segmentBy, List<String> valid) {
            return new MetricDefinition("probe", "Probe", null, 1, "trips", "avg(on_time)", null,
                    "month", MetricSpec.HIGHER_IS_BETTER, "rate", true, null, false, null,
                    500, List.of(MetricSpec.GLOBAL), null, segmentBy, valid, null, List.of(), List.of());
        }
    }

    @Test
    @DisplayName("unknown metric ids fail loudly and list what does exist")
    void unknownMetricFailsUsefully() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> catalog.get("otaa"));
        assertTrue(e.getMessage().contains("ota"), e.getMessage());
        assertTrue(catalog.find("otaa").isEmpty());
        assertEquals(List.of(), catalog.grainsFor("otaa"));
    }
}
