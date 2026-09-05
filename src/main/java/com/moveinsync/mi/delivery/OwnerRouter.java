package com.moveinsync.mi.delivery;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import java.util.Locale;
import java.util.Optional;

/**
 * Picks who gets told, from the metric and the dimension that actually explains the movement.
 *
 * <p>{@code ActionGuard} used to copy the first evidence entity into {@code Action.target}. That
 * names a slice (Clearwater Campus, LOGIN) rather than an owner. Routing is a separate judgement:
 * morning-bus / manual-route movements belong at the routing desk, vendor-shaped movements belong
 * with vendor ops, escort coverage belongs with the facilities head, and a shift-level break belongs
 * with the line manager of that shift.
 */
public final class OwnerRouter {

    private OwnerRouter() {
    }

    /**
     * Who should receive a communication about this incident.
     *
     * @param persona    one of {@link NarrativePort#PERSONAS}
     * @param recipient  desk label shown on the action and the outbox row
     * @param desk       short function name (routing, vendor, safety, shift)
     */
    public record Owner(String persona, String recipient, String desk) {
    }

    public static Owner route(Incident incident, AttributionResult attribution) {
        String metric = firstMetric(incident);
        String winner = winnerDimension(attribution);

        if (metric != null && metric.toLowerCase(Locale.ROOT).contains("escort")) {
            return new Owner(
                    NarrativePort.FACILITIES_HEAD,
                    "Transport & facilities head",
                    "safety");
        }
        if (isVendorDimension(winner) && vendorExplains(attribution)) {
            return new Owner(
                    NarrativePort.TRANSPORT_MANAGER,
                    "Vendor operations",
                    "vendor");
        }
        if (isShiftDimension(winner)) {
            return new Owner(
                    NarrativePort.LINE_MANAGER,
                    "Line manager — " + winnerEntity(attribution, incident),
                    "shift");
        }
        return new Owner(
                NarrativePort.TRANSPORT_MANAGER,
                "Routing desk",
                "routing");
    }

    public static boolean isVendorDimension(String dimension) {
        if (dimension == null) {
            return false;
        }
        String d = dimension.toLowerCase(Locale.ROOT).replace("-", "_");
        return d.equals("vendor") || d.equals("vendor_id");
    }

    static boolean isShiftDimension(String dimension) {
        if (dimension == null) {
            return false;
        }
        String d = dimension.toLowerCase(Locale.ROOT).replace("-", "_");
        return d.equals("shift_type") || d.equals("shift");
    }

    public static String winnerDimension(AttributionResult attribution) {
        if (attribution == null) {
            return null;
        }
        return attribution.winner().map(DimensionAttribution::dimension).orElse(null);
    }

    public static double vendorPower(AttributionResult attribution) {
        if (attribution == null) {
            return 0.0;
        }
        Optional<DimensionAttribution> vendor = attribution.forDimension("vendor");
        if (vendor.isEmpty()) {
            vendor = attribution.forDimension("vendor_id");
        }
        return vendor.map(DimensionAttribution::explanatoryPower).orElse(0.0);
    }

    private static boolean vendorExplains(AttributionResult attribution) {
        if (attribution == null || attribution.winner().isEmpty()) {
            return false;
        }
        return isVendorDimension(attribution.winner().get().dimension());
    }

    private static String winnerEntity(AttributionResult attribution, Incident incident) {
        if (attribution != null) {
            String leader = attribution.winner()
                    .map(DimensionAttribution::leader)
                    .map(c -> c == null ? null : c.entity())
                    .orElse(null);
            if (leader != null && !leader.isBlank()) {
                return leader;
            }
        }
        return firstEntity(incident);
    }

    public static String firstMetric(Incident incident) {
        if (incident == null) {
            return null;
        }
        for (Evidence evidence : incident.evidence()) {
            if (evidence != null && evidence.metricId() != null && !evidence.metricId().isBlank()) {
                return evidence.metricId();
            }
        }
        return null;
    }

    static String firstEntity(Incident incident) {
        if (incident == null) {
            return "operations";
        }
        for (Evidence evidence : incident.evidence()) {
            if (evidence != null && evidence.entity() != null && !evidence.entity().isBlank()) {
                return evidence.entity();
            }
        }
        return incident.id() == null || incident.id().isBlank() ? "operations" : incident.id();
    }
}
