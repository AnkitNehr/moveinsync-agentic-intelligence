package com.moveinsync.mi.pipeline.fallback;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.spi.ReasoningPort;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Explains a movement from the attribution arithmetic, with no model in the loop.
 *
 * <p>The explanation is assembled from four things the deterministic core already computed: the
 * winning dimension and how well it explains the aggregate, the shift-share split of the leading
 * contributors, the dimensions that were examined and rejected, and the reconciliation error. That
 * last one matters more than it looks — a decomposition that does not close against the aggregate
 * means entities were excluded by the volume gate, and saying so is more honest than presenting a
 * tidy total that quietly omits them.
 *
 * <p>The rate/mix split is the part a chart cannot give you. In the June OTA drop the vendor mix
 * barely moves — the largest share shift across 23 vendors is 0.79 points, so the mix effect is
 * essentially zero and the entire movement is rate-driven. Any narrative blaming "volume shifting to
 * a worse vendor" would be fabricated, and this stage is where that gets stated rather than assumed.
 *
 * <p>What it deliberately does not do is assert a cause. It says which slices carry the movement and
 * which explanations the data rules out; naming a root cause requires context the extracts do not
 * contain, and inventing one is the failure mode this whole design exists to prevent.
 */
@Service
public class DeterministicReasoner implements ReasoningPort {

    /** Leading contributors named explicitly in the explanation. */
    private static final int NAMED_CONTRIBUTORS = 3;

    /** Rejected dimensions listed as having been checked. */
    private static final int NAMED_REJECTIONS = 4;

    /**
     * Below this fraction of the aggregate movement, a mix effect is reported as negligible rather
     * than quoted. The threshold exists so that arithmetic noise is not narrated as a finding.
     */
    private static final double MIX_NEGLIGIBLE_FRACTION = 0.10;

    private final MetricFormat format;
    private final double reconciliationTolerance;

    public DeterministicReasoner(
            MetricFormat format,
            @Value("${app.attribution.reconciliation-tolerance:0.005}") double reconciliationTolerance) {
        this.format = format;
        this.reconciliationTolerance = Math.abs(reconciliationTolerance);
    }

    @Override
    public Explanation explain(
            TriagePort.IncidentDraft draft, List<Finding> findings, AttributionResult attribution) {

        if (findings == null || findings.isEmpty()) {
            return new Explanation(
                    "No findings survived ranking for this draft, so there is nothing to explain.",
                    List.of(),
                    null);
        }

        Finding lead = findings.getFirst();
        StringBuilder prose = new StringBuilder();
        List<Evidence> evidence = new ArrayList<>();

        appendMovement(prose, evidence, lead);
        appendReferences(prose, evidence, lead);
        appendCorrelatedSlices(prose, evidence, findings);
        String hypothesis = appendAttribution(prose, evidence, lead, attribution);
        appendQuality(prose, lead);

        return new Explanation(prose.toString().trim(), evidence, hypothesis);
    }

    @Override
    public String tier() {
        return "deterministic";
    }

    // ---- section 1: what moved -------------------------------------------------------------------

    private void appendMovement(StringBuilder prose, List<Evidence> evidence, Finding lead) {
        String claim = "%s on %s=%s %s from %s in %s to %s in %s (%s) across %,d trips.".formatted(
                format.label(lead.metricId()),
                lead.dimension(),
                lead.entity(),
                format.movement(lead.deltaPts()),
                format.value(lead.metricId(), lead.prior()),
                lead.priorPeriod(),
                format.value(lead.metricId(), lead.current()),
                lead.period(),
                format.delta(lead.metricId(), lead.deltaPts()),
                lead.sampleSize());

        prose.append(claim).append(' ');
        evidence.add(new Evidence(claim, lead.metricId(), lead.entity()));
    }

    // ---- section 2: the four reference frames ----------------------------------------------------

