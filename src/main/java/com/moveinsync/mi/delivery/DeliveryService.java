package com.moveinsync.mi.delivery;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.policy.ActionGuard;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import org.springframework.stereotype.Service;

/**
 * Turns a governed incident into outbox rows: sent notifies, and visible refusals.
 */
@Service
public class DeliveryService {

    private final OutboxStore outbox;
    private final NotificationSink sink;

    public DeliveryService(OutboxStore outbox, NotificationSink sink) {
        this.outbox = outbox;
        this.sink = sink;
    }

    /**
     * Called after ActionGuard on a new or refreshed incident. Permitted {@code notify} is sent
     * immediately. Blocked vendor escalation and auto-reallocate are written as refusals.
     */
    public List<Communication> publish(Incident incident, AttributionResult attribution) {
        if (incident == null) {
            return List.of();
        }
        OwnerRouter.Owner owner = OwnerRouter.route(incident, attribution);
        List<Communication> written = new ArrayList<>();
        for (Action action : incident.recommendedActions()) {
            if (action == null || action.type() == null) {
                continue;
            }
            if (ActionGuard.NOTIFY.equalsIgnoreCase(action.type()) && action.permitted()) {
                written.add(send(composeNotify(incident, attribution, owner, "Attention required")));
            } else if (ActionGuard.VENDOR_ESCALATION.equalsIgnoreCase(action.type()) && !action.permitted()) {
                written.add(outbox.put(composeBlocked(incident, attribution, owner, action)));
            } else if (ActionGuard.AUTO_REALLOCATE.equalsIgnoreCase(action.type()) && !action.permitted()) {
                written.add(outbox.put(composeBlocked(incident, attribution, owner, action)));
            }
        }
        return List.copyOf(written);
    }

    /** Operator-forced notify: compose and send even if a prior draft exists. */
    public Communication notifyNow(Incident incident, AttributionResult attribution) {
        OwnerRouter.Owner owner = OwnerRouter.route(incident, attribution);
        return send(composeNotify(incident, attribution, owner, "Attention required"));
    }

    public Communication send(Communication message) {
        Communication delivered = sink.deliver(message);
        return outbox.put(delivered);
    }

    public Communication markSent(String id) {
        Communication existing = outbox.byId(id).orElse(null);
        if (existing == null) {
            return null;
        }
        return outbox.put(sink.deliver(existing));
    }

    /**
     * Quiet close: the metric recovered, so nobody is interrupted. The outbox still records that
     * the loop ran and chose silence.
     */
    public Communication publishRecovery(Incident incident, MetricObservation observation) {
        OwnerRouter.Owner owner = OwnerRouter.route(incident, null);
        String value = observation == null || observation.value() == null
                ? "the SLA band"
                : String.format(Locale.ROOT, "%.4f", observation.value());
        String period = observation == null ? "the later period" : observation.period();
        String body = """
                To: %s

                Incident **%s** recovered on re-check.

                %s measured %s in %s, which is back inside the SLA. The incident is resolved.
                Nobody was interrupted — closing loops quietly is as important as opening them.

                Original title: %s
                """.formatted(owner.recipient(), incident.id(),
                observation == null ? "The metric" : observation.metricId(),
                value, period, incident.title());
        Communication message = new Communication(
                newId(),
                incident.id(),
                ActionGuard.NOTIFY,
                owner.persona(),
                sink.channel(),
                owner.recipient(),
                "Closed — " + incident.title(),
                body,
                Communication.DRAFTED,
                null,
                Instant.now().toString());
        return send(message);
    }

    /** Higher-urgency draft after a follow-up still finds a breach. */
    public List<Communication> publishEscalation(Incident incident, AttributionResult attribution) {
        OwnerRouter.Owner owner = new OwnerRouter.Owner(
                "facilities_head",
                "Transport & facilities head",
                "escalation");
        List<Communication> written = new ArrayList<>();
        written.add(send(composeNotify(incident, attribution, owner, "ESCALATED — still breaching")));
        for (Action action : incident.recommendedActions()) {
            if (action == null) {
                continue;
            }
            if ((ActionGuard.VENDOR_ESCALATION.equalsIgnoreCase(action.type())
                    || ActionGuard.AUTO_REALLOCATE.equalsIgnoreCase(action.type()))
                    && !action.permitted()) {
                written.add(outbox.put(composeBlocked(incident, attribution, owner, action)));
            }
        }
        return List.copyOf(written);
    }

    private Communication composeNotify(
            Incident incident, AttributionResult attribution, OwnerRouter.Owner owner, String prefix) {

        String vendorLine = vendorLine(attribution);
        String winnerLine = winnerLine(attribution);
        String followUp = incident.followUpAt() == null
                ? "No follow-up scheduled."
                : "Follow-up scheduled " + incident.followUpAt() + ".";
        String body = """
                To: %s
                Persona: %s
                Channel: %s (console outbox — not email)

                **%s**

                %s

                %s
                %s

                %s

                Why now: %s

                %s
                """.formatted(
                owner.recipient(),
                owner.persona(),
                sink.channel(),
                incident.title(),
                incident.explanation() == null ? "" : incident.explanation(),
                winnerLine,
                vendorLine,
                followUp,
                incident.whyNow() == null ? "" : incident.whyNow(),
                actionsBlock(incident));
        return new Communication(
                newId(),
                incident.id(),
                ActionGuard.NOTIFY,
                owner.persona(),
                sink.channel(),
                owner.recipient(),
                "[" + prefix + "] " + incident.title(),
                body.trim(),
                Communication.DRAFTED,
                null,
                Instant.now().toString());
    }

    private Communication composeBlocked(
            Incident incident, AttributionResult attribution, OwnerRouter.Owner owner, Action action) {

        String body = """
                To: %s

                Action **%s** was considered for incident %s and **refused**.

                Reason: %s

                %s

                A blocked action that disappears looks identical to one nobody thought of.
                This row exists so the refusal is visible.
                """.formatted(
                owner.recipient(),
                action.type(),
                incident.id(),
                action.reason(),
                vendorLine(attribution));
        return new Communication(
                newId(),
                incident.id(),
                action.type(),
                owner.persona(),
                sink.channel(),
                action.target() == null ? owner.recipient() : action.target(),
                "Blocked: " + action.type() + " — " + incident.title(),
                body.trim(),
                Communication.BLOCKED,
                action.reason(),
                Instant.now().toString());
    }

    private static String winnerLine(AttributionResult attribution) {
        if (attribution == null || attribution.winner().isEmpty()) {
            return "Attribution: not attached to this message.";
        }
        DimensionAttribution winner = attribution.winner().get();
        String leader = winner.leader() == null ? "n/a" : winner.leader().entity();
        return "Best explanatory dimension: **" + winner.dimension() + "** (power "
                + String.format(Locale.ROOT, "%.2f", winner.explanatoryPower())
                + ", leader " + leader + ").";
    }

    private static String vendorLine(AttributionResult attribution) {
        double power = OwnerRouter.vendorPower(attribution);
        return "Vendor explanatory power: **" + String.format(Locale.ROOT, "%.2f", power) + "**.";
    }

    private static String actionsBlock(Incident incident) {
        if (incident.recommendedActions().isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("Policy actions:\n");
        for (Action action : incident.recommendedActions()) {
            sb.append("- ")
                    .append(action.type())
                    .append(" → ")
                    .append(action.target())
                    .append(action.permitted() ? " (permitted) " : " (blocked) ")
                    .append(action.reason())
                    .append('\n');
        }
        return sb.toString();
    }

    private static String newId() {
        return "comm-" + UUID.randomUUID();
    }
}
