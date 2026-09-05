package com.moveinsync.mi.policy;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.PolicyDecision;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/**
 * Unit tests for the SLA rule engine.
 *
 * <p>No Spring context: the policy is constructed with plain target values, which is the whole point
 * of keeping it free of a configuration object. Targets mirror {@code application.yml} — OTA 0.95,
 * escort compliance 1.0, alert acknowledgement 15 minutes, cost per km 25.0.
 */
class SlaPolicyTest {

    private static final double OTA_TARGET = 0.95;
    private static final double ESCORT_TARGET = 1.0;
    private static final double ACK_TARGET = 15.0;
    private static final double CPK_TARGET = 25.0;

    private final SlaPolicy policy = new SlaPolicy(OTA_TARGET, ESCORT_TARGET, ACK_TARGET, CPK_TARGET);

    /** Builds a finding carrying only the fields the policy reads. */
    private static Finding finding(String metricId, double current, double prior) {
        return new Finding(
                "f-1", metricId, "business_unit", "vanta-Sea", "2026-06", "2026-05",
                current, prior, current - prior, 10_000L, -3.1, 0.9, null, null);
    }

    @Nested
    @DisplayName("higher_is_better metrics")
    class HigherIsBetter {

        @Test
        @DisplayName("value below target is breached")
        void belowTargetIsBreached() {
            // Real June campus OTA against the configured 0.95 target.
            PolicyDecision decision = policy.decide(finding("ota", 0.9246, 0.9531));

            assertThat(decision.breached()).isTrue();
            assertThat(decision.ruleId()).isEqualTo("SLA-OTA-001");
            assertThat(decision.severityBand()).isEqualTo(SlaPolicy.BAND_MAJOR);
        }

        @Test
        @DisplayName("value above target is not breached")
        void aboveTargetIsNotBreached() {
            // Real May campus OTA, comfortably inside target.
            PolicyDecision decision = policy.decide(finding("ota", 0.9531, 0.9400));

            assertThat(decision.breached()).isFalse();
            assertThat(decision.severityBand()).isEqualTo(SlaPolicy.BAND_NONE);
            assertThat(decision.consecutivePeriods()).isZero();
            assertThat(decision.escalationPermitted()).isFalse();
        }

        @Test
        @DisplayName("value exactly on target is not breached")
        void exactlyOnTargetIsNotBreached() {
            assertThat(policy.decide(finding("ota", OTA_TARGET, OTA_TARGET)).breached()).isFalse();
        }

        @Test
        @DisplayName("escort compliance is zero-tolerance: 99.9% still breaches a 1.0 target")
        void escortComplianceIsZeroTolerance() {
            PolicyDecision decision = policy.decide(finding("escort_compliance", 0.999, 1.0));

            assertThat(decision.breached()).isTrue();
            assertThat(decision.ruleId()).isEqualTo("SLA-ESCORT-001");
            assertThat(decision.severityBand()).isEqualTo(SlaPolicy.BAND_MINOR);
        }
    }

    @Nested
    @DisplayName("lower_is_better metrics are inverted")
    class LowerIsBetter {

        @Test
        @DisplayName("acknowledgement slower than target is breached even though the number is larger")
        void aboveTargetIsBreached() {
            PolicyDecision decision = policy.decide(finding("alert_ack_minutes", 20.0, 12.0));

            assertThat(decision.breached()).isTrue();
            assertThat(decision.ruleId()).isEqualTo("SLA-ACK-001");
        }

        @Test
        @DisplayName("acknowledgement faster than target is not breached")
        void belowTargetIsNotBreached() {
            PolicyDecision decision = policy.decide(finding("alert_ack_minutes", 9.0, 8.0));

            assertThat(decision.breached()).isFalse();
            assertThat(decision.severityBand()).isEqualTo(SlaPolicy.BAND_NONE);
        }

        @Test
        @DisplayName("cost per km above target is breached; below is not")
        void costPerKmInverted() {
            assertThat(policy.decide(finding("cost_per_km", 31.0, 24.0)).breached()).isTrue();
            assertThat(policy.decide(finding("cost_per_km", 22.0, 24.0)).breached()).isFalse();
        }

