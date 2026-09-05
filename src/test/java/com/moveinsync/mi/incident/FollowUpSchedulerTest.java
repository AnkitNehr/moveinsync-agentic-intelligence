package com.moveinsync.mi.incident;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.policy.ActionGuard;
import com.moveinsync.mi.policy.SlaPolicy;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;

/**
 * Tests for the autonomous follow-up loop and the incident memory it runs on.
 *
 * <p>Drives the loop with an explicit instant rather than waiting on the scheduler, so the whole
 * behaviour — recover, escalate, stay silent when unmeasurable — is deterministic.
 */
class FollowUpSchedulerTest {

    private static final Instant DETECTED = Instant.parse("2026-07-01T00:00:00Z");
    private static final Instant DUE = DETECTED.plus(8, ChronoUnit.DAYS);

    @TempDir
    Path stateDir;

    private IncidentStore store;
    private FollowUpScheduler scheduler;
    private SlaPolicy slaPolicy;

    @BeforeEach
    void setUp() {
        store = new IncidentStore(stateDir.toString());
        store.load();
        slaPolicy = new SlaPolicy(0.95, 1.0, 15.0, 25.0);
        // Replaced per test via rebuild(); default port reports a still-breaching OTA.
        scheduler = rebuild(observationOf(0.9246));
    }

    private FollowUpScheduler rebuild(Optional<MetricObservation> recheckResult) {
        MetricRecheckPort port = (metricId, dimension, entity, period) -> recheckResult;
        return new FollowUpScheduler(
                store, slaPolicy, new ActionGuard(), new AuditLog(stateDir.toString()), provider(port));
    }

    private static Optional<MetricObservation> observationOf(double value) {
        return Optional.of(new MetricObservation(
                "ota", "month", "LOGIN", "2026-07", value, 48_000L,
                References.empty(), 0.8, new Quality(0.99, "HIGH", List.of())));
    }

    /** Minimal ObjectProvider so the scheduler can be built without a Spring context. */
    private static <T> ObjectProvider<T> provider(T instance) {
        return new ObjectProvider<>() {
            @Override
            public T getObject() {
                return instance;
            }

            @Override
            public T getObject(Object... args) {
                return instance;
            }

            @Override
            public T getIfAvailable() {
                return instance;
            }

            @Override
            public T getIfUnique() {
                return instance;
            }
        };
    }

    private Incident openIncident(int priority, int consecutivePeriods) {
        Incident incident = new Incident(
                "inc-001",
                "June OTA drop concentrated in LOGIN / BUS / MANUAL",
                "Campus OTA fell 2.85pts month over month.",
                priority,
                SlaPolicy.BAND_MAJOR,
                List.of("f-1"),
                "LOGIN trips fell 5.17pts against LOGOUT's 0.77pts.",
                List.of(new Evidence("LOGIN OTA fell 5.17pts", "ota", "LOGIN")),
                List.of(),
                new PolicyDecision("SLA-OTA-001", true, consecutivePeriods, false, SlaPolicy.BAND_MAJOR),
                new Quality(0.99, "HIGH", List.of()),
                DETECTED.toString(),
                null,
                IncidentStore.STATUS_OPEN);
        store.open(incident);
        store.scheduleFollowUp(incident.id(), 7, DETECTED);
        return incident;
    }

    @Test
    @DisplayName("a still-breaching metric raises an escalation with raised priority and prefixed title")
    void unrecoveredBreachEscalates() {
        openIncident(3, 1);

        List<Incident> escalations = scheduler.runDueFollowUps(DUE);

        assertThat(escalations).hasSize(1);
        Incident escalation = escalations.get(0);
        assertThat(escalation.title()).startsWith(FollowUpScheduler.ESCALATION_PREFIX);
        assertThat(escalation.priority()).isEqualTo(2);
        assertThat(escalation.policy().consecutivePeriods()).isEqualTo(2);
        assertThat(escalation.policy().escalationPermitted()).isTrue();
        assertThat(escalation.status()).isEqualTo(IncidentStore.STATUS_OPEN);
    }

