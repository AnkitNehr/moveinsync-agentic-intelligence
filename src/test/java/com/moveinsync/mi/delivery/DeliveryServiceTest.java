package com.moveinsync.mi.delivery;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import com.moveinsync.mi.policy.SlaPolicy;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DeliveryServiceTest {

    @TempDir
    Path stateDir;

    @Test
    void permittedNotifyIsSentAndBlockedVendorIsVisible() {
        OutboxStore store = new OutboxStore(stateDir.toString());
        store.load();
        DeliveryService delivery = new DeliveryService(store, new ConsoleNotificationSink());

        Incident incident = new Incident(
                "inc-ota-2026-06",
                "June OTA drop concentrated in LOGIN / BUS / MANUAL",
                "Campus OTA fell 2.85pts.",
                1,
                SlaPolicy.BAND_MAJOR,
                List.of("f-1"),
                "LOGIN trips fell 5.17pts against LOGOUT's 0.77pts.",
                List.of(new Evidence("LOGIN OTA fell 5.17pts", "ota", "LOGIN")),
                List.of(
                        new com.moveinsync.mi.model.Action(
                                "notify", "Routing desk", true, "always"),
                        new com.moveinsync.mi.model.Action(
                                "vendor_escalation", "Vendor operations", false,
                                "vendor explanatory power 0.07 is below the 0.25 bar; Routing desk is the owner."),
                        new com.moveinsync.mi.model.Action(
                                "auto_reallocate", "Routing desk", false, "never")),
                new PolicyDecision("SLA-OTA-001", true, 1, false, SlaPolicy.BAND_MAJOR),
                new Quality(0.99, "HIGH", List.of()),
                "2026-07-01T00:00:00Z",
                null,
                "OPEN");

        List<Communication> written = delivery.publish(incident, null);

        assertThat(written).extracting(Communication::status)
                .contains(Communication.SENT, Communication.BLOCKED);
        assertThat(written).anyMatch(c ->
                Communication.SENT.equals(c.status()) && NarrativePort.TRANSPORT_MANAGER.equals(c.persona()));
        assertThat(written).anyMatch(c ->
                Communication.BLOCKED.equals(c.status())
                        && "vendor_escalation".equals(c.actionType())
                        && c.blockedReason().contains("0.07"));
        assertThat(store.all()).hasSize(written.size());
    }
}