    private void appendReferences(StringBuilder prose, List<Evidence> evidence, Finding lead) {
        if (lead.observation() == null || lead.observation().references() == null) {
            return;
        }
        var references = lead.observation().references();

        Sla sla = references.sla();
        if (sla != null && sla.target() != null) {
            String claim = sla.breached()
                    ? "This breaches the configured target of %s.".formatted(
                            format.value(lead.metricId(), sla.target()))
                    : "This still clears the configured target of %s.".formatted(
                            format.value(lead.metricId(), sla.target()));
            prose.append(claim).append(' ');
            evidence.add(new Evidence(claim, lead.metricId(), lead.entity()));
        }

        Peer peer = references.peer();
        if (peer != null && peer.cohortMedian() != null && peer.rank() != null) {
            String claim = "Against its cohort on the same dimension it ranks %s, with a cohort median of %s."
                    .formatted(peer.rank(), format.value(lead.metricId(), peer.cohortMedian()));
            prose.append(claim).append(' ');
            evidence.add(new Evidence(claim, lead.metricId(), lead.entity()));
        }

        Industry industry = references.industry();
        if (industry != null && industry.benchmark() != null) {
            String claim = "The published benchmark is %s%s.".formatted(
                    format.value(lead.metricId(), industry.benchmark()),
                    industry.source() == null ? "" : " (" + industry.source() + ")");
            prose.append(claim).append(' ');
            evidence.add(new Evidence(claim, lead.metricId(), lead.entity()));
        }

        Trend trend = references.trend();
        if (trend != null && trend.robustZ() != null && Double.isFinite(trend.robustZ())) {
            // Stated as a comparison rather than as a statistic. The reader needs to know how unusual
            // this is; "3.2 robust z" answers that only for someone who already knows the units.
            // Three bands, not two. The earlier version had no lower bound, so a finding admitted by
            // the material-delta route rather than the z route — AnomalyScanner.significant permits
            // exactly that — could carry z = 0.3 and still be described as "larger than usual". That
            // is a false claim where the text it replaced (the literal z) was at least accurate, and
            // it disagreed with the sibling ladder in BuiltInChatRouter about the same score.
            double z = Math.abs(trend.robustZ());
            String claim = z >= 3
                    ? "This is far outside what this measure normally does month to month."
                    : z >= 2
                            ? "This is a larger move than this measure usually makes month to month."
                            : "This sits within what this measure normally does month to month; it "
                                    + "is surfaced for the size of the movement, not its rarity.";
            prose.append(claim).append(' ');
            evidence.add(new Evidence(claim, lead.metricId(), lead.entity()));
        }
    }

    // ---- section 3: the correlated slices --------------------------------------------------------

    private void appendCorrelatedSlices(StringBuilder prose, List<Evidence> evidence, List<Finding> findings) {
        if (findings.size() < 2) {
            return;
        }
        String slices = findings.stream()
                .skip(1)
                .map(f -> "%s=%s at %s".formatted(
                        f.dimension(), f.entity(), format.delta(f.metricId(), f.deltaPts())))
                .collect(Collectors.joining(", "));

        String claim = "The same movement is visible on %s. These are correlated views of largely the "
                .formatted(slices)
                + "same trips, not independent problems.";
        prose.append(claim).append(' ');
        findings.stream().skip(1).forEach(f ->
                evidence.add(new Evidence(
                        "%s on %s=%s moved %s.".formatted(
                                format.label(f.metricId()), f.dimension(), f.entity(),
                                format.delta(f.metricId(), f.deltaPts())),
                        f.metricId(),
                        f.entity())));
    }

    // ---- section 4: attribution ------------------------------------------------------------------

    /**
     * Narrates the decomposition and returns the resulting hypothesis.
     *
     * @return a short causal hypothesis grounded in the winning dimension, or null when no dimension
     *         cleared the volume gate — in which case saying nothing is the correct output
     */
    private String appendAttribution(
            StringBuilder prose, List<Evidence> evidence, Finding lead, AttributionResult attribution) {

        if (attribution == null || attribution.ranked().isEmpty()) {
            prose.append("No dimension cleared the volume gate with enough entities to decompose this ")
                    .append("movement, so the driver is not identified. That is a coverage limit, not ")
                    .append("evidence that the movement is uniform. ");
            return null;
        }

        DimensionAttribution winner = attribution.ranked().getFirst();
        String metricId = attribution.metricId();

        String winnerClaim = ("Scanning all %d decomposable dimensions, %s explains the movement best "
                + "(explanatory power %.2f, concentration %.2f across %d entities).")
                .formatted(attribution.ranked().size(), winner.dimension(),
                        winner.explanatoryPower(), winner.concentration(), winner.entityCount());
        prose.append(winnerClaim).append(' ');
        evidence.add(new Evidence(winnerClaim, metricId, winner.dimension()));

        List<Contribution> top = winner.contributions().stream().limit(NAMED_CONTRIBUTORS).toList();
        if (!top.isEmpty()) {
            String contributors = top.stream()
                    .map(c -> "%s (%s total: %s rate, %s mix; share %s to %s)".formatted(
                            c.entity(),
                            format.effect(metricId, c.total()),
                            format.effect(metricId, c.rateEffect()),
                            format.effect(metricId, c.mixEffect()),
                            format.share(c.shareBefore()),
                            format.share(c.shareAfter())))
                    .collect(Collectors.joining("; "));
            String claim = "The leading contributors are %s.".formatted(contributors);
            prose.append(claim).append(' ');
            top.forEach(c -> evidence.add(new Evidence(
                    "%s contributed %s to the %s movement.".formatted(
                            c.entity(), format.effect(metricId, c.total()), format.label(metricId)),
                    metricId,
                    c.entity())));
        }

        appendMixVerdict(prose, evidence, winner, metricId);
        appendRejections(prose, evidence, attribution, metricId);
        appendReconciliation(prose, winner, metricId);

        Contribution leader = winner.leader();
        return leader == null
                ? null
                : ("The movement is concentrated in %s=%s on the %s dimension; that segment is where "
                        + "an intervention would have the most effect.")
                        .formatted(winner.dimension(), leader.entity(), winner.dimension());
    }

