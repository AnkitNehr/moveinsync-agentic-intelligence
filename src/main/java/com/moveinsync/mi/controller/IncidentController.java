package com.moveinsync.mi.controller;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.delivery.Communication;
import com.moveinsync.mi.delivery.DeliveryService;
import com.moveinsync.mi.delivery.OwnerRouter;
import com.moveinsync.mi.incident.FollowUp;
import com.moveinsync.mi.incident.FollowUpScheduler;
import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.policy.ActionGuard;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The operator's surface onto agent memory: read incidents, dismiss them, escalate them.
 *
 * <h2>Dismissal is a teaching signal, not a delete</h2>
 *
 * <p>Dismissing writes a {@link com.moveinsync.mi.incident.Suppression} keyed on the metric and entity
 * the incident was about, which the candidate ranker consults on every subsequent run. The platform
 * therefore gets quieter as an operator uses it, instead of re-raising the same judgement call every
 * month and training people to ignore it.
 *
 * <h2>Escalation can be refused</h2>
 *
 * <p>{@code POST /escalate} asks {@link ActionGuard}, and the guard says no to a single-period breach
 * however severe it looks. That refusal is returned as 403 with the policy's own reason attached
 * rather than being silently swallowed — a blocked action that disappears is indistinguishable from
 * one nobody thought of, and the whole value of a guard is that its refusals are visible.
 */
@RestController
@RequestMapping("/api/incidents")
@CrossOrigin
public class IncidentController {

    private static final Logger log = LoggerFactory.getLogger(IncidentController.class);

    private final IncidentStore store;
    private final ActionGuard actionGuard;
    private final AuditLog auditLog;
    private final AttributionService attribution;
    private final DeliveryService delivery;
    private final FollowUpScheduler followUps;

    public IncidentController(
            IncidentStore store,
            ActionGuard actionGuard,
            AuditLog auditLog,
            AttributionService attribution,
            DeliveryService delivery,
            FollowUpScheduler followUps) {
        this.store = store;
        this.actionGuard = actionGuard;
        this.auditLog = auditLog;
        this.attribution = attribution;
        this.delivery = delivery;
        this.followUps = followUps;
    }

    /** Body for a dismissal. The reason is retained on the suppression and in the audit trail. */
    public record DismissRequest(String reason) {
    }

    /** Body for an escalation. The note is recorded against the delivery audit entry. */
    public record EscalateRequest(String note) {
    }

    /**
     * The outcome of an escalation attempt.
     *
     * @param incident  the incident, with its status advanced when the escalation was permitted
     * @param action    the guard's verdict on {@code vendor_escalation}
     * @param escalated whether the escalation actually went ahead
     */
    public record EscalateResponse(Incident incident, Action action, boolean escalated) {
    }

    public record RecheckRequest(String period, String asOf) {
    }

    public record RecheckResponse(Incident incident, List<Incident> escalations, FollowUp followUp) {
    }

    /**
     * Lists incidents.
     *
     * @param status optional filter, e.g. {@code OPEN}, {@code DISMISSED}; {@code open} is a
     *               shorthand for open-or-monitoring
     * @param limit  maximum returned, newest first; non-positive means unlimited
     */
    @GetMapping
    public List<Incident> list(
            @RequestParam(required = false) String status,
            @RequestParam(required = false, defaultValue = "0") int limit) {

        List<Incident> all = (status != null && "open".equalsIgnoreCase(status.trim()))
                ? store.openIncidents()
                : store.all();

        List<Incident> filtered = (status == null || status.isBlank() || "open".equalsIgnoreCase(status.trim()))
                ? all
                : all.stream()
                        .filter(incident -> status.trim().equalsIgnoreCase(incident.status()))
                        .toList();

        return limit > 0 && filtered.size() > limit ? filtered.subList(0, limit) : filtered;
    }

    /** One incident. 404 when the id is not in memory. */
    @GetMapping("/{id}")
    public Incident byId(@PathVariable String id) {
        return store.byId(id).orElseThrow(() -> NotFoundException.of("incident", id, null));
    }

    /** The scheduled re-check for an incident, if one is pending. 404 when nothing is scheduled. */
    @GetMapping("/{id}/followup")
    public FollowUp followUp(@PathVariable String id) {
        return store.allFollowUps().stream()
                .filter(followUp -> followUp.incidentId() != null && followUp.incidentId().equals(id))
                .findFirst()
                .orElseThrow(() -> new NotFoundException("No follow-up is scheduled for incident '" + id + "'."));
    }

    /**
     * Dismisses an incident and writes the suppression that keeps the same pattern from returning.
     *
     * @return the dismissed incident, or 404 when the id is unknown
     */
    @PostMapping("/{id}/dismiss")
    public Incident dismiss(
            @PathVariable String id,
            @RequestBody(required = false) DismissRequest request) {

        String reason = request == null || request.reason() == null || request.reason().isBlank()
                ? "dismissed by operator"
                : request.reason().trim();

        Incident dismissed = store.dismiss(id, reason)
                .orElseThrow(() -> NotFoundException.of("incident", id, null));

        auditLog.recordDeterministic("operator", AuditLog.STAGE_DELIVER,
                List.of(id + ":dismissed:" + reason));
        log.info("Incident {} dismissed: {}", id, reason);
        return dismissed;
    }