    @Test
    @DisplayName("escalation unlocks vendor_escalation, which was denied on the original incident")
    void escalationUnlocksVendorEscalation() {
        Incident original = openIncident(3, 1);
        ActionGuard guard = new ActionGuard();

        assertThat(permitted(guard.permittedActions(original, original.policy()), ActionGuard.VENDOR_ESCALATION))
                .isFalse();

        Incident escalation = scheduler.runDueFollowUps(DUE).get(0);

        assertThat(permitted(escalation.recommendedActions(), ActionGuard.VENDOR_ESCALATION)).isTrue();
        assertThat(permitted(escalation.recommendedActions(), ActionGuard.NOTIFY)).isTrue();
        assertThat(permitted(escalation.recommendedActions(), ActionGuard.REVIEW_ALLOCATION)).isFalse();
        assertThat(permitted(escalation.recommendedActions(), ActionGuard.AUTO_REALLOCATE)).isFalse();
    }

    @Test
    @DisplayName("title is not double-prefixed when an escalation is itself escalated")
    void titleIsNotDoublePrefixed() {
        openIncident(3, 1);
        Incident first = scheduler.runDueFollowUps(DUE).get(0);

        List<Incident> second = scheduler.runDueFollowUps(DUE.plus(8, ChronoUnit.DAYS));

        assertThat(second).hasSize(1);
        assertThat(second.get(0).title())
                .isEqualTo(first.title())
                .doesNotContain(FollowUpScheduler.ESCALATION_PREFIX + FollowUpScheduler.ESCALATION_PREFIX);
        assertThat(second.get(0).policy().consecutivePeriods()).isEqualTo(3);
        // Ids escalate from the root incident rather than chaining onto the previous escalation.
        assertThat(first.id()).isEqualTo("inc-001-esc1");
        assertThat(second.get(0).id()).isEqualTo("inc-001-esc2");
    }

    @Test
    @DisplayName("a recovered metric resolves the incident and raises nothing")
    void recoveredBreachResolvesQuietly() {
        openIncident(3, 1);
        scheduler = rebuild(observationOf(0.9700));

        List<Incident> escalations = scheduler.runDueFollowUps(DUE);

        assertThat(escalations).isEmpty();
        assertThat(store.byId("inc-001")).get()
                .extracting(Incident::status)
                .isEqualTo(IncidentStore.STATUS_RESOLVED);
        assertThat(store.allFollowUps().get(0).status()).isEqualTo(FollowUp.RECOVERED);
    }

    @Test
    @DisplayName("an unmeasurable metric leaves the follow-up pending rather than assuming recovery")
    void unmeasurableMetricStaysPending() {
        openIncident(3, 1);
        scheduler = rebuild(Optional.empty());

        List<Incident> escalations = scheduler.runDueFollowUps(DUE);

        assertThat(escalations).isEmpty();
        assertThat(store.allFollowUps().get(0).status()).isEqualTo(FollowUp.PENDING);
        assertThat(store.byId("inc-001")).get()
                .extracting(Incident::status)
                .isEqualTo(IncidentStore.STATUS_OPEN);
    }

    @Test
    @DisplayName("follow-ups are not actioned before they come due")
    void followUpsAreNotActionedEarly() {
        openIncident(3, 1);

        assertThat(scheduler.runDueFollowUps(DETECTED.plus(1, ChronoUnit.DAYS))).isEmpty();
        assertThat(store.allFollowUps().get(0).status()).isEqualTo(FollowUp.PENDING);
    }

    @Test
    @DisplayName("an incident dismissed before its follow-up comes due is never escalated")
    void dismissedIncidentIsNotEscalated() {
        openIncident(3, 1);
        store.dismiss("inc-001", "known Denver depot works, already tracked offline");

        assertThat(scheduler.runDueFollowUps(DUE)).isEmpty();
        assertThat(store.byId("inc-001")).get()
                .extracting(Incident::status)
                .isEqualTo(IncidentStore.STATUS_DISMISSED);
    }

