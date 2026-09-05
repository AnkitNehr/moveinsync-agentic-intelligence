package com.moveinsync.mi.incident;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.delivery.DeliveryService;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.policy.ActionGuard;
import com.moveinsync.mi.policy.SlaPolicy;
import java.time.Instant;
import java.time.YearMonth;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
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
 *       {@code vendor_escalation} only if attribution also shows vendors explain the movement.
 *       Persistence without vendor signal still escalates internally; the vendor letter stays blocked.</li>
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
    private final ObjectProvider<DeliveryService> deliveryProvider;
    private final ObjectProvider<AttributionService> attributionProvider;
    private final ObjectProvider<MetricQueryService> metricsProvider;

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
        this(store, slaPolicy, actionGuard, auditLog, recheckProvider, unused(), unused(), unused());
    }

    @Autowired
    public FollowUpScheduler(
            IncidentStore store,
            SlaPolicy slaPolicy,
            ActionGuard actionGuard,
            AuditLog auditLog,
            ObjectProvider<MetricRecheckPort> recheckProvider,
            ObjectProvider<DeliveryService> deliveryProvider,
            ObjectProvider<AttributionService> attributionProvider,
            ObjectProvider<MetricQueryService> metricsProvider) {
        this.store = store;
        this.slaPolicy = slaPolicy;
        this.actionGuard = actionGuard;
        this.auditLog = auditLog;
        this.recheckProvider = recheckProvider;
        this.deliveryProvider = deliveryProvider;
        this.attributionProvider = attributionProvider;
        this.metricsProvider = metricsProvider;
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
        return runDueFollowUps(now, null);
    }

    /**
     * Processes every follow-up due at the given instant, optionally forcing the re-check period.
     *
     * <p>{@code periodOverride} is the demo lever: pass {@code 2026-07} to re-measure July without
     * waiting for a later extract. When it is null the loop uses the latest period that is
     * <em>after</em> the originating month; if no later period exists it leaves the follow-up pending.
     */
    public List<Incident> runDueFollowUps(Instant now, String periodOverride) {
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
        DeliveryService delivery = deliveryProvider == null ? null : deliveryProvider.getIfAvailable();

        for (FollowUp followUp : due) {
            Optional<Incident> maybeIncident = store.byId(followUp.incidentId());
            if (maybeIncident.isEmpty()) {
                store.completeFollowUp(
                        followUp.incidentId(), FollowUp.UNRESOLVED, "incident no longer present in memory");
                continue;
            }
            Incident incident = maybeIncident.get();

            if (IncidentStore.STATUS_DISMISSED.equalsIgnoreCase(incident.status())
                    || IncidentStore.STATUS_RESOLVED.equalsIgnoreCase(incident.status())) {
                store.completeFollowUp(
                        followUp.incidentId(), FollowUp.RECOVERED, "closed before follow-up came due");
                continue;
            }

            RecheckPeriod target = resolveRecheckPeriod(followUp, periodOverride);
            if (target.waitReason() != null) {
                log.info("Follow-up for incident {} waiting: {}", followUp.incidentId(), target.waitReason());
                auditLog.recordDeterministic(
                        runId, AuditLog.STAGE_FOLLOW_UP,
                        List.of(followUp.incidentId() + ":waiting:" + target.waitReason()));
                continue;
            }

            Optional<MetricObservation> observation = safeRecheck(recheck, followUp, target.period());
            if (observation.isEmpty() || observation.get().value() == null) {
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
                        "recovered: " + followUp.metricId() + " back within SLA at " + current.value()
                                + " in " + current.period());
                if (delivery != null) {
                    delivery.publishRecovery(incident, current);
                }
                auditLog.recordDeterministic(
                        runId, AuditLog.STAGE_FOLLOW_UP, List.of(incident.id() + ":recovered"));
                log.info("Incident {} recovered at follow-up ({} = {} in {})",
                        incident.id(), followUp.metricId(), current.value(), current.period());
                continue;
            }

            AttributionResult attributed = safeAttribute(followUp, current);
            Incident escalation = escalate(incident, followUp, current, now, attributed);
            store.open(escalation);
            store.scheduleFollowUp(escalation.id(), ESCALATION_FOLLOW_UP_DAYS, now, current.period());
            store.completeFollowUp(
                    incident.id(), FollowUp.ESCALATED, "still breaching; raised " + escalation.id());
            escalations.add(escalation);
            if (delivery != null) {
                delivery.publishEscalation(escalation, attributed);
            }

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
    private Optional<MetricObservation> safeRecheck(
            MetricRecheckPort recheck, FollowUp followUp, String period) {
        try {
            Optional<MetricObservation> result = recheck.recheck(
                    followUp.metricId(), followUp.dimension(), followUp.entity(), period);
            return result == null ? Optional.empty() : result;
        } catch (RuntimeException e) {
            log.warn("Re-check failed for incident {} metric {}: {}",
                    followUp.incidentId(), followUp.metricId(), e.toString());
            return Optional.empty();
        }
    }

    /**
     * Picks the period to re-measure.
     *
     * <p>Never the originating month when a later one exists: re-scoring June as June cannot show
     * recovery. When the metric layer is not wired (unit tests) the follow-up's stored period is
     * used, which is what the stub re-check port already ignores.
     */
    RecheckPeriod resolveRecheckPeriod(FollowUp followUp, String periodOverride) {
        if (periodOverride != null && !periodOverride.isBlank()) {
            return RecheckPeriod.use(periodOverride.trim());
        }
        MetricQueryService metrics = metricsProvider == null ? null : metricsProvider.getIfAvailable();
        if (metrics == null) {
            return RecheckPeriod.use(followUp.period());
        }
        Optional<String> latest = metrics.latestPeriod(followUp.metricId());
        if (latest.isEmpty()) {
            return RecheckPeriod.wait("no later period available");
        }
        String origin = followUp.period();
        if (origin != null && !origin.isBlank() && latest.get().compareTo(origin) <= 0) {
            return RecheckPeriod.wait("latest period " + latest.get()
                    + " is not after origin " + origin);
        }
        return RecheckPeriod.use(latest.get());
    }

    private AttributionResult safeAttribute(FollowUp followUp, MetricObservation current) {
        AttributionService service = attributionProvider == null ? null : attributionProvider.getIfAvailable();
        if (service == null || followUp.metricId() == null || current == null || current.period() == null) {
            return null;
        }
        try {
            return service.attribute(followUp.metricId(), current.period(), priorPeriod(current.period()));
        } catch (RuntimeException e) {
            log.warn("Attribution on follow-up of {} failed: {}", followUp.incidentId(), e.toString());
            return null;
        }
    }

    public List<Incident> recheckNow(String incidentId, Instant now, String periodOverride) {
        store.markDue(incidentId, now);
        return runDueFollowUps(now, periodOverride);
    }

    public static String priorPeriod(String period) {
        if (period == null || period.isBlank()) {
            return null;
        }
        try {
            return YearMonth.parse(period).minusMonths(1).toString();
        } catch (DateTimeParseException e) {
            return period;
        }
    }

    private static <T> ObjectProvider<T> unused() {
        return new ObjectProvider<>() {
            @Override
            public T getObject() {
                return null;
            }

            @Override
            public T getObject(Object... args) {
                return null;
            }

            @Override
            public T getIfAvailable() {
                return null;
            }

            @Override
            public T getIfUnique() {
                return null;
            }
        };
    }

    record RecheckPeriod(String period, String waitReason) {
        static RecheckPeriod use(String period) {
            return new RecheckPeriod(period, null);
        }

        static RecheckPeriod wait(String reason) {
            return new RecheckPeriod(null, reason);
        }
    }

    /**
     * Builds the escalation incident.
     *
     * <p>Breach depth is advanced by one period because the metric has now been observed breaching
     * across another measurement, and the action ladder is re-evaluated against that deeper streak.
     * Persistence is necessary for a vendor letter; it is not sufficient without vendor attribution.
     */
    private Incident escalate(
            Incident original, FollowUp followUp, MetricObservation current, Instant now,
            AttributionResult attributed) {

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
                + " period(s). Vendor escalation still requires attribution evidence that vendors "
                + "explain the movement; persistence alone does not write a vendor letter.";

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

        List<Action> actions = actionGuard.permittedActions(skeleton, escalatedPolicy, attributed);

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
