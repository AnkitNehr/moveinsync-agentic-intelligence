package com.moveinsync.mi.model;

/**
 * Deterministic governance verdict applied to an incident.
 *
 * <p>Escalation is decided by rules, not by the language model. A one-off dip and a third
 * consecutive breach of the same SLA are different situations, and {@code consecutivePeriods} is
 * what separates them.
 *
 * @param ruleId               identifier of the policy rule that was evaluated
 * @param breached             whether the rule's condition is currently violated
 * @param consecutivePeriods   number of consecutive periods the rule has been breached
 * @param escalationPermitted  whether the rule authorises escalation at this breach depth
 * @param severityBand         resulting band, e.g. {@code CRITICAL} / {@code HIGH} / {@code MEDIUM} / {@code LOW}
 */
public record PolicyDecision(
        String ruleId,
        boolean breached,
        int consecutivePeriods,
        boolean escalationPermitted,
        String severityBand) {
}
