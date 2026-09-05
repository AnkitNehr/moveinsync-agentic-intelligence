package com.moveinsync.mi.model;

/**
 * A recommended remediation, gated by policy.
 *
 * <p>The platform proposes; it does not act unilaterally. {@code permitted} records whether the
 * governing policy allows this action to be taken automatically, and {@code reason} explains the
 * verdict either way — so a blocked escalation is visibly blocked rather than silently dropped.
 *
 * @param type      action kind, e.g. {@code NOTIFY_VENDOR}, {@code ESCALATE}, {@code OPEN_TICKET}
 * @param target    who or what the action is directed at, e.g. a vendor id or an office
 * @param permitted whether policy permits this action for the current incident
 * @param reason    justification for the permit / deny decision
 */
public record Action(String type, String target, boolean permitted, String reason) {
}
