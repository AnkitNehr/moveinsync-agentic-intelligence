package com.moveinsync.mi.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Tuning for the candidate ranker, bound from {@code app.ranking}.
 *
 * <p>Every value here ships with a working default, so the platform ranks sensibly with no
 * configuration at all and {@code application.yml} is only needed to override. Example:
 *
 * <pre>
 * app:
 *   ranking:
 *     confidence-saturation: 5000
 *     default-actionability: 0.5
 *     actionability:
 *       vendor_id: 1.0
 *       office: 1.0
 *       route_source: 1.0
 *       actual_cab_fuel_type: 0.3
 * </pre>
 */
@ConfigurationProperties(prefix = "app.ranking")
public class RankingProperties {

    /**
     * How actionable a movement on each dimension is, 0.0 to 1.0.
     *
     * <p>This is the term that stops the platform becoming an alert firehose, and it encodes a
     * judgement the statistics cannot make: whether anyone can actually do something about the
     * movement. A vendor or an office has an owner and a lever — a contract conversation, a routing
     * change — so it scores 1.0. {@code route_source} scores 1.0 because MANUAL versus AUTO planning
     * is directly controllable, which matters on this data since manually planned routes carry the
     * bulk of the June decline. Fuel type scores low: knowing that diesel cabs underperform is
     * interesting but there is no lever short of fleet replacement, so it should not outrank an
     * actionable finding of similar magnitude. Demographic dimensions score lowest — acting on them
     * would be inappropriate regardless of signal strength.
     *
     * <p>Keys are matched loosely, so {@code route_source}, {@code route-source} and
     * {@code routeSource} all resolve to the same entry.
     */
    private Map<String, Double> actionability = defaultActionabilityMap();

    /** Weight for a dimension with no configured entry: assumed moderately actionable. */
    private double defaultActionability = 0.5;

    /**
     * Sample size at which confidence reaches 1.0. Confidence grows with the logarithm of sample
     * size, so the curve is steep where it matters — the difference between 50 and 500 trips is large
     * — and flat where it does not, since 50,000 trips are not meaningfully more trustworthy than
     * 5,000.
     */
    private long confidenceSaturation = 5000L;

    /**
     * Confidence retained by an observation with zero coverage. Coverage scales confidence between
     * this floor and 1.0, so a metric computed on partial data is discounted without being discarded
     * — nulls in this dataset are meaningful, not defects.
     */
    private double coverageFloor = 0.6;

    /** Persistence weight for a movement seen in a single period. */
    private double persistenceBase = 0.7;

    /** Additional persistence per consecutive repeat, capped at 1.0. A recurring problem outranks a blip. */
    private double persistenceStep = 0.15;

    /** Findings carried into the agentic layer. Only these reach an LLM, which is the cost lever. */
    private int topN = 20;

    private static Map<String, Double> defaultActionabilityMap() {
        Map<String, Double> defaults = new LinkedHashMap<>();
        defaults.put("vendor_id", 1.0);
        defaults.put("office", 1.0);
        defaults.put("route_source", 1.0);
        defaults.put("product_type", 1.0);
        defaults.put("business_unit", 0.9);
        defaults.put("contract", 0.85);
        defaults.put("shift_type", 0.8);
        defaults.put("trip_direction", 0.8);
        defaults.put("delay_reason", 0.7);
        defaults.put("trip_nodal", 0.6);
        defaults.put("slab_name", 0.5);
        defaults.put("global", 0.5);
        defaults.put("actual_cab_fuel_type", 0.3);
        defaults.put("gender", 0.05);
        return defaults;
    }

    /**
     * Actionability weight for a dimension, matched ignoring case and separator style.
     *
     * @param dimension dimension name
     * @return the configured weight, or {@link #getDefaultActionability()} when unmapped
     */
    public double actionabilityFor(String dimension) {
        if (dimension == null || dimension.isBlank()) {
            return defaultActionability;
        }
        String target = normalise(dimension);
        for (Map.Entry<String, Double> entry : actionability.entrySet()) {
            if (normalise(entry.getKey()).equals(target)) {
                Double weight = entry.getValue();
                if (weight != null && Double.isFinite(weight)) {
                    return Math.clamp(weight, 0.0, 1.0);
                }
            }
        }
        return defaultActionability;
    }

    private static String normalise(String value) {
        return value.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "");
    }

    public Map<String, Double> getActionability() {
        return actionability;
    }

    public void setActionability(Map<String, Double> actionability) {
        // Merge rather than replace, so overriding one dimension in YAML does not silently discard
        // the defaults for every other dimension.
        Map<String, Double> merged = defaultActionabilityMap();
        if (actionability != null) {
            merged.putAll(actionability);
        }
        this.actionability = merged;
    }

    public double getDefaultActionability() {
        return defaultActionability;
    }

    public void setDefaultActionability(double defaultActionability) {
        this.defaultActionability = defaultActionability;
    }

    public long getConfidenceSaturation() {
        return confidenceSaturation;
    }

    public void setConfidenceSaturation(long confidenceSaturation) {
        this.confidenceSaturation = Math.max(1L, confidenceSaturation);
    }

    public double getCoverageFloor() {
        return coverageFloor;
    }

    public void setCoverageFloor(double coverageFloor) {
        this.coverageFloor = Math.clamp(coverageFloor, 0.0, 1.0);
    }

    public double getPersistenceBase() {
        return persistenceBase;
    }

    public void setPersistenceBase(double persistenceBase) {
        this.persistenceBase = Math.clamp(persistenceBase, 0.0, 1.0);
    }

    public double getPersistenceStep() {
        return persistenceStep;
    }

    public void setPersistenceStep(double persistenceStep) {
        this.persistenceStep = Math.clamp(persistenceStep, 0.0, 1.0);
    }

    public int getTopN() {
        return topN;
    }

    public void setTopN(int topN) {
        this.topN = Math.max(1, topN);
    }
}
