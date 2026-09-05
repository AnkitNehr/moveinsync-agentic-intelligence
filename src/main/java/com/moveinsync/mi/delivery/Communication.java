package com.moveinsync.mi.delivery;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A message the platform drafted, sent to the console outbox, or refused to send.
 *
 * <p>This is the artefact of "act". An incident that only lives on a dashboard is a report. A
 * communication is something a transport manager could forward: a recipient, a subject, a body, and
 * a status that records whether policy allowed it.
 *
 * @param id             stable id, unique per outbox row
 * @param incidentId     incident this message is about
 * @param actionType     {@code notify}, {@code vendor_escalation}, {@code auto_reallocate}, …
 * @param persona        reader the message is written for
 * @param channel        delivery channel; the shipped sink is {@code console}
 * @param recipient      human-readable desk or role
 * @param subject        one-line title
 * @param body           markdown body; figures in it must already exist on the incident
 * @param status         {@link #DRAFTED}, {@link #SENT}, {@link #BLOCKED} or {@link #SUPERSEDED}
 * @param blockedReason  policy reason when status is {@link #BLOCKED}; otherwise null
 * @param createdAt      ISO-8601 instant
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record Communication(
        String id,
        String incidentId,
        String actionType,
        String persona,
        String channel,
        String recipient,
        String subject,
        String body,
        String status,
        String blockedReason,
        String createdAt) {

    public static final String DRAFTED = "DRAFTED";
    public static final String SENT = "SENT";
    public static final String BLOCKED = "BLOCKED";
    public static final String SUPERSEDED = "SUPERSEDED";

    public static final String CHANNEL_CONSOLE = "console";

    public Communication {
        if (status == null || status.isBlank()) {
            status = DRAFTED;
        }
    }

    public Communication withStatus(String newStatus, String reason) {
        return new Communication(
                id, incidentId, actionType, persona, channel, recipient, subject, body,
                newStatus, reason, createdAt);
    }
}