    /**
     * Raises the breach formally with the owning entity, if policy allows it.
     *
     * @return 200 with the advanced incident and the permitting action, or 403 with the guard's
     *         reason when the breach has not persisted long enough to earn an escalation
     */
    @PostMapping("/{id}/escalate")
    public ResponseEntity<EscalateResponse> escalate(
            @PathVariable String id,
            @RequestBody(required = false) EscalateRequest request) {

        Incident incident = store.byId(id)
                .orElseThrow(() -> NotFoundException.of("incident", id, null));

        PolicyDecision decision = incident.policy();
        AttributionResult attributed = attributionFor(incident);
        Action escalation = actionGuard.permittedActions(incident, decision, attributed).stream()
                .filter(action -> ActionGuard.VENDOR_ESCALATION.equalsIgnoreCase(action.type()))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException(
                        "The action guard did not emit a vendor_escalation verdict for this incident."));

        if (!escalation.permitted()) {
            log.info("Escalation of incident {} refused by policy: {}", id, escalation.reason());
            auditLog.record("operator", AuditLog.STAGE_POLICY, List.of(id + ":escalation_denied"),
                    incident.evidence(), List.of(escalation), List.of(), null, 0L, 0L);
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(new EscalateResponse(incident, escalation, false));
        }

        Incident escalated = withStatus(incident, IncidentStore.STATUS_MONITORING);
        store.open(escalated);

        String note = request == null || request.note() == null ? "" : request.note().trim();
        auditLog.record("operator", AuditLog.STAGE_DELIVER,
                List.of(id + ":escalated" + (note.isEmpty() ? "" : ":" + note)),
                incident.evidence(), List.of(escalation),
                List.of(Optional.ofNullable(escalation.target()).orElse("operations")),
                null, 0L, 0L);
        log.info("Incident {} escalated to {} ({} consecutive periods)",
                id, escalation.target(), decision == null ? 0 : decision.consecutivePeriods());

        return ResponseEntity.ok(new EscalateResponse(escalated, escalation, true));
    }

    /**
     * Drafts and sends a notify to the routed owner. Always permitted; this is the operator forcing
     * a copy into the outbox.
     */
    @PostMapping("/{id}/notify")
    public Communication notifyOwner(@PathVariable String id) {
        Incident incident = store.byId(id)
                .orElseThrow(() -> NotFoundException.of("incident", id, null));
        Communication sent = delivery.notifyNow(incident, attributionFor(incident));
        auditLog.recordDeterministic("operator", AuditLog.STAGE_DELIVER, List.of(id + ":notified"));
        return sent;
    }

    /**
     * Fires this incident's follow-up immediately. Pass {@code period} (e.g. {@code 2026-07}) to
     * re-measure a later month on stage.
     */
    @PostMapping("/{id}/recheck")
    public RecheckResponse recheck(
            @PathVariable String id,
            @RequestBody(required = false) RecheckRequest request) {

        store.byId(id).orElseThrow(() -> NotFoundException.of("incident", id, null));
        Instant asOf = Instant.now();
        if (request != null && request.asOf() != null && !request.asOf().isBlank()) {
            try {
                asOf = Instant.parse(request.asOf());
            } catch (RuntimeException ignored) {
                asOf = Instant.now();
            }
        }
        String period = request == null ? null : request.period();
        List<Incident> escalations = followUps.recheckNow(id, asOf, period);
        Incident after = store.byId(id).orElseThrow(() -> NotFoundException.of("incident", id, null));
        FollowUp followUp = store.allFollowUps().stream()
                .filter(item -> id.equals(item.incidentId()))
                .findFirst()
                .orElse(null);
        log.info("Incident {} rechecked (period={}): status={} escalations={}",
                id, period, after.status(), escalations.size());
        return new RecheckResponse(after, escalations, followUp);
    }

    private AttributionResult attributionFor(Incident incident) {
        String metric = OwnerRouter.firstMetric(incident);
        String period = IncidentStore.originPeriodOf(incident, null);
        if (metric == null || period == null) {
            return AttributionResult.empty(metric, period, null);
        }
        try {
            return attribution.attribute(metric, period, FollowUpScheduler.priorPeriod(period));
        } catch (RuntimeException e) {
            log.warn("Attribution for incident {} failed: {}", incident.id(), e.toString());
            return AttributionResult.empty(metric, period, FollowUpScheduler.priorPeriod(period));
        }
    }

    /** Status transitions rebuild the record: {@link Incident} is immutable by design. */
    private static Incident withStatus(Incident incident, String status) {
        return new Incident(
                incident.id(), incident.title(), incident.whyNow(), incident.priority(),
                incident.severity(), incident.findingIds(), incident.explanation(), incident.evidence(),
                incident.recommendedActions(), incident.policy(), incident.quality(),
                incident.detectedAt(), incident.followUpAt(), status.toUpperCase(Locale.ROOT));
    }
}
