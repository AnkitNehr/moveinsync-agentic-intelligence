package com.moveinsync.mi.policy;

import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Sla;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Deterministic SLA rule engine. Decides breach, severity band and breach depth for a {@link Finding}.
 *
 * <p>Escalation is a governance decision, so it is made by rules rather than by the language model.
 * This class is the single place where "is this actually a contract violation?" is answered, and it
 * is deliberately <strong>pure</strong>: given the same finding and the same prior breach depth it
 * always returns the same {@link PolicyDecision}. There is no randomness, no {@code Instant.now()},
 * no I/O and no LLM call anywhere in it — the only notion of time is the period label carried on the
 * finding. That is what makes the verdict reproducible in an audit six months later.
 *
 * <h2>Direction matters</h2>
 * A naive "value &lt; target means breach" check is wrong for half the catalog. On-time arrival is
 * {@link Direction#HIGHER_IS_BETTER} — 92.46% against a 0.95 target is a breach. Alert acknowledgement
 * minutes and cost per km are {@link Direction#LOWER_IS_BETTER} — 20 minutes against a 15 minute
 * target is a breach even though the number is larger. Every rule declares its direction and the
 * comparison is inverted accordingly.
 *
 * <h2>Severity bands are relative, not absolute</h2>
 * The gap between an OTA value and its target is measured in fractions of a percent; the gap between
 * a cost-per-km value and its target is measured in rupees. A single set of absolute thresholds
 * cannot serve both. The band is therefore computed from the <em>relative</em> gap
 * ({@code gap / |target|}), which is dimensionless and comparable across the whole catalog.
 *
 * <h2>Configuration</h2>
 * Targets are bound from the same {@code app.sla.*} keys that back the typed configuration
 * properties, injected here as plain values. The policy deliberately depends on four doubles rather
 * than on a configuration object: it keeps the rule engine unit-testable without a Spring context,
 * and it means a change to the shape of the properties class cannot silently change a governance
 * verdict. A properties-based {@code @Bean} factory can call the plain constructor directly.
 */
@Service
public class SlaPolicy {

    /** Whether a larger value is better or worse for a metric. */
    public enum Direction {
        /** Breached when the observed value falls below target (OTA, escort compliance). */
        HIGHER_IS_BETTER,
        /** Breached when the observed value rises above target (ack minutes, cost per km). */
        LOWER_IS_BETTER
    }

    /** Unit family of a metric, used to reconcile percent-scaled inputs against fractional targets. */
    public enum Unit {
        /** A 0.0-1.0 proportion. Values above 1.0 are interpreted as percentages and rescaled. */
        RATIO,
        /** A value in native units (minutes, currency per km). Never rescaled. */
        ABSOLUTE
    }

    /**
     * One SLA rule.
     *
     * @param ruleId    stable identifier quoted in the {@link PolicyDecision} and the audit log
     * @param metricId  canonical metric this rule governs
     * @param direction whether higher or lower values are better
     * @param unit      unit family, controlling percent reconciliation
     * @param target    configured threshold
     */
    public record SlaRule(String ruleId, String metricId, Direction direction, Unit unit, double target) {
    }

    // ---- severity bands -------------------------------------------------------------------------

    /** No breach: the value meets or beats its target. */
    public static final String BAND_NONE = "NONE";
    /** Breach smaller than {@link #MAJOR_THRESHOLD} of target. */
    public static final String BAND_MINOR = "MINOR";
    /** Breach at or beyond {@link #MAJOR_THRESHOLD} but below {@link #CRITICAL_THRESHOLD} of target. */
    public static final String BAND_MAJOR = "MAJOR";
    /** Breach at or beyond {@link #CRITICAL_THRESHOLD} of target. */
    public static final String BAND_CRITICAL = "CRITICAL";

    /**
     * Relative gap at which a breach stops being MINOR and becomes MAJOR.
     *
     * <p>Calibrated against the real series: June campus OTA of 92.46% against the 0.95 target is a
     * relative gap of 0.0267, which lands in MAJOR. July's 94.69% is a gap of 0.0033 and stays MINOR.
     * That is the intended discrimination — June is the month worth waking someone for.
     */
    public static final double MAJOR_THRESHOLD = 0.02;

    /** Relative gap at which a breach becomes CRITICAL. */
    public static final double CRITICAL_THRESHOLD = 0.05;

    /** Consecutive breach periods required before escalation is authorised. */
    public static final int ESCALATION_MIN_CONSECUTIVE_PERIODS = 2;

    /** Rule id reported when the metric has no configured SLA target. */
    public static final String RULE_NO_SLA = "SLA-NONE-000";

    /** Tolerance used when testing a ratio value for percent scaling. */
    private static final double RATIO_EPSILON = 1e-9;

    private final Map<String, SlaRule> rulesByMetric;

    /**
     * Spring constructor. Binds the same {@code app.sla.*} keys as the typed configuration
     * properties; defaults mirror {@code application.yml} so the policy is never silently unarmed.
     */
    public SlaPolicy(
            @Value("${app.sla.ota:0.95}") double otaTarget,
            @Value("${app.sla.escort-compliance:1.0}") double escortComplianceTarget,
            @Value("${app.sla.alert-ack-minutes:15}") double alertAckMinutesTarget,
            @Value("${app.sla.cost-per-km-distance-contracts:25.0}") double costPerKmTarget) {
        this.rulesByMetric = buildRules(otaTarget, escortComplianceTarget, alertAckMinutesTarget, costPerKmTarget);
    }

    /**
     * Builds the immutable rule registry.
     *
     * <p>Aliases are registered alongside canonical ids so the scanner can emit either
     * {@code ota} or {@code on_time_arrival} without the policy silently falling through to
     * "no SLA applies" — a failure mode that would quietly disarm the whole engine.
     */
    private static Map<String, SlaRule> buildRules(
            double ota, double escortCompliance, double alertAckMinutes, double costPerKm) {

        SlaRule otaRule = new SlaRule("SLA-OTA-001", "ota", Direction.HIGHER_IS_BETTER, Unit.RATIO, ota);
        SlaRule otdRule = new SlaRule("SLA-OTD-001", "otd", Direction.HIGHER_IS_BETTER, Unit.RATIO, ota);
        SlaRule escortRule = new SlaRule(
                "SLA-ESCORT-001", "escort_compliance", Direction.HIGHER_IS_BETTER, Unit.RATIO, escortCompliance);
        SlaRule ackRule = new SlaRule(
                "SLA-ACK-001", "alert_ack_minutes", Direction.LOWER_IS_BETTER, Unit.ABSOLUTE, alertAckMinutes);
        // Only meaningful for distance-based contracts. Roughly 42% of bill rows are fixed-rate with
        // total_trip_km = 0, where cost per km is undefined rather than infinite; callers must not
        // route those segments here.
        SlaRule costRule = new SlaRule(
                "SLA-CPK-001", "cost_per_km", Direction.LOWER_IS_BETTER, Unit.ABSOLUTE, costPerKm);

        Map<String, SlaRule> rules = new LinkedHashMap<>();
        register(rules, otaRule, "ota", "on_time_arrival", "on_time_arrival_rate", "ota_rate");
        register(rules, otdRule, "otd", "on_time_departure", "on_time_departure_rate");
        register(rules, escortRule, "escort_compliance", "escort", "night_escort_compliance", "escort_rate");
        register(rules, ackRule, "alert_ack_minutes", "ack_minutes", "alert_acknowledgement_minutes",
                "alert_ack_time", "acknowledgement_minutes");
        register(rules, costRule, "cost_per_km", "cost_per_kilometre", "cpk");
        return Map.copyOf(rules);
    }

    private static void register(Map<String, SlaRule> rules, SlaRule rule, String... aliases) {
        for (String alias : aliases) {
            rules.put(normalise(alias), rule);
        }
    }

    /**
     * Canonicalises a metric id: lower-cased, with any run of non-alphanumeric characters collapsed
     * to a single underscore. {@code "Cost / km"}, {@code "cost-per-km"} and {@code "COST_PER_KM"}
     * all resolve to the same rule.
     */
    private static String normalise(String metricId) {
        if (metricId == null) {
            return "";
        }
        return metricId.trim()
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "_")
                .replaceAll("^_|_$", "");
    }

    // ---- public API -----------------------------------------------------------------------------

    /** Returns the rule governing a metric, or empty when the metric has no configured SLA. */
    public Optional<SlaRule> ruleFor(String metricId) {
        return Optional.ofNullable(rulesByMetric.get(normalise(metricId)));
    }

    /**
     * Reconciles a raw metric value against its rule's unit.
     *
     * <p>The scanner reports campus OTA as {@code 95.31} while the SLA target is {@code 0.95}. Both
     * are correct in their own frame, and comparing them naively would report a spectacular pass on a
     * month that actually breached. Ratio metrics whose value exceeds 1.0 are therefore treated as
     * percentages and divided by 100. Absolute metrics are never rescaled.
     */
    public double normaliseValue(SlaRule rule, double value) {
        if (rule.unit() == Unit.RATIO && rule.target() <= 1.0 + RATIO_EPSILON && value > 1.0 + RATIO_EPSILON) {
            return value / 100.0;
        }
        return value;
    }

    /**
     * Signed distance past the target, in the metric's native unit. Positive means breached,
     * negative means comfortably inside target, regardless of direction.
     */
    public double gap(SlaRule rule, double value) {
        double observed = normaliseValue(rule, value);
        return rule.direction() == Direction.HIGHER_IS_BETTER
                ? rule.target() - observed
                : observed - rule.target();
    }

    /**
     * {@link #gap} expressed as a fraction of the target, so bands are comparable across units.
     * Falls back to the absolute gap when the target is zero.
     */
    public double relativeGap(SlaRule rule, double value) {
        double raw = gap(rule, value);
        double magnitude = Math.abs(rule.target());
        return magnitude < RATIO_EPSILON ? raw : raw / magnitude;
    }

    /**
     * Whether the value violates the metric's SLA. Metrics with no configured target, and values
     * that are null or non-finite, are never breached — an unmeasurable metric is not a violation.
     */
    public boolean breaches(String metricId, Double value) {
        Optional<SlaRule> rule = ruleFor(metricId);
        if (rule.isEmpty() || !isUsable(value)) {
            return false;
        }
        return gap(rule.get(), value) > 0.0;
    }

    /** Severity band for a value, or {@link #BAND_NONE} when it is not breached or not measurable. */
    public String band(String metricId, Double value) {
        Optional<SlaRule> rule = ruleFor(metricId);
        if (rule.isEmpty() || !isUsable(value)) {
            return BAND_NONE;
        }
        return bandFor(relativeGap(rule.get(), value));
    }

    /** Maps a relative gap onto a severity band. Boundaries are inclusive at the lower edge. */
    public static String bandFor(double relativeGap) {
        if (relativeGap <= 0.0) {
            return BAND_NONE;
        }
        if (relativeGap < MAJOR_THRESHOLD) {
            return BAND_MINOR;
        }
        if (relativeGap < CRITICAL_THRESHOLD) {
            return BAND_MAJOR;
        }
        return BAND_CRITICAL;
    }

    /**
     * Builds the SLA reference frame for a metric observation, so the scanner and the policy engine
     * cannot disagree about whether a number breached.
     */
    public Sla toSla(String metricId, Double value) {
        Optional<SlaRule> maybeRule = ruleFor(metricId);
        if (maybeRule.isEmpty()) {
            return Sla.notApplicable();
        }
        SlaRule rule = maybeRule.get();
        if (!isUsable(value)) {
            return new Sla(rule.target(), null, false);
        }
        double signedGap = gap(rule, value);
        return new Sla(rule.target(), signedGap, signedGap > 0.0);
    }

    /**
     * Evaluates a finding, inferring breach depth from the finding's own prior-period value.
     *
     * <p>A finding carries both the current and the prior value, so a two-period streak can be
     * established without consulting incident memory. Deeper streaks require the caller to supply
     * the count from persisted history via {@link #decide(Finding, int)}.
     */
    public PolicyDecision decide(Finding finding) {
        if (finding == null) {
            return new PolicyDecision(RULE_NO_SLA, false, 0, false, BAND_NONE);
        }
        int priorStreak = breaches(finding.metricId(), finding.prior()) ? 1 : 0;
        return decide(finding, priorStreak);
    }

    /**
     * Evaluates a finding against its SLA rule.
     *
     * <p>Pure and total: no clock, no randomness, no I/O. The same finding and the same prior streak
     * always yield the same decision.
     *
     * @param finding                the movement under assessment
     * @param priorConsecutivePeriods breach depth as of the previous period, from incident memory;
     *                                negative values are clamped to zero
     * @return the governance verdict; never null
     */
    public PolicyDecision decide(Finding finding, int priorConsecutivePeriods) {
        if (finding == null) {
            return new PolicyDecision(RULE_NO_SLA, false, 0, false, BAND_NONE);
        }

        Optional<SlaRule> maybeRule = ruleFor(finding.metricId());
        if (maybeRule.isEmpty()) {
            // No contractual target for this metric. The movement may still be interesting enough to
            // become an incident on trend or peer grounds, but it is not an SLA violation and must
            // never be described as one.
            return new PolicyDecision(RULE_NO_SLA, false, 0, false, BAND_NONE);
        }

        SlaRule rule = maybeRule.get();
        double current = finding.current();
        if (!isUsable(current)) {
            return new PolicyDecision(rule.ruleId(), false, 0, false, BAND_NONE);
        }

        double relativeGap = relativeGap(rule, current);
        boolean breached = relativeGap > 0.0;

        // A streak only continues while the breach continues; a recovered period resets it to zero.
        int consecutivePeriods = breached ? Math.max(0, priorConsecutivePeriods) + 1 : 0;
        boolean escalationPermitted = breached && consecutivePeriods >= ESCALATION_MIN_CONSECUTIVE_PERIODS;

        return new PolicyDecision(
                rule.ruleId(), breached, consecutivePeriods, escalationPermitted, bandFor(relativeGap));
    }

    private static boolean isUsable(Double value) {
        return value != null && !value.isNaN() && !value.isInfinite();
    }
}
