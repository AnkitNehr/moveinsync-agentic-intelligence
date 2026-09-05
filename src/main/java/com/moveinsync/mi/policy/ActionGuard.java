package com.moveinsync.mi.policy;

import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * Decides which remediation types may be taken automatically for an incident.
 *
 * <p>The platform proposes; humans dispose. Every action the system can name is emitted on every
 * incident, but each one carries an explicit {@code permitted} flag and a reason. Denied actions are
 * <strong>not</strong> filtered out — a blocked escalation that silently disappears is
 * indistinguishable from an escalation nobody thought of, and the whole point of a guard is that its
 * refusals are visible and auditable.
 *
 * <h2>The ladder</h2>
 * <ul>
 *   <li>{@link #NOTIFY} — always permitted. Telling someone what happened changes nothing on the
 *       ground and carries no downside risk.</li>
 *   <li>{@link #VENDOR_ESCALATION} — permitted only once the breach has persisted for at least
 *       {@link SlaPolicy#ESCALATION_MIN_CONSECUTIVE_PERIODS} consecutive periods. One bad month is
 *       noise; two in a row is a pattern worth putting in front of a vendor.</li>
 *   <li>{@link #REVIEW_ALLOCATION} — never auto-permitted. Reallocating volume changes cost exposure
 *       and contractual commitments, so it requires human approval however clear the data looks.</li>
 *   <li>{@link #AUTO_REALLOCATE} — never permitted under any circumstances. It is emitted only so
 *       that the refusal is on the record.</li>
 * </ul>
 *
 * <p>Deterministic: the same incident and decision always produce the same list, in the same order.
 */
@Service
public class ActionGuard {

    /** Inform the owning stakeholders. Always permitted. */
    public static final String NOTIFY = "notify";
    /** Raise the breach formally with the vendor. Permitted from the second consecutive breach. */
    public static final String VENDOR_ESCALATION = "vendor_escalation";
    /** Reconsider how volume is distributed. Always requires human approval. */
    public static final String REVIEW_ALLOCATION = "review_allocation";
    /** Autonomously move volume between vendors. Never permitted. */
    public static final String AUTO_REALLOCATE = "auto_reallocate";

    private static final String DEFAULT_TARGET = "operations";

    /**
     * Produces the policy-gated action list for an incident.
     *
     * @param incident the incident under consideration; may be null, in which case a generic target
     *                 is used and the ladder is still fully reported
     * @param decision the governing SLA verdict; a null decision is treated as zero breach depth
     * @return four actions in fixed order, each with {@code permitted} and {@code reason} populated
     */
    public List<Action> permittedActions(Incident incident, PolicyDecision decision) {
        String target = targetFor(incident);
        int consecutivePeriods = decision == null ? 0 : Math.max(0, decision.consecutivePeriods());
        boolean escalationEarned = consecutivePeriods >= SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS;

        return List.of(
                new Action(
                        NOTIFY,
                        target,
                        true,
                        "Notification is always permitted: it informs the owning team without "
                                + "altering allocation, contracts or cost exposure."),
                new Action(
                        VENDOR_ESCALATION,
                        target,
                        escalationEarned,
                        escalationEarned
                                ? "Breach sustained for " + consecutivePeriods
                                        + " consecutive periods, which meets the "
                                        + SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS
                                        + "-period threshold for formal vendor escalation."
                                : "Breach depth is " + consecutivePeriods + " period(s); formal vendor "
                                        + "escalation requires at least "
                                        + SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS
                                        + " consecutive periods so a single-period dip is not "
                                        + "treated as a pattern."),
                new Action(
                        REVIEW_ALLOCATION,
                        target,
                        false,
                        "Allocation review shifts volume between vendors and changes cost and "
                                + "contractual exposure; it is never auto-permitted and requires "
                                + "explicit human approval."),
                new Action(
                        AUTO_REALLOCATE,
                        target,
                        false,
                        "Autonomous reallocation is never permitted by policy. The platform "
                                + "recommends; a human decides and executes."));
    }

    /**
     * Convenience overload for incidents that already carry their own {@link PolicyDecision}.
     */
    public List<Action> permittedActions(Incident incident) {
        return permittedActions(incident, incident == null ? null : incident.policy());
    }

    /** Whether a specific action type is permitted for this incident. */
    public boolean isPermitted(String actionType, Incident incident, PolicyDecision decision) {
        if (actionType == null) {
            return false;
        }
        return permittedActions(incident, decision).stream()
                .filter(action -> actionType.equalsIgnoreCase(action.type()))
                .findFirst()
                .map(Action::permitted)
                .orElse(false);
    }

    /**
     * Resolves who the actions are aimed at.
     *
     * <p>Prefers the entity named by the incident's first evidence item, which is the dimension
     * member the narrative is actually about (a vendor id, an office, a product type). Falls back
     * through the finding ids to a generic owner so an action never carries a null target.
     */
    private String targetFor(Incident incident) {
        if (incident == null) {
            return DEFAULT_TARGET;
        }
        for (Evidence evidence : incident.evidence()) {
            if (evidence != null && evidence.entity() != null && !evidence.entity().isBlank()) {
                return evidence.entity();
            }
        }
        for (String findingId : incident.findingIds()) {
            if (findingId != null && !findingId.isBlank()) {
                return findingId;
            }
        }
        return incident.id() == null || incident.id().isBlank() ? DEFAULT_TARGET : incident.id();
    }
}
