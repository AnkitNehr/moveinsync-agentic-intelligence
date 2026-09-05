package com.moveinsync.mi.attribution;

import com.moveinsync.mi.model.Contribution;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.moveinsync.mi.attribution.MixRateDecomposer.slice;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Reconciliation is the acceptance test for the attribution engine.
 *
 * <p>A decomposition that does not sum to the movement it claims to explain is not an approximation,
 * it is a fabrication — every narrative built on it would attribute points that went somewhere else.
 * The tolerance here is {@code 1e-9}, which is floating-point noise, not an engineering allowance:
 * the identity is exact, so anything larger indicates a genuine defect rather than accumulated error.
 */
class MixRateDecomposerTest {

    private static final double TOLERANCE = 1e-9;

    private final MixRateDecomposer decomposer = new MixRateDecomposer();

    /** Asserts the core identity: the contributions account for the movement, exactly. */
    private void assertReconciles(Map<String, double[]> base, Map<String, double[]> current) {
        List<Contribution> contributions = decomposer.decompose(base, current);
        double impliedDelta = decomposer.impliedDelta(base, current);

        assertThat(decomposer.reconciliationError(contributions, impliedDelta))
                .as("sum of rate and mix effects must equal R1 - R0")
                .isLessThan(TOLERANCE);

        double summed = contributions.stream().mapToDouble(Contribution::total).sum();
        assertThat(summed).isCloseTo(impliedDelta, within(TOLERANCE));

        // Each contribution's own total must be internally consistent too.
        for (Contribution c : contributions) {
            assertThat(c.total())
                    .as("total must equal rateEffect + mixEffect for %s", c.entity())
                    .isCloseTo(c.rateEffect() + c.mixEffect(), within(TOLERANCE));
        }
    }

    @Nested
    @DisplayName("reconciliation")
    class Reconciliation {

        @Test
        @DisplayName("contributions sum to the delta for a plain two-entity movement")
        void reconcilesTwoEntities() {
            Map<String, double[]> base = Map.of(
                    "LOGIN", slice(0.9340, 46_800),
                    "LOGOUT", slice(0.9700, 53_200));
            Map<String, double[]> current = Map.of(
                    "LOGIN", slice(0.8823, 47_270),
                    "LOGOUT", slice(0.9623, 52_730));

            assertReconciles(base, current);
        }

        @Test
        @DisplayName("contributions sum to the delta across a 23-vendor cohort")
        void reconcilesLargeCohort() {
            Map<String, double[]> base = new LinkedHashMap<>();
            Map<String, double[]> current = new LinkedHashMap<>();
            for (int i = 0; i < 23; i++) {
                double baseRate = 0.90 + (i % 7) * 0.012;
                base.put("V" + i, slice(baseRate, 4_000 + i * 137));
                current.put("V" + i, slice(baseRate - 0.02 - (i % 3) * 0.004, 4_050 + i * 131));
            }

            assertReconciles(base, current);
        }

        @Test
        @DisplayName("reconciles when rates are identical and only volume moves")
        void reconcilesPureMixShift() {
            Map<String, double[]> base = Map.of(
                    "AUTO", slice(0.965, 70_000),
                    "MANUAL", slice(0.905, 30_000));
            Map<String, double[]> current = Map.of(
                    "AUTO", slice(0.965, 55_000),
                    "MANUAL", slice(0.905, 45_000));

            assertReconciles(base, current);

            List<Contribution> contributions = decomposer.decompose(base, current);
            assertThat(contributions)
                    .as("no entity changed its rate, so every rate effect must be zero")
                    .allSatisfy(c -> assertThat(c.rateEffect()).isCloseTo(0.0, within(TOLERANCE)));
            assertThat(contributions)
                    .as("the entire movement must land in mix effects")
                    .anySatisfy(c -> assertThat(Math.abs(c.mixEffect())).isGreaterThan(1e-4));
        }

        @Test
        @DisplayName("reconciles when volume is identical and only rates move")
        void reconcilesPureRateShift() {
            Map<String, double[]> base = Map.of(
                    "BUS", slice(0.9420, 40_000),
                    "CAB", slice(0.9600, 60_000));
            Map<String, double[]> current = Map.of(
                    "BUS", slice(0.8795, 40_000),
                    "CAB", slice(0.9380, 60_000));

            assertReconciles(base, current);

            assertThat(decomposer.decompose(base, current))
                    .as("shares are unchanged, so every mix effect must be exactly zero")
                    .allSatisfy(c -> assertThat(c.mixEffect()).isEqualTo(0.0));
        }
    }

    @Nested
    @DisplayName("entities present in only one period")
    class PartialPresence {