        @Test
        @DisplayName("the same numeric value breaches one direction and passes the other")
        void directionActuallyFlipsTheComparison() {
            // 0.9 is below the 0.95 OTA target (breach) but well below the 15-minute ack target (pass).
            assertThat(policy.breaches("ota", 0.90)).isTrue();
            assertThat(policy.breaches("alert_ack_minutes", 0.90)).isFalse();
        }
    }

    @Nested
    @DisplayName("severity band boundaries")
    class SeverityBands {

        @Test
        @DisplayName("bands are keyed off the relative gap, inclusive at the lower edge")
        void bandBoundaries() {
            assertThat(SlaPolicy.bandFor(0.0)).isEqualTo(SlaPolicy.BAND_NONE);
            assertThat(SlaPolicy.bandFor(-0.10)).isEqualTo(SlaPolicy.BAND_NONE);

            assertThat(SlaPolicy.bandFor(0.0001)).isEqualTo(SlaPolicy.BAND_MINOR);
            assertThat(SlaPolicy.bandFor(SlaPolicy.MAJOR_THRESHOLD - 1e-9))
                    .isEqualTo(SlaPolicy.BAND_MINOR);

            assertThat(SlaPolicy.bandFor(SlaPolicy.MAJOR_THRESHOLD)).isEqualTo(SlaPolicy.BAND_MAJOR);
            assertThat(SlaPolicy.bandFor(SlaPolicy.CRITICAL_THRESHOLD - 1e-9))
                    .isEqualTo(SlaPolicy.BAND_MAJOR);

            assertThat(SlaPolicy.bandFor(SlaPolicy.CRITICAL_THRESHOLD))
                    .isEqualTo(SlaPolicy.BAND_CRITICAL);
            assertThat(SlaPolicy.bandFor(0.50)).isEqualTo(SlaPolicy.BAND_CRITICAL);
        }

        @ParameterizedTest(name = "OTA {0} -> {1}")
        @CsvSource({
            // target 0.95; relative gap = (0.95 - value) / 0.95
            "0.9600, NONE",
            "0.9500, NONE",
            "0.9469, MINOR",   // real July value, gap 0.0033 relative
            "0.9330, MINOR",   // gap 0.0179 relative, just under the MAJOR edge
            "0.9290, MAJOR",   // gap 0.0221 relative, just past the MAJOR edge
            "0.9246, MAJOR",   // real June value, gap 0.0267 relative
            "0.9000, CRITICAL" // gap 0.0526 relative, past the CRITICAL edge
        })
        @DisplayName("real OTA values land in the intended bands")
        void otaBands(double value, String expectedBand) {
            assertThat(policy.band("ota", value)).isEqualTo(expectedBand);
        }

        @Test
        @DisplayName("bands are comparable across units: a 20% overshoot is CRITICAL in any metric")
        void bandsAreUnitIndependent() {
            assertThat(policy.band("alert_ack_minutes", ACK_TARGET * 1.2))
                    .isEqualTo(SlaPolicy.BAND_CRITICAL);
            assertThat(policy.band("cost_per_km", CPK_TARGET * 1.2))
                    .isEqualTo(SlaPolicy.BAND_CRITICAL);
            assertThat(policy.band("ota", OTA_TARGET * 0.8)).isEqualTo(SlaPolicy.BAND_CRITICAL);
        }
    }

    @Nested
    @DisplayName("consecutive breach periods")
    class ConsecutivePeriods {

        @Test
        @DisplayName("a first breach after a clean prior period does not authorise escalation")
        void firstBreachDoesNotEscalate() {
            PolicyDecision decision = policy.decide(finding("ota", 0.9246, 0.9531));

            assertThat(decision.consecutivePeriods()).isEqualTo(1);
            assertThat(decision.escalationPermitted()).isFalse();
        }

