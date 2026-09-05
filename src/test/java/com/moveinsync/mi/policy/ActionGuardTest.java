package com.moveinsync.mi.policy;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.DimensionAttribution;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Quality;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class ActionGuardTest {

    private final ActionGuard guard = new ActionGuard();

    @Test
    @DisplayName("notify is always permitted and routed to the routing desk when vendors do not win")
    void notifyAlwaysPermittedToRoutingDesk() {
        List<Action> actions = guard.permittedActions(otaIncident(1), policy(1), loginWinsVendorWeak());

        Action notify = action(actions, ActionGuard.NOTIFY);
        assertThat(notify.permitted()).isTrue();
        assertThat(notify.target()).isEqualTo("Routing desk");
    }

    @Test
    @DisplayName("vendor escalation stays blocked on a single period even if vendors win")
    void singlePeriodBlocksVendorEvenWhenVendorsWin() {
        List<Action> actions = guard.permittedActions(otaIncident(1), policy(1), vendorWins());

        Action vendor = action(actions, ActionGuard.VENDOR_ESCALATION);
        assertThat(vendor.permitted()).isFalse();
        assertThat(vendor.reason()).contains("consecutive periods");
    }

    @Test
    @DisplayName("two periods still block vendor escalation when vendor power is 0.07")
    void persistenceWithoutVendorEvidenceBlocks() {
        List<Action> actions = guard.permittedActions(otaIncident(2), policy(2), loginWinsVendorWeak());

        Action vendor = action(actions, ActionGuard.VENDOR_ESCALATION);
        assertThat(vendor.permitted()).isFalse();
        assertThat(vendor.reason()).contains("0.07");
        assertThat(vendor.reason()).contains("Routing desk");
    }

    @Test
    @DisplayName("two periods plus vendor as winner permits vendor escalation")
    void persistenceAndVendorWinnerPermits() {
        List<Action> actions = guard.permittedActions(otaIncident(2), policy(2), vendorWins());

        assertThat(action(actions, ActionGuard.VENDOR_ESCALATION).permitted()).isTrue();
        assertThat(action(actions, ActionGuard.NOTIFY).target()).isEqualTo("Vendor operations");
    }

    @Test
    @DisplayName("auto_reallocate and review_allocation are never permitted")
    void neverAutoReallocate() {
        List<Action> actions = guard.permittedActions(otaIncident(5), policy(5), vendorWins());

        assertThat(action(actions, ActionGuard.REVIEW_ALLOCATION).permitted()).isFalse();
        assertThat(action(actions, ActionGuard.AUTO_REALLOCATE).permitted()).isFalse();
    }

    @Test
    @DisplayName("escort incidents route notify to the facilities head")
    void escortRoutesToFacilitiesHead() {
        Incident escort = new Incident(
                "inc-escort-2026-07",
                "Night escort coverage fell at Crestwood",
                "Coverage 48% against a 100% policy.",
                1,
                SlaPolicy.BAND_CRITICAL,
                List.of("f-1"),
                "Night escort coverage is an approximation of policy compliance.",
                List.of(new Evidence("escort_compliance at Crestwood is 0.48", "escort_compliance", "Crestwood")),
                List.of(),
                policy(1),
                new Quality(1.0, "HIGH", List.of()),
                "2026-07-01T00:00:00Z",
                null,
                "OPEN");

        Action notify = action(guard.permittedActions(escort, policy(1), null), ActionGuard.NOTIFY);
        assertThat(notify.target()).isEqualTo("Transport & facilities head");
    }

    private static Action action(List<Action> actions, String type) {
        return actions.stream()
                .filter(a -> type.equals(a.type()))
                .findFirst()
                .orElseThrow();
    }

    private static PolicyDecision policy(int consecutive) {
        return new PolicyDecision(
                "SLA-OTA-001",
                true,
                consecutive,
                consecutive >= SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS,
                SlaPolicy.BAND_MAJOR);
    }

    private static Incident otaIncident(int consecutive) {
        return new Incident(
                "inc-ota-2026-06",
                "June OTA drop concentrated in LOGIN / BUS / MANUAL",
                "Campus OTA fell 2.85pts.",
                1,
                SlaPolicy.BAND_MAJOR,
                List.of("f-1"),
                "LOGIN trips fell 5.17pts against LOGOUT's 0.77pts.",
                List.of(new Evidence("LOGIN OTA fell 5.17pts", "ota", "LOGIN")),
                List.of(),
                policy(consecutive),
                new Quality(0.99, "HIGH", List.of()),
                "2026-07-01T00:00:00Z",
                null,
                "OPEN");
    }

    private static AttributionResult loginWinsVendorWeak() {
        DimensionAttribution direction = new DimensionAttribution(
                "trip_direction", -0.0286, -0.0241, 0.85, 0.80, 0.70, 0.0, 2, 210_000L,
                List.of(new Contribution("LOGIN", -0.0241, -0.0002, -0.0243, 0.51, 0.52)));
        DimensionAttribution vendor = new DimensionAttribution(
                "vendor", -0.0286, -0.002, 0.07, 0.12, 0.05, 0.0, 23, 210_000L,
                List.of(new Contribution("Sneha", -0.001, 0.0, -0.001, 0.04, 0.04)));
        return new AttributionResult("ota", "2026-06", "2026-05", -0.0286, List.of(direction, vendor));
    }

    private static AttributionResult vendorWins() {
        DimensionAttribution vendor = new DimensionAttribution(
                "vendor", -0.0286, -0.022, 0.72, 0.65, 0.55, 0.0, 23, 210_000L,
                List.of(new Contribution("WorstVendor", -0.018, 0.0, -0.018, 0.12, 0.11)));
        DimensionAttribution direction = new DimensionAttribution(
                "trip_direction", -0.0286, -0.01, 0.20, 0.30, 0.10, 0.0, 2, 210_000L,
                List.of());
        return new AttributionResult("ota", "2026-06", "2026-05", -0.0286, List.of(vendor, direction));
    }
}