    @Test
    @DisplayName("dismissal writes a suppression that the ranker honours, and it survives a restart")
    void dismissalWritesDurableSuppression() {
        openIncident(3, 1);
        Finding candidate = new Finding(
                "f-9", "ota", "trip_direction", "LOGIN", "2026-08", "2026-07",
                0.92, 0.95, -3.0, 40_000L, -2.8, 0.7, null, null);

        assertThat(store.isSuppressed(candidate)).isFalse();

        store.dismiss("inc-001", "expected during the depot relocation");

        assertThat(store.openSuppressions()).hasSize(1);
        assertThat(store.isSuppressed(candidate)).isTrue();

        // A different metric on the same entity is not covered by this suppression.
        Finding otherMetric = new Finding(
                "f-10", "noshow_rate", "trip_direction", "LOGIN", "2026-08", "2026-07",
                0.09, 0.05, 4.0, 40_000L, 2.9, 0.7, null, null);
        assertThat(store.isSuppressed(otherMetric)).isFalse();

        IncidentStore reloaded = new IncidentStore(stateDir.toString());
        reloaded.load();
        assertThat(reloaded.openSuppressions()).hasSize(1);
        assertThat(reloaded.isSuppressed(candidate)).isTrue();
        assertThat(reloaded.byId("inc-001")).get()
                .extracting(Incident::status)
                .isEqualTo(IncidentStore.STATUS_DISMISSED);
    }

    @Test
    @DisplayName("the follow-up pass is written to the audit trail")
    void followUpIsAudited() {
        openIncident(3, 1);
        AuditLog auditLog = new AuditLog(stateDir.toString());
        scheduler = new FollowUpScheduler(
                store, slaPolicy, new ActionGuard(), auditLog, provider(
                        (MetricRecheckPort) (m, d, e, p) -> observationOf(0.9246)));

        scheduler.runDueFollowUps(DUE);

        List<AuditLog.AuditEntry> entries = auditLog.readAll();
        assertThat(entries).hasSize(1);
        assertThat(entries.get(0).stage()).isEqualTo(AuditLog.STAGE_FOLLOW_UP);
        assertThat(entries.get(0).detected()).containsExactly("inc-001-esc1");
        assertThat(entries.get(0).recommended())
                .extracting(Action::type)
                .contains(ActionGuard.NOTIFY, ActionGuard.VENDOR_ESCALATION);
    }

    @Test
    @DisplayName("the loop is inert, not broken, when no metric re-check port is registered")
    void missingPortLeavesFollowUpsPending() {
        openIncident(3, 1);
        FollowUpScheduler portless = new FollowUpScheduler(
                store, slaPolicy, new ActionGuard(), new AuditLog(stateDir.toString()), provider(null));

        assertThat(portless.runDueFollowUps(DUE)).isEmpty();
        assertThat(store.allFollowUps().get(0).status()).isEqualTo(FollowUp.PENDING);
    }

    @Test
    @DisplayName("a metric layer that throws does not take the governance loop down")
    void recheckFailureIsContained() {
        openIncident(3, 1);
        FollowUpScheduler failing = new FollowUpScheduler(
                store, slaPolicy, new ActionGuard(), new AuditLog(stateDir.toString()),
                provider((MetricRecheckPort) (m, d, e, p) -> {
                    throw new IllegalStateException("DuckDB connection closed");
                }));

        assertThat(failing.runDueFollowUps(DUE)).isEmpty();
        assertThat(store.allFollowUps().get(0).status()).isEqualTo(FollowUp.PENDING);
    }

    private static boolean permitted(List<Action> actions, String type) {
        return actions.stream()
                .filter(action -> type.equals(action.type()))
                .findFirst()
                .map(Action::permitted)
                .orElseThrow(() -> new AssertionError("action not emitted: " + type));
    }
}
