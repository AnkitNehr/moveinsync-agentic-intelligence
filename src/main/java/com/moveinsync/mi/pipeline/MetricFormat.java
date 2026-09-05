package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import java.util.Locale;
import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * The single place a metric number is turned into text for a human.
 *
 * <p>Two different scales are in play across the platform and mixing them produces figures that are
 * wrong by a factor of a hundred:
 *
 * <ul>
 *   <li>{@code Finding.current}, {@code Finding.prior}, {@code Sla.target} and every
 *       {@link com.moveinsync.mi.model.Contribution} effect are in the metric's <em>native</em>
 *       unit — a rate metric carries {@code 0.9246}, not {@code 92.46}.
 *   <li>{@code Finding.deltaPts} has already been scaled to points by the scanner, so a rate
 *       movement of {@code 0.0285} arrives here as {@code 2.85}.
 * </ul>
 *
 * <p>Centralising the conversion means the triage title, the narrative body, the chat answer and the
 * REST payloads cannot disagree about whether June's OTA was 92.46% or 0.92 — a discrepancy that
 * would look like a data bug to whoever noticed it, and would be a formatting bug.
 */
@Component
public class MetricFormat {

    private final MetricCatalog catalog;

    public MetricFormat(MetricCatalog catalog) {
        this.catalog = catalog;
    }

    /** Human-readable metric name, falling back to the id when the metric is not in the catalog. */
    public String label(String metricId) {
        return definition(metricId).map(MetricDefinition::label).orElse(metricId == null ? "metric" : metricId);
    }

    /** Whether the metric is a proportion, so its values render as percentages. */
    public boolean isRate(String metricId) {
        return definition(metricId).map(MetricDefinition::rateMetric).orElse(false);
    }

    /**
     * Formats a value in the metric's native unit.
     *
     * @param metricId metric the value belongs to
     * @param value    native-unit value; null renders as {@code n/a} rather than as zero
     * @return e.g. {@code 92.46%}, {@code 78.49}, {@code 12.0 min}
     */
    public String value(String metricId, Double value) {
        if (value == null || !Double.isFinite(value)) {
            return "n/a";
        }
        if (isRate(metricId)) {
            return "%.2f%%".formatted(value * 100.0);
        }
        String unit = definition(metricId).map(MetricDefinition::unit).orElse("");
        String number = String.format(Locale.ROOT, "%,.2f", value);
        return switch (unit) {
            case "minutes" -> number + " min";
            case "currency" -> number;
            default -> number;
        };
    }

    /**
     * Formats an already-scaled delta as carried on {@link com.moveinsync.mi.model.Finding#deltaPts()}.
     *
     * <p>No further scaling is applied: the scanner has done it. Multiplying again here is the exact
     * mistake this class exists to prevent.
     *
     * @param metricId metric the movement belongs to
     * @param deltaPts points for a rate metric, native units otherwise
     */
    public String delta(String metricId, double deltaPts) {
        if (!Double.isFinite(deltaPts)) {
            return "n/a";
        }
        return isRate(metricId)
                ? "%+.2f pts".formatted(deltaPts)
                : "%+,.2f".formatted(deltaPts);
    }

    /**
     * Formats a native-unit effect from a shift-share decomposition, converting rates to points so it
     * is directly comparable with {@link #delta(String, double)}.
     *
     * @param metricId metric the effect belongs to
     * @param effect   native-unit rate, mix or total effect
     */
    public String effect(String metricId, double effect) {
        if (!Double.isFinite(effect)) {
            return "n/a";
        }
        return isRate(metricId)
                ? "%+.2f pts".formatted(effect * 100.0)
                : "%+,.2f".formatted(effect);
    }

    /** Formats a 0.0-1.0 share as a percentage. */
    public String share(double share) {
        return Double.isFinite(share) ? "%.1f%%".formatted(share * 100.0) : "n/a";
    }

    /** Direction word for a movement, respecting nothing but the sign. */
    public String movement(double delta) {
        return delta < 0 ? "fell" : "rose";
    }

    private Optional<MetricDefinition> definition(String metricId) {
        return catalog.find(metricId);
    }
}
