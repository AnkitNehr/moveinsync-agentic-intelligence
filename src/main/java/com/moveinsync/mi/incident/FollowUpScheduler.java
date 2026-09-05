package com.moveinsync.mi.incident;

import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.policy.ActionGuard;
import com.moveinsync.mi.policy.SlaPolicy;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * The autonomous loop: honours scheduled re-checks and escalates what has not recovered.
 *
 * <p>This is what separates an agent from a report generator. Everything else in the platform runs
 * because a human asked for a run. This class runs because it previously promised to. When an
 * incident is raised the system commits to looking again on a date; when that date arrives this
 * scheduler re-measures the metric through {@link MetricRecheckPort}, and:
 *
 * <ul>
 *   <li><strong>Recovered</strong> — the incident is resolved and the follow-up closed. Nobody is
 *       interrupted. Closing loops quietly is as important as opening them loudly.</li>
 *   <li><strong>Still breaching</strong> — a new incident is raised with the title prefixed
 *       {@code ESCALATED:} and the priority raised one step. Crucially the breach depth has now
 *       grown by a period, which is exactly the condition {@link ActionGuard} uses to unlock
 *       {@code vendor_escalation}. Persistence, not severity, is what earns a vendor conversation.</li>
 *   <li><strong>Unmeasurable</strong> — left pending. A segment that fell below the min-sample gate
 *       returns no value, and silence must never be mistaken for recovery.</li>
 * </ul>
 *
 * <p>Every pass writes to {@link AuditLog}, so an escalation that appears in someone's inbox can
 * always be traced back to the promise that produced it.
 */
@Service
public class FollowUpScheduler {

    private static final Logger log = LoggerFactory.getLogger(FollowUpScheduler.class);

    /** Prefix applied to escalated incident titles. */
    public static final String ESCALATION_PREFIX = "ESCALATED: ";

    /** Highest (most urgent) priority an escalation can reach. Lower number means more urgent. */
    public static final int MAX_PRIORITY = 1;

    /** Days until an escalation's own follow-up comes due. */
    public static final int ESCALATION_FOLLOW_UP_DAYS = 7;

    private final IncidentStore store;
    private final SlaPolicy slaPolicy;
    private final ActionGuard actionGuard;
    private final AuditLog auditLog;
    private final ObjectProvider<MetricRecheckPort> recheckProvider;

    /**
     * The re-check port is injected as an {@link ObjectProvider} rather than a hard dependency so the
     * governance loop can start before the metrics layer is wired. A missing port makes the scheduler
     * inert, not broken.
     */
    public FollowUpScheduler(
            IncidentStore store,
            SlaPolicy slaPolicy,
            ActionGuard actionGuard,
            AuditLog auditLog,
            ObjectProvider<MetricRecheckPort> recheckProvider) {
        this.store = store;
        this.slaPolicy = slaPolicy;
        this.actionGuard = actionGuard;
        this.auditLog = auditLog;
        this.recheckProvider = recheckProvider;
    }

    /**
     * Periodic sweep. Uses {@code fixedDelay} rather than {@code fixedRate} so a slow re-check can
     * never cause passes to overlap and double-escalate the same incident.
     */
    @Scheduled(
            fixedDelayString = "${app.followup.check-interval-ms:900000}",
            initialDelayString = "${app.followup.initial-delay-ms:60000}")
    public void sweep() {
        try {
            List<Incident> raised = runDueFollowUps(Instant.now());
            if (!raised.isEmpty()) {
                log.info("Follow-up sweep raised {} escalation(s)", raised.size());
            }
        } catch (RuntimeException e) {
            // A scheduled method that throws is silently unscheduled by some executors; swallow and log.
            log.error("Follow-up sweep failed: {}", e.toString(), e);
        }
    }

    /**
     * Processes every follow-up due at the given instant.
     *
     * <p>Exposed with an explicit {@code now} so the loop can be driven deterministically from tests
     * and from an on-demand console action without waiting for the scheduler.
     *
     * @return the escalation incidents raised during this pass
     */
    public List<Incident> runDueFollowUps(Instant now) {
        List<FollowUp> due = store.dueFollowUps(now);
        if (due.isEmpty()) {
            return List.of();
        }

        MetricRecheckPort recheck = recheckProvider.getIfAvailable();
        if (recheck == null) {
            log.warn("{} follow-up(s) due but no MetricRecheckPort is registered; leaving them pending",
                    due.size());
            return List.of();
        }

        String runId = "followup-" + now.toString();
        List<Incident> escalations = new ArrayList<>();

        for (FollowUp followUp : due) {
            Optional<Incident> maybeIncident = store.byId(followUp.incidentId());
            if (maybeIncident.isEmpty()) {
                store.completeFollowUp(
                        followUp.incidentId(), FollowUp.UNRESOLVED, "incident no longer present in memory");
                continue;
            }
            Incident incident = maybeIncident.get();

            // An incident the operator already dismissed or resolved must not be reopened by the loop.
            if (IncidentStore.STATUS_DISMISSED.equalsIgnoreCase(incident.status())
                    || IncidentStore.STATUS_RESOLVED.equalsIgnoreCase(incident.status())) {
                store.completeFollowUp(
                        followUp.incidentId(), FollowUp.RECOVERED, "closed before follow-up came due");
                continue;
            }

            Optional<MetricObservation> observation = safeRecheck(recheck, followUp);
            if (observation.isEmpty() || observation.get().value() == null) {
                // No number means no verdict. Leaving it pending is the honest outcome: silence from a
                // volume-gated segment is not evidence of recovery.
                log.info("Follow-up for incident {} could not be measured; leaving pending",
                        followUp.incidentId());
                auditLog.recordDeterministic(
                        runId, AuditLog.STAGE_FOLLOW_UP, List.of(followUp.incidentId() + ":unmeasurable"));
                continue;
            }

            MetricObservation current = observation.get();
            boolean stillBreaching = slaPolicy.breaches(followUp.metricId(), current.value());

            if (!stillBreaching) {
                store.resolve(incident.id());
                store.completeFollowUp(
                        incident.id(),
                        FollowUp.RECOVERED,
                        "recovered: " + followUp.metricId() + " back within SLA at " + current.value());
                auditLog.recordDeterministic(
                        runId, AuditLog.STAGE_FOLLOW_UP, List.of(incident.id() + ":recovered"));
                log.info("Incident {} recovered at follow-up ({} = {})",
                        incident.id(), followUp.metricId(), current.value());
                continue;
            }

            Incident escalation = escalate(incident, followUp, current, now);
            store.open(escalation);
            store.scheduleFollowUp(escalation.id(), ESCALATION_FOLLOW_UP_DAYS, now);
            store.completeFollowUp(
                    incident.id(), FollowUp.ESCALATED, "still breaching; raised " + escalation.id());
            escalations.add(escalation);

            auditLog.record(
                    runId,
                    AuditLog.STAGE_FOLLOW_UP,
                    List.of(escalation.id()),
                    escalation.evidence(),
                    escalation.recommendedActions(),
                    List.of(),
                    null,
                    0L,
                    0L);
            log.info("Incident {} still breaching at follow-up; escalated as {}",
                    incident.id(), escalation.id());
        }

        return List.copyOf(escalations);
    }

