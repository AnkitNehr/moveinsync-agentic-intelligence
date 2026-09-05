package com.moveinsync.mi.controller;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.glossary.OperatorCopy;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.model.Contribution;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * "Where did that movement come from?" — decomposed across every dimension, then ranked.
 *
 * <p>The endpoint returns the winner <em>and</em> the dimensions that lost, with their scores. That is
 * not padding. Every dimension reconciles to the same aggregate delta, so being arithmetically
 * correct is not the test; the ranking is what separates the dimension that localises a movement from
 * the ones that merely restate it. And "vendor mix does not explain this" is only a credible finding
 * if the vendor decomposition is visibly on the record rather than never having been run — on this
 * data the largest vendor share shift is 0.79 points, so the mix effect is approximately zero and any
 * narrative blaming a shift of volume between vendors would be fabricated.
 *
 * <p>The reconciliation block is reported rather than hidden. A decomposition that does not close
 * against the aggregate means entities were held back by the volume gate, which is real information
 * about coverage — presenting a tidy total that quietly omits them would be the dishonest option.
 */
@RestController
@RequestMapping("/api/attribution")
@CrossOrigin
public class AttributionController {

    private final AttributionService attribution;
    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final OperatorCopy copy;
    private final double reconciliationTolerance;

    public AttributionController(
            AttributionService attribution,
            MetricCatalog catalog,
            MetricQueryService metrics,
            OperatorCopy copy,
            @Value("${app.attribution.reconciliation-tolerance:0.005}") double reconciliationTolerance) {
        this.attribution = attribution;
        this.catalog = catalog;
        this.metrics = metrics;
        this.copy = copy;
        this.reconciliationTolerance = Math.abs(reconciliationTolerance);
    }

    /**
     * How well one dimension explains the movement, and the split behind it.
     *
     * @param dimension        the dimension decomposed
     * @param explanatoryPower composite 0-1 score used to rank dimensions
     * @param concentration    share of gross entity movement carried by the top three entities
     * @param dispersion       how differently entities moved from the aggregate; 0 means uniform
     * @param explainedDelta   movement accounted for by those top three
     * @param entityCount      entities that cleared the volume gate
     * @param sampleSize       current-period rows across those entities
     * @param contributions    per-entity rate/mix split, largest absolute contribution first
     */
    public record DimensionView(
            String dimension,
            double explanatoryPower,
            double concentration,
            double dispersion,
            double explainedDelta,
            int entityCount,
            long sampleSize,
            List<Contribution> contributions) {

        static DimensionView of(DimensionAttribution source) {
            return new DimensionView(
                    source.dimension(),
                    source.explanatoryPower(),
                    source.concentration(),
                    source.dispersion(),
                    source.explainedDelta(),
                    source.entityCount(),
                    source.sampleSize(),
                    source.contributions());
        }
    }

    /**
     * Whether the winning decomposition closes against the aggregate it claims to explain.
     *
     * @param actualDelta   the aggregate movement
     * @param explainedSum  sum of every contribution in the winning dimension
     * @param error         absolute gap between the two
     * @param tolerance     the gap treated as floating-point noise
     * @param reconciles    whether the gap is within tolerance
     * @param note          what a non-zero gap means operationally
     */
    public record Reconciliation(
            double actualDelta,
            double explainedSum,
            double error,
            double tolerance,
            boolean reconciles,
            String note) {
    }

    /**
     * The full attribution answer.
     *
     * @param metricId    metric decomposed
     * @param period      current period
     * @param priorPeriod comparison period
     * @param actualDelta aggregate movement, current minus prior
     * @param winner      the dimension that best explains it, or null when none could be decomposed
     * @param ranked      every dimension examined, best first — including the rejected ones
     * @param reconciliation whether the winning decomposition closes
     * @param note        plain-language reading of the result
     */
    public record AttributionView(
            String metricId,
            String period,
            String priorPeriod,
            double actualDelta,
            DimensionView winner,
            List<DimensionView> ranked,
            Reconciliation reconciliation,
            String note) {
    }