        @Test
        @DisplayName("reconciles when an entity is absent from the base period")
        void reconcilesNewEntity() {
            Map<String, double[]> base = Map.of(
                    "vanta-Sea", slice(0.951, 60_000),
                    "pinnacle-Slc", slice(0.944, 40_000));
            Map<String, double[]> current = Map.of(
                    "vanta-Sea", slice(0.9095, 58_000),
                    "pinnacle-Slc", slice(0.9128, 38_000),
                    "catalyst-Sac", slice(0.9490, 9_000));

            assertReconciles(base, current);

            Contribution entrant = contributionFor(base, current, "catalyst-Sac");
            assertThat(entrant.shareBefore()).isEqualTo(0.0);
            assertThat(entrant.shareAfter()).isGreaterThan(0.0);
            // A new entity is treated as w=0, r=0 in the base period, which makes its total
            // contribution w1 * (r1 - R0): its volume times how far it sits from the old overall rate.
            double baseRate = decomposer.baseRate(base);
            assertThat(entrant.total())
                    .isCloseTo(entrant.shareAfter() * (0.9490 - baseRate), within(TOLERANCE));
        }

        @Test
        @DisplayName("reconciles when an entity is absent from the current period")
        void reconcilesDepartedEntity() {
            Map<String, double[]> base = Map.of(
                    "Denver", slice(0.9502, 30_000),
                    "Clearwater Campus", slice(0.9488, 25_000),
                    "SPOT_2.0", slice(0.8100, 700));
            Map<String, double[]> current = Map.of(
                    "Denver", slice(0.9087, 31_000),
                    "Clearwater Campus", slice(0.9081, 25_500));

            assertReconciles(base, current);

            Contribution departed = contributionFor(base, current, "SPOT_2.0");
            assertThat(departed.shareAfter()).isEqualTo(0.0);
            assertThat(departed.rateEffect())
                    .as("an absent entity has zero current weight, so no rate effect")
                    .isEqualTo(0.0);
        }

        @Test
        @DisplayName("reconciles when both periods have disjoint entity sets")
        void reconcilesDisjointSets() {
            Map<String, double[]> base = Map.of("OLD_A", slice(0.95, 1_000), "OLD_B", slice(0.91, 500));
            Map<String, double[]> current = Map.of("NEW_A", slice(0.88, 900), "NEW_B", slice(0.93, 700));

            assertReconciles(base, current);
            assertThat(decomposer.decompose(base, current)).hasSize(4);
        }
    }

    @Nested
    @DisplayName("weight handling")
    class Weights {

        @Test
        @DisplayName("raw trip counts and pre-normalised shares produce identical contributions")
        void normalisesWeights() {
            Map<String, double[]> baseCounts = Map.of("A", slice(0.90, 40_000), "B", slice(0.96, 60_000));
            Map<String, double[]> currentCounts = Map.of("A", slice(0.87, 45_000), "B", slice(0.95, 55_000));
            Map<String, double[]> baseShares = Map.of("A", slice(0.90, 0.4), "B", slice(0.96, 0.6));
            Map<String, double[]> currentShares = Map.of("A", slice(0.87, 0.45), "B", slice(0.95, 0.55));

            List<Contribution> fromCounts = decomposer.decompose(baseCounts, currentCounts);
            List<Contribution> fromShares = decomposer.decompose(baseShares, currentShares);

            assertThat(fromCounts).hasSameSizeAs(fromShares);
            for (int i = 0; i < fromCounts.size(); i++) {
                assertThat(fromCounts.get(i).entity()).isEqualTo(fromShares.get(i).entity());
                assertThat(fromCounts.get(i).total())
                        .isCloseTo(fromShares.get(i).total(), within(TOLERANCE));
            }
        }

        @Test
        @DisplayName("shares sum to one in each period")
        void sharesSumToOne() {
            Map<String, double[]> base = Map.of("A", slice(0.9, 10), "B", slice(0.8, 30), "C", slice(0.7, 60));
            Map<String, double[]> current = Map.of("A", slice(0.9, 20), "B", slice(0.8, 20), "C", slice(0.7, 60));

            List<Contribution> contributions = decomposer.decompose(base, current);
            assertThat(contributions.stream().mapToDouble(Contribution::shareBefore).sum())
                    .isCloseTo(1.0, within(TOLERANCE));
            assertThat(contributions.stream().mapToDouble(Contribution::shareAfter).sum())
                    .isCloseTo(1.0, within(TOLERANCE));
        }

        @Test
        @DisplayName("negative and non-finite weights are neutralised rather than corrupting shares")
        void guardsBadWeights() {
            // emp_data carries physically impossible negative distances; a negative weight leaking
            // into the normaliser would distort every other entity's share.
            Map<String, double[]> base = new HashMap<>();
            base.put("GOOD", slice(0.95, 1_000));
            base.put("NEGATIVE", slice(0.50, -6.63));
            base.put("NAN", slice(0.50, Double.NaN));
            Map<String, double[]> current = Map.of("GOOD", slice(0.91, 1_000), "NEGATIVE", slice(0.50, 0));

            assertReconciles(base, current);

            List<Contribution> contributions = decomposer.decompose(base, current);
            assertThat(contributions)
                    .filteredOn(c -> c.entity().equals("GOOD"))
                    .allSatisfy(c -> assertThat(c.shareBefore()).isCloseTo(1.0, within(TOLERANCE)));
        }
    }

