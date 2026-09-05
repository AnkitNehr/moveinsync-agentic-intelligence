package com.moveinsync.mi.pipeline.fallback;

import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Clusters findings into incident drafts without a model.
 *
 * <p>This is the fallback, but it is not a stub. It implements the clustering rule the LLM stage is
 * asked to apply: <em>one metric moving one way in one period is one story</em>. Findings are keyed
 * by metric and direction, so the June OTA decline — which surfaces simultaneously on
 * {@code trip_direction=LOGIN} (-5.17), {@code product_type=BUS} (-6.25) and
 * {@code route_source=MANUAL} (-6.22) because those slices largely describe the same trips —
 * collapses into one incident naming the strongest slice, with the correlated ones carried as
 * supporting findings rather than as three near-duplicate alerts.
 *
 * <p>Direction is part of the key on purpose. OTA falling on LOGIN and OTA rising on LOGOUT are
 * different situations; merging them would produce a narrative that averages a problem against a
 * success and reports neither.
 *
 * <p>What this cannot do, and an LLM tier can, is spot a <em>cross-metric</em> story — that a
 * no-show spike and an occupancy drop are one event. That judgement is why the agentic layer exists;
 * this is the floor that keeps the platform useful when it is switched off.
 */
@Service
public class DeterministicTriage implements TriagePort {

    /** Robust z at which a movement is described as a break from the series' own pattern. */
    private static final double NOTABLE_Z = 2.0;

    private final MetricFormat format;
    private final int maxIncidents;
    private final int maxSupportingFindings;

    public DeterministicTriage(
            MetricFormat format,
            @Value("${app.triage.max-incidents:5}") int maxIncidents,
            @Value("${app.triage.max-supporting-findings:6}") int maxSupportingFindings) {
        this.format = format;
        this.maxIncidents = Math.max(1, maxIncidents);
        this.maxSupportingFindings = Math.max(1, maxSupportingFindings);
    }

    @Override
    public List<IncidentDraft> triage(List<Finding> ranked, String period) {
        if (ranked == null || ranked.isEmpty()) {
            return List.of();
        }

        // LinkedHashMap so cluster order follows the ranker's order: the first finding to create a
        // cluster is the highest-scoring one in it, and therefore the lead.
        Map<String, List<Finding>> clusters = new LinkedHashMap<>();
        for (Finding finding : ranked) {
            if (finding != null) {
                clusters.computeIfAbsent(clusterKey(finding), key -> new ArrayList<>()).add(finding);
            }
        }

        List<IncidentDraft> drafts = new ArrayList<>(clusters.size());
        int priority = 1;
        for (Map.Entry<String, List<Finding>> entry : clusters.entrySet()) {
            List<Finding> members = entry.getValue();
            members.sort(Comparator.comparingDouble((Finding f) -> -f.score()).thenComparing(Finding::id));

            Finding lead = members.getFirst();
            List<String> ids = members.stream().limit(maxSupportingFindings).map(Finding::id).toList();

            drafts.add(new IncidentDraft(
                    entry.getKey(),
                    title(lead),
                    whyNow(lead, members.size()),
                    priority++,
                    ids,
                    rationale(lead, members)));

            if (drafts.size() >= maxIncidents) {
                break;
            }
        }
        return List.copyOf(drafts);
    }

    @Override
    public String tier() {
        return "deterministic";
    }

    /**
     * Cluster key: metric plus direction of movement. Period is excluded because a draft is always
     * built for a single period, so including it would only add noise to the derived incident id.
     */
    private String clusterKey(Finding finding) {
        String metric = finding.metricId() == null ? finding.id() : finding.metricId();
        return metric + ":" + (finding.deltaPts() < 0 ? "down" : "up");
    }

    private String title(Finding lead) {
        // "on shift_type = 08:00" was a column name and an equals sign in the most-read string in
        // the product. entityPhrase lives in MetricFormat so the list, the brief, the chat answer
        // and every LLM payload that quotes a title all say it the same way.
        return "%s %s %s for %s".formatted(
                format.label(lead.metricId()),
                format.movement(lead.deltaPts()),
                format.delta(lead.metricId(), lead.deltaPts()),
                format.entityPhrase(lead.dimension(), lead.entity()));
    }