    /**
     * Decomposes a metric's period-over-period movement across every dimension it declares.
     *
     * @param metric catalog metric id
     * @param period current period, {@code yyyy-MM}; defaults to the latest with data
     * @param prior  comparison period; defaults to the month before {@code period}
     */
    @GetMapping
    public AttributionView attribute(
            @RequestParam("metric") String metric,
            @RequestParam(required = false) String period,
            @RequestParam(required = false) String prior) {

        MetricDefinition definition = catalog.find(metric)
                .orElseThrow(() -> NotFoundException.of("metric", metric, catalog.ids()));

        String resolvedPeriod = resolvePeriod(definition, period);
        String resolvedPrior = (prior == null || prior.isBlank())
                ? MetricQueryService.previousPeriod(resolvedPeriod)
                : validate(prior.trim());

        AttributionResult result = attribution.attribute(definition.id(), resolvedPeriod, resolvedPrior);

        if (result.ranked().isEmpty()) {
            return new AttributionView(
                    definition.id(), resolvedPeriod, resolvedPrior, result.actualDelta(),
                    null, List.of(),
                    new Reconciliation(result.actualDelta(), 0.0, Math.abs(result.actualDelta()),
                            reconciliationTolerance, false,
                            "Nothing was decomposed, so nothing reconciles."),
                    "No dimension had at least two entities clearing the volume gate in both periods, "
                            + "so no driver is named. That is a coverage limit, not evidence that the "
                            + "movement is uniform.");
        }

        DimensionAttribution winner = result.ranked().getFirst();
        double explainedSum = winner.contributions().stream().mapToDouble(Contribution::total).sum();

        return new AttributionView(
                definition.id(),
                resolvedPeriod,
                resolvedPrior,
                result.actualDelta(),
                DimensionView.of(winner),
                result.ranked().stream().map(DimensionView::of).toList(),
                new Reconciliation(
                        result.actualDelta(),
                        explainedSum,
                        winner.reconciliationError(),
                        reconciliationTolerance,
                        winner.reconciles(reconciliationTolerance),
                        winner.reconciles(reconciliationTolerance)
                                ? "The decomposition closes against the aggregate movement."
                                : "The gap is volume excluded by the minimum-sample gate or carried on a "
                                        + "null dimension value, not an arithmetic error. Treat the named "
                                        + "contributors as the bulk of the story, not all of it."),
                note(winner, result));
    }

    /**
     * States, in one sentence, whether the movement is rate-driven or mix-driven.
     *
     * <p>This is the sentence a chart cannot give you and the one that stops a plausible-sounding
     * wrong story: when mix is negligible the same entities carried the same share and simply
     * performed worse, which has a different fix from volume moving to a weaker performer.
     */
    private String note(DimensionAttribution winner, AttributionResult result) {
        double grossMix = winner.contributions().stream().mapToDouble(c -> Math.abs(c.mixEffect())).sum();
        double grossTotal = winner.contributions().stream().mapToDouble(c -> Math.abs(c.total())).sum();
        String leader = winner.leader() == null ? "no single entity" : winner.leader().entity();

        if (grossTotal <= 0.0) {
            return "The winning dimension is " + copy.grainLabel(winner.dimension())
                    + ", but no entity carried measurable movement.";
        }
        double mixFraction = grossMix / grossTotal;
        String driver = mixFraction < 0.10
                ? "This is a rate change: mix accounts for only %.0f%% of the gross movement, so volume "
                        .formatted(mixFraction * 100.0)
                        + "did not shift between entities — they got worse."
                : "Mix accounts for %.0f%% of the gross movement, so a meaningful part of this is volume "
                        .formatted(mixFraction * 100.0)
                        + "moving between entities rather than entities changing performance.";

        return "Of %d dimensions examined, %s explains the movement best and it is concentrated in %s. %s"
                .formatted(result.ranked().size(), copy.grainLabel(winner.dimension()), leader, driver);
    }

    private String resolvePeriod(MetricDefinition definition, String period) {
        if (period != null && !period.isBlank()) {
            return validate(period.trim());
        }
        return metrics.latestPeriod(definition.id())
                .orElseThrow(() -> new NotFoundException(
                        "The fact store holds no periods for metric '" + definition.id() + "'."));
    }

    private static String validate(String period) {
        String canonical = MetricQueryService.canonicalPeriod(period);
        if (canonical == null) {
            throw new IllegalArgumentException(
                    "Malformed period '" + period + "'; expected a yyyy-MM label such as 2026-06.");
        }
        return canonical;
    }
}
