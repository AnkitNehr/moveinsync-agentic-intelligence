package com.moveinsync.mi.incident;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.time.Instant;

/**
 * A scheduled promise to re-check an incident.
 *
 * <p>This is the record that turns a reporting tool into an agent. When an incident is raised the
 * system commits to looking again on a date, and {@link FollowUpScheduler} honours that commitment
 * without anyone asking it to. The metric context is captured at scheduling time so the re-check can
 * be executed even if the originating incident has since been edited.
 *
 * @param incidentId incident to re-evaluate
 * @param metricId   metric to re-measure
 * @param dimension  dimension the original finding sat on
 * @param entity     dimension member to re-measure
 * @param period     period label that was breaching when the follow-up was scheduled
 * @param dueAt      when the re-check becomes due
 * @param status     {@link #PENDING}, {@link #RECOVERED} or {@link #ESCALATED}
 * @param note       outcome note written when the follow-up is completed
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record FollowUp(
        String incidentId,
        String metricId,
        String dimension,
        String entity,
        String period,
        Instant dueAt,
        String status,
        String note) {

    /** Scheduled and not yet actioned. */
    public static final String PENDING = "PENDING";
    /** Re-checked and the metric was back inside its SLA. */
    public static final String RECOVERED = "RECOVERED";
    /** Re-checked and still breaching; an escalation incident was raised. */
    public static final String ESCALATED = "ESCALATED";
    /** Re-check could not be performed because the metric layer returned no value. */
    public static final String UNRESOLVED = "UNRESOLVED";

    /** Whether this follow-up is still awaiting action. */
    public boolean pending() {
        return PENDING.equals(status);
    }

    /** Whether this follow-up is pending and due at the given instant. */
    public boolean dueAt(Instant now) {
        return pending() && dueAt != null && now != null && !dueAt.isAfter(now);
    }

    /** Returns a copy marked complete with the given status and note. */
    public FollowUp completed(String newStatus, String outcomeNote) {
        return new FollowUp(incidentId, metricId, dimension, entity, period, dueAt, newStatus, outcomeNote);
    }
}
