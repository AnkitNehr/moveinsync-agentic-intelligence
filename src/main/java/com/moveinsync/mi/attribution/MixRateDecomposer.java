package com.moveinsync.mi.attribution;

import com.moveinsync.mi.model.Contribution;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Shift-share (mix-rate) variance decomposition of a period-over-period rate movement.
 *
 * <p>Splits an aggregate delta into, per entity, the part caused by that entity's own rate changing
 * and the part caused by that entity's share of volume changing. The two demand different responses:
 * a rate effect is a performance conversation with the entity, a mix effect is an allocation decision
 * about how work was routed. Reporting a single blended "contribution" conflates them and produces
 * narratives that recommend the wrong action.
 *
 * <h2>Formulas</h2>
 *
 * <pre>
 *   R0 = sum over v of  w0(v) * r0(v)          overall rate in the base period
 *
 *   rateEffect(v) = w1(v) * ( r1(v) - r0(v) )
 *   mixEffect(v)  = ( w1(v) - w0(v) ) * ( r0(v) - R0 )
 * </pre>
 *
 * where {@code w} is the entity's share of volume, {@code r} is the entity's rate, {@code 0} denotes
 * the base period and {@code 1} the current period.
 *
 * <h2>Why this variant reconciles exactly</h2>
 *
 * <p>Summing the two effects over all entities telescopes to the observed aggregate delta with no
 * residual term:
 *
 * <pre>
 *   sum[ w1(r1-r0) ] + sum[ (w1-w0)(r0-R0) ]
 *     = sum(w1 r1) - sum(w1 r0) + sum(w1 r0) - sum(w0 r0) - R0 * ( sum(w1) - sum(w0) )
 *     = R1 - R0 - R0 * ( 1 - 1 )
 *     = R1 - R0
 * </pre>
 *
 * <p>The cancellation depends on two things. First, the rate effect must be weighted by the
 * <em>current</em> share {@code w1}, not the base share {@code w0}: the common textbook form
 * {@code w0 * (r1 - r0)} leaves an unexplained cross term {@code sum[(w1-w0)(r1-r0)]} and only
 * reconciles approximately. Second, shares must sum to one in both periods, which is why
 * {@link #decompose} normalises the supplied weights rather than trusting them. Exact reconciliation
 * is what makes the output auditable, so both guarantees are enforced here rather than assumed.
 *
 * <h2>Entities present in only one period</h2>
 *
 * <p>A vendor that appears mid-quarter, or an office that stopped running trips, is treated as
 * {@code w = 0, r = 0} in the period where it is absent. The identity above still holds, and the
 * resulting contribution is the intuitive one: a new entity contributes {@code w1 * (r1 - R0)},
 * i.e. its volume times how far its rate sits from the old overall rate.
 *
 * <p>Framework-free and stateless by design, so it can be unit tested directly against the
 * reconciliation property without a Spring context.
 */
public final class MixRateDecomposer {

    /** Index of the rate component in the {@code double[]} pairs callers supply. */
    public static final int RATE = 0;

    /** Index of the weight component in the {@code double[]} pairs callers supply. */
    public static final int WEIGHT = 1;

    /**
     * Tolerance within which the decomposition is considered reconciled. Chosen to sit just above
     * accumulated IEEE-754 rounding for series of a few thousand entities, and well below any
     * movement that would be operationally meaningful.
     */
    public static final double TOLERANCE = 1e-9;

    private static final double EPSILON = 1e-12;

    /**
     * Decomposes the movement between two periods into per-entity rate and mix effects.
     *
     * <p>The two maps are keyed by entity, with values {@code {rate, weight}}. Weights are volume
     * measures — trip counts are the natural choice — and are normalised internally to shares, so
     * callers may pass raw counts or pre-computed shares interchangeably. The union of both key sets
     * is decomposed; an entity missing from either map is treated as absent volume at a zero rate.
     *
     * @param base    entity to {@code {rate, weight}} in the prior period
     * @param current entity to {@code {rate, weight}} in the current period
     * @return contributions sorted by absolute total contribution, largest first; never null
     */
    public List<Contribution> decompose(Map<String, double[]> base, Map<String, double[]> current) {
        Map<String, double[]> safeBase = base == null ? Map.of() : base;
        Map<String, double[]> safeCurrent = current == null ? Map.of() : current;

        Set<String> entities = new LinkedHashSet<>();
        entities.addAll(safeBase.keySet());
        entities.addAll(safeCurrent.keySet());
        if (entities.isEmpty()) {
            return List.of();
        }

        double baseWeightTotal = totalWeight(safeBase, entities);
        double currentWeightTotal = totalWeight(safeCurrent, entities);
        double overallBaseRate = baseRate(safeBase);

        List<Contribution> contributions = new ArrayList<>(entities.size());
        for (String entity : entities) {
            double r0 = rateOf(safeBase, entity);
            double r1 = rateOf(safeCurrent, entity);
            double w0 = share(safeBase, entity, baseWeightTotal);
            double w1 = share(safeCurrent, entity, currentWeightTotal);

            double rateEffect = w1 * (r1 - r0);
            double mixEffect = (w1 - w0) * (r0 - overallBaseRate);

            contributions.add(new Contribution(entity, rateEffect, mixEffect, rateEffect + mixEffect, w0, w1));
        }

        contributions.sort(Comparator
                .comparingDouble((Contribution c) -> -Math.abs(c.total()))
                .thenComparing(Contribution::entity));
        return List.copyOf(contributions);
    }

    /**
     * Absolute gap between the decomposition and the movement it claims to explain.
     *
     * <p>This is the acceptance property for the attribution engine. Two distinct gaps can show up
     * here and they mean different things. Against the delta implied by the same two maps
     * ({@link #impliedDelta}) the error is pure floating-point noise and must clear {@link #TOLERANCE};
     * anything larger is a bug. Against an independently reported aggregate delta the error is a
     * <em>coverage</em> signal — entities dropped for insufficient sample or an unparseable rate are
     * exactly the difference — and it belongs in the narrative as a caveat rather than being hidden.
     *
     * @param contributions output of {@link #decompose}
     * @param actualDelta   the aggregate movement being explained
     * @return absolute reconciliation error; {@code 0.0} for an empty decomposition of a zero delta
     */
    public double reconciliationError(List<Contribution> contributions, double actualDelta) {
        double explained = 0.0;
        if (contributions != null) {
            for (Contribution c : contributions) {
                explained += c.total();
            }
        }
        return Math.abs(explained - actualDelta);
    }

    /**
     * Overall rate in the base period, {@code R0 = sum over v of w0(v) * r0(v)}.
     *
     * <p>Derived from the supplied slices rather than accepted as a parameter. Taking it from an
     * outside source would let a caller pass an {@code R0} inconsistent with the entity rates and
     * silently break the reconciliation guarantee.
     *
     * @param base entity to {@code {rate, weight}} in the prior period
     * @return the share-weighted base rate, or {@code 0.0} when there is no base volume
     */
    public double baseRate(Map<String, double[]> base) {
        if (base == null || base.isEmpty()) {
            return 0.0;
        }
        double total = totalWeight(base, base.keySet());
        if (total <= EPSILON) {
            return 0.0;
        }
        double weighted = 0.0;
        for (Map.Entry<String, double[]> entry : base.entrySet()) {
            weighted += weightOf(entry.getValue()) * rateOf(entry.getValue());
        }
        return weighted / total;
    }

    /**
     * The aggregate movement implied by the two slice maps, {@code R1 - R0}.
     *
     * <p>Use this as the reference in {@link #reconciliationError} to assert the algebraic identity
     * in isolation, independent of any coverage gap against an externally reported total.
     *
     * @param base    entity to {@code {rate, weight}} in the prior period
     * @param current entity to {@code {rate, weight}} in the current period
     * @return current overall rate minus base overall rate
     */
    public double impliedDelta(Map<String, double[]> base, Map<String, double[]> current) {
        return baseRate(current) - baseRate(base);
    }

    /**
     * Convenience factory for a slice pair, mostly to keep test fixtures readable.
     *
     * @param rate   the entity's metric rate for the period
     * @param weight the entity's volume for the period
     * @return a {@code {rate, weight}} pair
     */
    public static double[] slice(double rate, double weight) {
        return new double[]{rate, weight};
    }

    private static double totalWeight(Map<String, double[]> slices, Set<String> entities) {
        double total = 0.0;
        for (String entity : entities) {
            total += weightOf(slices.get(entity));
        }
        return total;
    }

    private static double share(Map<String, double[]> slices, String entity, double totalWeight) {
        if (totalWeight <= EPSILON) {
            return 0.0;
        }
        return weightOf(slices.get(entity)) / totalWeight;
    }

    private static double rateOf(Map<String, double[]> slices, String entity) {
        return rateOf(slices.get(entity));
    }

    /** Absent entity, malformed pair, or a non-finite rate all resolve to a zero rate. */
    private static double rateOf(double[] pair) {
        if (pair == null || pair.length <= RATE || !Double.isFinite(pair[RATE])) {
            return 0.0;
        }
        return pair[RATE];
    }

    /**
     * Absent entity, malformed pair, or a non-finite weight resolve to zero volume. Negative weights
     * are clamped to zero: this dataset carries physically impossible negatives (emp_data km reaches
     * -6.63), and letting one through would corrupt the share normalisation for every other entity.
     */
    private static double weightOf(double[] pair) {
        if (pair == null || pair.length <= WEIGHT || !Double.isFinite(pair[WEIGHT])) {
            return 0.0;
        }
        return Math.max(0.0, pair[WEIGHT]);
    }
}
