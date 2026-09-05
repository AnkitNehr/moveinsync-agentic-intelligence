package com.moveinsync.mi.policy;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.delivery.OwnerRouter;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import java.util.List;
import java.util.Locale;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
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
 *       ground and carries no downside risk. The recipient is chosen by {@link OwnerRouter}, not
 *       copied from the first evidence entity.</li>
 *   <li>{@link #VENDOR_ESCALATION} — permitted only when the breach has persisted for at least
 *       {@link SlaPolicy#ESCALATION_MIN_CONSECUTIVE_PERIODS} consecutive periods <em>and</em> the
 *       attribution evidence says vendors actually explain the movement. Persistence without vendor
 *       signal is a routing-desk conversation, not a vendor letter.</li>
 *   <li>{@link #REVIEW_ALLOCATION} — never auto-permitted.</li>
 *   <li>{@link #AUTO_REALLOCATE} — never permitted under any circumstances.</li>
 * </ul>
 */
@Service
public class ActionGuard {

    public static final String NOTIFY = "notify";
    public static final String VENDOR_ESCALATION = "vendor_escalation";
    public static final String REVIEW_ALLOCATION = "review_allocation";
    public static final String AUTO_REALLOCATE = "auto_reallocate";

    public static final double DEFAULT_VENDOR_ESCALATION_MIN_POWER = 0.25;

    private final double vendorEscalationMinPower;

    public ActionGuard() {
        this(DEFAULT_VENDOR_ESCALATION_MIN_POWER);
    }

    @Autowired
    public ActionGuard(
            @Value("${app.policy.vendor-escalation-min-power:0.25}") double vendorEscalationMinPower) {
        this.vendorEscalationMinPower = Double.isFinite(vendorEscalationMinPower)
                ? Math.clamp(vendorEscalationMinPower, 0.0, 1.0)
                : DEFAULT_VENDOR_ESCALATION_MIN_POWER;
    }

    public List<Action> permittedActions(Incident incident, PolicyDecision decision) {
        return permittedActions(incident, decision, null);
    }

    public List<Action> permittedActions(Incident incident) {
        return permittedActions(incident, incident == null ? null : incident.policy(), null);
    }

    /**
     * Produces the policy-gated action list for an incident.
     *
     * @param incident    the incident under consideration
     * @param decision    the governing SLA verdict; a null decision is treated as zero breach depth
     * @param attribution ranked dimension decompositions; null means vendor evidence is absent
     */
    public List<Action> permittedActions(
            Incident incident, PolicyDecision decision, AttributionResult attribution) {

        OwnerRouter.Owner owner = OwnerRouter.route(incident, attribution);
        int consecutivePeriods = decision == null ? 0 : Math.max(0, decision.consecutivePeriods());
        boolean persistenceEarned = consecutivePeriods >= SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS;
        VendorEvidence vendor = VendorEvidence.of(attribution, vendorEscalationMinPower);
        boolean vendorPermitted = persistenceEarned && vendor.supportsEscalation();

        return List.of(
                new Action(
                        NOTIFY,
                        owner.recipient(),
                        true,
                        "Notification is always permitted: it informs " + owner.recipient()
                                + " without altering allocation, contracts or cost exposure."),
                new Action(
                        VENDOR_ESCALATION,
                        owner.desk().equals("vendor") ? owner.recipient() : "Vendor operations",
                        vendorPermitted,
                        vendorEscalationReason(persistenceEarned, consecutivePeriods, vendor, owner)),
                new Action(
                        REVIEW_ALLOCATION,
                        owner.recipient(),
                        false,
                        "Allocation review shifts volume between vendors and changes cost and "
                                + "contractual exposure; it is never auto-permitted and requires "
                                + "explicit human approval."),
                new Action(
                        AUTO_REALLOCATE,
                        owner.recipient(),
                        false,
                        "Autonomous reallocation is never permitted by policy. The platform "
                                + "recommends; a human decides and executes."));
    }

    public boolean isPermitted(String actionType, Incident incident, PolicyDecision decision) {
        return isPermitted(actionType, incident, decision, null);
    }

    public boolean isPermitted(
            String actionType, Incident incident, PolicyDecision decision, AttributionResult attribution) {
        if (actionType == null) {
            return false;
        }
        return permittedActions(incident, decision, attribution).stream()
                .filter(action -> actionType.equalsIgnoreCase(action.type()))
                .findFirst()
                .map(Action::permitted)
                .orElse(false);
    }

    public double vendorEscalationMinPower() {
        return vendorEscalationMinPower;
    }

    private static String vendorEscalationReason(
            boolean persistenceEarned, int consecutivePeriods, VendorEvidence vendor, OwnerRouter.Owner owner) {

        if (vendorPermitted(persistenceEarned, vendor)) {
            return "Breach sustained for " + consecutivePeriods
                    + " consecutive periods and vendor explanatory power "
                    + formatPower(vendor.power())
                    + " meets the evidence bar. Formal vendor escalation is permitted.";
        }
        String persistenceBit = persistenceEarned
                ? "Breach depth is " + consecutivePeriods + " period(s), which meets the persistence bar"
                : "Breach depth is " + consecutivePeriods + " period(s); formal vendor escalation "
                        + "requires at least " + SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS
                        + " consecutive periods so a single-period dip is not treated as a pattern";
        return persistenceBit + ", but " + vendor.reason()
                + " " + owner.recipient() + " is the owner.";
    }

    private static boolean vendorPermitted(boolean persistenceEarned, VendorEvidence vendor) {
        return persistenceEarned && vendor.supportsEscalation();
    }

    private static String formatPower(double power) {
        return String.format(Locale.ROOT, "%.2f", power);
    }

    /**
     * Whether vendors actually explain the movement, as opposed to merely being a grain we scanned.
     */
    record VendorEvidence(boolean supportsEscalation, double power, String reason) {

        static VendorEvidence of(AttributionResult attribution, double minPower) {
            if (attribution == null || attribution.ranked().isEmpty()) {
                return new VendorEvidence(
                        false,
                        0.0,
                        "vendor mix has not been shown to explain this movement (no attribution attached);");
            }
            double power = OwnerRouter.vendorPower(attribution);
            String winner = OwnerRouter.winnerDimension(attribution);
            if (OwnerRouter.isVendorDimension(winner)) {
                return new VendorEvidence(
                        true,
                        power,
                        "vendor is the winning dimension (explanatory power " + formatPower(power) + ");");
            }
            if (power + 1e-12 >= minPower) {
                return new VendorEvidence(
                        true,
                        power,
                        "vendor explanatory power " + formatPower(power) + " meets the "
                                + formatPower(minPower) + " bar;");
            }
            return new VendorEvidence(
                    false,
                    power,
                    "vendor explanatory power " + formatPower(power)
                            + " is below the " + formatPower(minPower)
                            + " bar;");
        }
    }
}