        @Test
        @DisplayName("a breach following a breaching prior period authorises escalation")
        void secondConsecutiveBreachEscalates() {
            PolicyDecision decision = policy.decide(finding("ota", 0.9200, 0.9300));

            assertThat(decision.consecutivePeriods()).isEqualTo(2);
            assertThat(decision.escalationPermitted()).isTrue();
        }

        @Test
        @DisplayName("history from incident memory deepens the streak")
        void supplierHistoryExtendsTheStreak() {
            PolicyDecision decision = policy.decide(finding("ota", 0.9200, 0.9300), 4);

            assertThat(decision.consecutivePeriods()).isEqualTo(5);
            assertThat(decision.escalationPermitted()).isTrue();
        }

        @Test
        @DisplayName("recovery resets the streak to zero regardless of history")
        void recoveryResetsTheStreak() {
            PolicyDecision decision = policy.decide(finding("ota", 0.9700, 0.9200), 7);

            assertThat(decision.breached()).isFalse();
            assertThat(decision.consecutivePeriods()).isZero();
            assertThat(decision.escalationPermitted()).isFalse();
        }
    }

    @Nested
    @DisplayName("robustness")
    class Robustness {

        @Test
        @DisplayName("percent-scaled ratio values are reconciled against fractional targets")
        void percentScaledValuesAreReconciled() {
            // The scanner reports OTA as 92.46, the SLA target is 0.95. A naive comparison would
            // report a spectacular pass on a month that actually breached.
            assertThat(policy.breaches("ota", 92.46)).isTrue();
            assertThat(policy.band("ota", 92.46)).isEqualTo(SlaPolicy.BAND_MAJOR);
            assertThat(policy.breaches("ota", 95.31)).isFalse();
        }

        @Test
        @DisplayName("absolute metrics are never rescaled")
        void absoluteMetricsAreNotRescaled() {
            // 20 minutes must stay 20 minutes, not become 0.2.
            assertThat(policy.breaches("alert_ack_minutes", 20.0)).isTrue();
        }

        @Test
        @DisplayName("metrics with no configured SLA are never breached")
        void metricsWithoutSlaAreNeverBreached() {
            PolicyDecision decision = policy.decide(finding("noshow_rate", 0.42, 0.05));

            assertThat(decision.breached()).isFalse();
            assertThat(decision.ruleId()).isEqualTo(SlaPolicy.RULE_NO_SLA);
            assertThat(decision.severityBand()).isEqualTo(SlaPolicy.BAND_NONE);
        }

        @Test
        @DisplayName("metric ids are matched case- and separator-insensitively")
        void metricIdsAreCanonicalised() {
            assertThat(policy.ruleFor("COST-PER-KM")).isPresent();
            assertThat(policy.ruleFor("cost per km")).isPresent();
            assertThat(policy.ruleFor("On_Time_Arrival")).map(SlaPolicy.SlaRule::ruleId)
                    .contains("SLA-OTA-001");
        }

        @Test
        @DisplayName("null and non-finite values are not breaches")
        void unmeasurableValuesAreNotBreaches() {
            assertThat(policy.breaches("ota", null)).isFalse();
            assertThat(policy.breaches("ota", Double.NaN)).isFalse();
            assertThat(policy.breaches("ota", Double.POSITIVE_INFINITY)).isFalse();
            assertThat(policy.decide(null).breached()).isFalse();
        }

        @Test
        @DisplayName("the decision is pure: repeated evaluation yields an identical verdict")
        void decisionIsDeterministic() {
            Finding f = finding("ota", 0.9246, 0.9300);

            PolicyDecision first = policy.decide(f);
            for (int i = 0; i < 100; i++) {
                assertThat(policy.decide(f)).isEqualTo(first);
            }
        }

        @Test
        @DisplayName("the SLA reference frame agrees with the policy verdict")
        void slaFrameAgreesWithDecision() {
            assertThat(policy.toSla("ota", 0.9246).breached()).isTrue();
            assertThat(policy.toSla("ota", 0.9246).target()).isEqualTo(OTA_TARGET);
            assertThat(policy.toSla("noshow_rate", 0.42).target()).isNull();
            assertThat(policy.toSla("ota", null).breached()).isFalse();
        }
    }
}