    /**
     * States whether the movement is rate-driven or mix-driven.
     *
     * <p>This is the sentence that stops a plausible-sounding wrong story. When mix is negligible,
     * volume did not move between entities and the entities themselves got worse — a different
     * problem with a different fix from "we shifted work to a weaker vendor".
     */
    private void appendMixVerdict(
            StringBuilder prose, List<Evidence> evidence, DimensionAttribution winner, String metricId) {

        double grossMix = winner.contributions().stream()
                .mapToDouble(c -> Math.abs(c.mixEffect())).sum();
        double grossTotal = winner.contributions().stream()
                .mapToDouble(c -> Math.abs(c.total())).sum();
        if (grossTotal <= 0.0) {
            return;
        }

        double mixFraction = grossMix / grossTotal;
        String claim = mixFraction < MIX_NEGLIGIBLE_FRACTION
                ? ("Mix effects account for only %.0f%% of the gross movement, so this is a rate change, "
                        + "not a redistribution of volume: the same entities carried roughly the same "
                        + "share and performed worse. An explanation blaming a shift of volume between "
                        + "entities is not supported by these numbers.")
                        .formatted(mixFraction * 100.0)
                : ("Mix effects account for %.0f%% of the gross movement, so a meaningful part of this is "
                        + "volume moving between entities rather than entities changing performance.")
                        .formatted(mixFraction * 100.0);

        prose.append(claim).append(' ');
        evidence.add(new Evidence(claim, metricId, winner.dimension()));
    }

    /**
     * Records the dimensions that were checked and rejected.
     *
     * <p>"Vendor does not explain this" is a finding, and it is only credible if the vendor
     * decomposition is visibly on the record rather than never having been run.
     */
    private void appendRejections(
            StringBuilder prose, List<Evidence> evidence, AttributionResult attribution, String metricId) {

        if (attribution.ranked().size() < 2) {
            return;
        }
        String rejected = attribution.ranked().stream()
                .skip(1)
                .limit(NAMED_REJECTIONS)
                .map(d -> "%s (%.2f)".formatted(d.dimension(), d.explanatoryPower()))
                .collect(Collectors.joining(", "));

        String claim = ("Also decomposed and ranked lower: %s. Every dimension reconciles to the same "
                + "aggregate delta, so being arithmetically correct is not the test — these were "
                + "rejected because they restate the total rather than concentrating it.")
                .formatted(rejected);
        prose.append(claim).append(' ');
        evidence.add(new Evidence(claim, metricId, "ALL"));
    }

    private void appendReconciliation(StringBuilder prose, DimensionAttribution winner, String metricId) {
        if (winner.reconciles(reconciliationTolerance)) {
            prose.append("The decomposition reconciles to the aggregate movement within tolerance. ");
            return;
        }
        prose.append(("The decomposition leaves %s unaccounted for against the aggregate movement, "
                + "which means entities were held back by the volume gate or carried a null dimension "
                + "value. Treat the named contributors as the bulk of the story, not all of it. ")
                .formatted(format.effect(metricId, winner.reconciliationError())));
    }

    // ---- section 5: data quality -----------------------------------------------------------------

    private void appendQuality(StringBuilder prose, Finding lead) {
        if (lead.observation() == null || lead.observation().quality() == null) {
            return;
        }
        var quality = lead.observation().quality();
        prose.append("Confidence %s on %.1f%% coverage.".formatted(
                quality.confidence(), quality.coverage() * 100.0));
        if (!quality.caveats().isEmpty()) {
            prose.append(" Caveats: ").append(String.join(" ", quality.caveats()));
        }
    }
}