    @Nested
    @DisplayName("rate versus mix separation")
    class RateVersusMix {

        @Test
        @DisplayName("a near-static vendor mix produces a mix effect of approximately zero")
        void vendorMixIsNegligible() {
            // This is the case that justifies scanning every dimension. Vendor volume share barely
            // moves between May and June — the largest shift across 23 vendors is 0.79 points — so
            // the mix effect is negligible and a mix-shift narrative would be invented.
            Map<String, double[]> base = new LinkedHashMap<>();
            Map<String, double[]> current = new LinkedHashMap<>();
            for (int i = 0; i < 23; i++) {
                double rate = 0.953 - (i % 5) * 0.004;
                base.put("vendor-" + i, slice(rate, 8_000));
                // A 0.79-point share shift on the largest vendor, everything else static.
                double currentWeight = i == 0 ? 8_000 * 1.0079 : 8_000;
                current.put("vendor-" + i, slice(rate - 0.0285, currentWeight));
            }

            assertReconciles(base, current);

            List<Contribution> contributions = decomposer.decompose(base, current);
            double totalMix = contributions.stream().mapToDouble(Contribution::mixEffect).sum();
            double totalRate = contributions.stream().mapToDouble(Contribution::rateEffect).sum();

            assertThat(Math.abs(totalMix))
                    .as("mix effect must be negligible when volume share is static")
                    .isLessThan(0.0005);
            assertThat(Math.abs(totalRate))
                    .as("the movement is entirely rate-driven")
                    .isGreaterThan(0.02);
        }

        @Test
        @DisplayName("the dominant contributor is the entity that both moved and carries volume")
        void dominantContributorIsRanked() {
            // LOGIN falls 5.17 points against LOGOUT's 0.77 on comparable volume, so LOGIN must
            // rank first. Contributions are returned ordered by absolute total.
            Map<String, double[]> base = Map.of(
                    "LOGIN", slice(0.9340, 46_800),
                    "LOGOUT", slice(0.9700, 53_200));
            Map<String, double[]> current = Map.of(
                    "LOGIN", slice(0.8823, 47_270),
                    "LOGOUT", slice(0.9623, 52_730));

            List<Contribution> contributions = decomposer.decompose(base, current);

            assertThat(contributions.getFirst().entity()).isEqualTo("LOGIN");
            assertThat(Math.abs(contributions.getFirst().total()))
                    .isGreaterThan(Math.abs(contributions.get(1).total()));
        }
    }

    @Nested
    @DisplayName("degenerate input")
    class Degenerate {

        @Test
        @DisplayName("empty and null inputs produce an empty decomposition")
        void handlesEmptyInput() {
            assertThat(decomposer.decompose(Map.of(), Map.of())).isEmpty();
            assertThat(decomposer.decompose(null, null)).isEmpty();
            assertThat(decomposer.reconciliationError(List.of(), 0.0)).isZero();
        }

        @Test
        @DisplayName("a period with no volume yields a zero base rate rather than a division by zero")
        void handlesZeroVolume() {
            Map<String, double[]> base = Map.of("A", slice(0.95, 0));
            Map<String, double[]> current = Map.of("A", slice(0.91, 1_000));

            assertThat(decomposer.baseRate(base)).isZero();
            assertReconciles(base, current);
        }

        @Test
        @DisplayName("reconciliation error reports the coverage gap against an external delta")
        void reportsCoverageGap() {
            // Entities dropped by the volume gate are exactly the difference between the decomposed
            // delta and the reported aggregate delta. That gap is a coverage caveat for the narrative,
            // not an error to hide.
            Map<String, double[]> base = Map.of("A", slice(0.95, 50_000), "B", slice(0.93, 50_000));
            Map<String, double[]> current = Map.of("A", slice(0.92, 50_000), "B", slice(0.91, 50_000));

            List<Contribution> contributions = decomposer.decompose(base, current);
            double reportedAggregateDelta = -0.0285;

            assertThat(decomposer.reconciliationError(contributions, reportedAggregateDelta))
                    .isGreaterThan(TOLERANCE)
                    .isLessThan(0.01);
        }
    }

    private Contribution contributionFor(
            Map<String, double[]> base, Map<String, double[]> current, String entity) {
        return decomposer.decompose(base, current).stream()
                .filter(c -> c.entity().equals(entity))
                .findFirst()
                .orElseThrow(() -> new AssertionError("no contribution for " + entity));
    }
}