    /**
     * Why this warrants attention in this period.
     *
     * <p>Takes the strongest justification available, in order: an SLA breach, then an unusual move
     * against the series' own history, then the raw size of the movement. Every clause is derived
     * from a computed field, so nothing here can assert more than the data supports.
     */
    private String whyNow(Finding lead, int memberCount) {
        StringBuilder reason = new StringBuilder();

        Sla sla = lead.observation() == null ? null : lead.observation().references().sla();
        if (sla != null && sla.breached() && sla.target() != null) {
            reason.append("Now at %s against a target of %s. ".formatted(
                    format.value(lead.metricId(), lead.current()),
                    format.value(lead.metricId(), sla.target())));
        }

        if (Double.isFinite(lead.robustZ()) && Math.abs(lead.robustZ()) >= NOTABLE_Z) {
            // The z-score decides whether this line prints; it does not appear in it. "2.9 robust z"
            // is the statistic that justifies the claim, but a transport manager reading an alert at
            // 07:00 cannot act on a z-score and should not have to look one up. What they need is
            // the claim itself — this is bigger than this series normally moves — which is what the
            // number means and all it is being used to assert here.
            // Qualitative on purpose, and self-contained on purpose.
            //
            // An earlier version quantified this as "%s against a typical month-to-month move of
            // about %s", deriving the second figure as |delta| / |z|. That is not the spread it
            // claimed to be: robustZ is 0.6745 * (value - median) / mad, so inverting it drops the
            // scale factor, and AnomalyScanner may score the CROSS-SECTIONAL z — the spread across
            // sibling entities in one period — in which case the quotient describes peer variation
            // and not history at all. It rendered a plausible, checkable-looking number that was
            // wrong, in the one sentence whose job is to justify the alert. Removing jargon is not
            // worth inventing a statistic to do it; if a dispersion figure belongs here, the scanner
            // must carry the real one onto Finding rather than have this class reconstruct it.
            //
            // It also leads the paragraph whenever no SLA target exists, so it cannot open with
            // "That" — for cost per trip and occupancy there is no preceding sentence to refer to.
            reason.append(("%s is a much bigger swing than this measure normally makes from one month "
                            + "to the next, so it is a genuine break in the pattern rather than "
                            + "ordinary variation. ")
                    .formatted(format.delta(lead.metricId(), lead.deltaPts())));
        } else {
            reason.append("Moved %s period over period across %,d trips. ".formatted(
                    format.delta(lead.metricId(), lead.deltaPts()), lead.sampleSize()));
        }

        if (memberCount > 1) {
            reason.append("The same movement appears on %d correlated slices, reported here once rather than as separate alerts."
                    .formatted(memberCount));
        }
        return reason.toString().trim();
    }

    private String rationale(Finding lead, List<Finding> members) {
        if (members.size() == 1) {
            return ("Single finding: %s for %s. No other slice of %s moved in the same direction far "
                    + "enough to clear both the significance and volume gates.")
                    .formatted(
                            format.label(lead.metricId()),
                            format.entityPhrase(lead.dimension(), lead.entity()),
                            format.label(lead.metricId()));
        }
        String slices = members.stream()
                .limit(maxSupportingFindings)
                .map(f -> "%s (%s)".formatted(
                        format.entityPhrase(f.dimension(), f.entity()),
                        format.delta(f.metricId(), f.deltaPts())))
                .collect(Collectors.joining(", "));

        return ("Grouped %d findings on %s all moving %s in %s: %s. They are clustered because one "
                + "operational change surfaces across correlated slices of the same trips; reporting "
                + "them separately would multiply the alert count without adding a fact.")
                .formatted(members.size(), format.label(lead.metricId()),
                        lead.deltaPts() < 0 ? "down" : "up", lead.period(), slices);
    }
}
