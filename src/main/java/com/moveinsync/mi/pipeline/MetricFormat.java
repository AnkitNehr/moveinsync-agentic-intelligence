package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.glossary.ColumnDictionary;
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
    private final ColumnDictionary columns;

    public MetricFormat(MetricCatalog catalog, ColumnDictionary columns) {
        this.catalog = catalog;
        this.columns = columns;
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
        // Units, not bare numbers. "+51.50" on a delay metric says nothing — minutes, seconds,
        // trips? The catalog already declares the unit; the writer just has to use it.
        return switch (unitOf(metricId)) {
            case "rate" -> "%+.2f pts".formatted(deltaPts);
            case "minutes" -> "%+,.2f min".formatted(deltaPts);
            case "currency" -> "%+,.2f".formatted(deltaPts);
            default -> "%+,.2f".formatted(deltaPts);
        };
    }

    /** The catalog's declared unit for a metric, defaulting to {@code rate} as MetricDefinition does. */
    private String unitOf(String metricId) {
        return catalog.find(metricId).map(d -> d.unit()).orElse("rate");
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

    /**
     * An entity named the way a person would say it: "the 08:00 shift", "the vanta-Aus business unit".
     *
     * <p>Titles were built as {@code "on %s = %s"} and rendered {@code on shift_type = 08:00} — a
     * column name and an equals sign on the first line of every screen, in the product's most-read
     * string. It leaks into the incident list, the brief, the chat advice answer and every LLM
     * payload that quotes a title, so it is fixed once here rather than per writer. Grain nouns
     * come from the data dictionary glossary, not a second private map.
     */
    public String entityPhrase(String dimension, String entity) {
        if (entity == null || entity.isBlank()) {
            return "the fleet overall";
        }
        if (dimension == null || dimension.isBlank() || "global".equalsIgnoreCase(dimension)) {
            return "the fleet overall";
        }
        String noun = columns.label(dimension, dimension);
        // Entities sometimes already carry their category — shift_type has a value literally named
        // "Non Shift", and appending the noun produced "the Non Shift shift". When the name already
        // says what it is, the noun is redundant rather than clarifying.
        if (entity.toLowerCase(java.util.Locale.ROOT).contains(noun.toLowerCase(java.util.Locale.ROOT))) {
            return "the " + entity;
        }
        return "the %s %s".formatted(entity, noun);
    }

    /**
     * A guard action as an instruction someone can carry out, with its target folded in.
     *
     * <p>{@code notify} and {@code vendor_escalation} are internal constants. Printed raw they put
     * snake_case in front of a manager and, worse, say nothing useful: "notify" does not name who.
     */
    public String actionPhrase(String type, String target) {
        String who = target == null || target.isBlank() ? "" : " " + target;
        if (type == null) {
            return "act";
        }
        return switch (type) {
            case "notify" -> "tell the team that owns" + (who.isEmpty() ? " it" : who);
            case "vendor_escalation" -> "raise a formal escalation with the vendor behind" + who;
            case "review_allocation" -> "review how volume is allocated across" + who;
            case "auto_reallocate" -> "automatically move volume away from" + who;
            default -> type.replace('_', ' ') + who;
        };
    }

    /**
     * An instant as a date a person reads: "12 September 2026".
     *
     * <p>Briefs were carrying {@code 2026-09-12T08:07:39.899654Z} — microsecond precision, in a
     * document whose stated bar is that a facilities head can forward it without editing.
     */
    public String humanDate(String isoInstant) {
        if (isoInstant == null || isoInstant.isBlank()) {
            return "";
        }
        try {
            return java.time.format.DateTimeFormatter
                    .ofPattern("d MMMM yyyy", java.util.Locale.ENGLISH)
                    .withZone(java.time.ZoneOffset.UTC)
                    .format(java.time.Instant.parse(isoInstant));
        } catch (RuntimeException e) {
            return isoInstant;  // an unparseable stamp is still better than an empty line
        }
    }

    /** Direction word for a movement, respecting nothing but the sign. */
    public String movement(double delta) {
        return delta < 0 ? "fell" : "rose";
    }

    private Optional<MetricDefinition> definition(String metricId) {
        return catalog.find(metricId);
    }
}