    /** A misbehaving metric layer must not take the governance loop down with it. */
    private Optional<MetricObservation> safeRecheck(MetricRecheckPort recheck, FollowUp followUp) {
        try {
            Optional<MetricObservation> result = recheck.recheck(
                    followUp.metricId(), followUp.dimension(), followUp.entity(), followUp.period());
            return result == null ? Optional.empty() : result;
        } catch (RuntimeException e) {
            log.warn("Re-check failed for incident {} metric {}: {}",
                    followUp.incidentId(), followUp.metricId(), e.toString());
            return Optional.empty();
        }
    }

    /**
     * Builds the escalation incident.
     *
     * <p>Breach depth is advanced by one period because the metric has now been observed breaching
     * across another measurement, and the action ladder is re-evaluated against that deeper streak —
     * which is what promotes {@code vendor_escalation} from denied to permitted.
     */
    private Incident escalate(
            Incident original, FollowUp followUp, MetricObservation current, Instant now) {

        PolicyDecision priorPolicy = original.policy();
        int priorDepth = priorPolicy == null ? 1 : Math.max(1, priorPolicy.consecutivePeriods());
        int depth = priorDepth + 1;

        String ruleId = priorPolicy == null ? SlaPolicy.RULE_NO_SLA : priorPolicy.ruleId();
        String band = slaPolicy.band(followUp.metricId(), current.value());

        PolicyDecision escalatedPolicy = new PolicyDecision(
                ruleId, true, depth, depth >= SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS, band);

        // Escalate from the root incident id, not the previous escalation's, so a long-running breach
        // yields inc-001-esc1, inc-001-esc2, inc-001-esc3 rather than an ever-lengthening chain.
        String rootId = original.id().replaceFirst("(-esc\\d+)+$", "");
        String escalationId = rootId + "-esc" + (depth - 1);
        String title = original.title() == null ? "Unresolved SLA breach" : original.title();
        if (!title.startsWith(ESCALATION_PREFIX)) {
            title = ESCALATION_PREFIX + title;
        }

        String whyNow = "Re-checked on the scheduled follow-up date and "
                + followUp.metricId() + " is still outside SLA at " + current.value()
                + " after " + depth + " consecutive breaching periods.";

        String explanation = "Incident " + original.id() + " was raised and scheduled for review. "
                + "On re-measurement " + describeEntity(followUp) + " remains in breach of " + ruleId
                + ", so the issue has been escalated rather than closed. Breach depth is now " + depth
                + " period(s), which meets the threshold for formal vendor escalation.";

        List<Evidence> evidence = new ArrayList<>(original.evidence());
        evidence.add(new Evidence(
                "On follow-up, " + followUp.metricId() + " measured " + current.value()
                        + " over " + current.sampleSize() + " trips, still breaching " + ruleId + ".",
                followUp.metricId(),
                followUp.entity()));

        Incident skeleton = new Incident(
                escalationId,
                title,
                whyNow,
                Math.max(MAX_PRIORITY, original.priority() - 1),
                band,
                original.findingIds(),
                explanation,
                evidence,
                List.of(),
                escalatedPolicy,
                current.quality() == null ? original.quality() : current.quality(),
                now.toString(),
                null,
                IncidentStore.STATUS_OPEN);

        List<Action> actions = actionGuard.permittedActions(skeleton, escalatedPolicy);

        return new Incident(
                skeleton.id(),
                skeleton.title(),
                skeleton.whyNow(),
                skeleton.priority(),
                skeleton.severity(),
                skeleton.findingIds(),
                skeleton.explanation(),
                skeleton.evidence(),
                actions,
                skeleton.policy(),
                skeleton.quality(),
                skeleton.detectedAt(),
                now.plusSeconds(ESCALATION_FOLLOW_UP_DAYS * 86_400L).toString(),
                skeleton.status());
    }

    private static String describeEntity(FollowUp followUp) {
        if (followUp.entity() == null || followUp.entity().isBlank()) {
            return "the affected segment";
        }
        return followUp.dimension() == null || followUp.dimension().isBlank()
                ? followUp.entity()
                : followUp.dimension() + "=" + followUp.entity();
    }
}
