package com.moveinsync.mi.glossary;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

/**
 * Turns catalog ids and extract column names into the words an operator already uses.
 *
 * <p>Incidents persist the ids the pipeline keys on. Display is a separate pass so a stored
 * {@code escort_compliance} title still reads as Night Escort Coverage, with the dictionary
 * meaning of {@code actual_escort} attached, without rewriting history.
 */
@Service
public class OperatorCopy {

    private final MetricCatalog catalog;
    private final ColumnDictionary columns;
    private final List<Replacement> replacements;

    public OperatorCopy(MetricCatalog catalog, ColumnDictionary columns) {
        this.catalog = catalog;
        this.columns = columns;
        this.replacements = buildReplacements(catalog, columns);
    }

    /** Human metric name from the catalog. */
    public String metricLabel(String metricId) {
        return catalog.find(metricId).map(MetricDefinition::label).orElse(metricId);
    }

    /** First-paragraph description from the catalog YAML. */
    public String metricDescription(String metricId) {
        return catalog.find(metricId).map(MetricDefinition::description).orElse(null);
    }

    public String grainLabel(String grain) {
        if (grain == null || grain.isBlank() || "global".equalsIgnoreCase(grain)) {
            return "fleet-wide";
        }
        return columns.label(grain, grain);
    }

    public String grainMeaning(String grain) {
        return columns.meaning(grain);
    }

    /**
     * Dictionary-backed sources for a metric: extract columns the formula, filter, or coverage
     * expression actually names. Grain keys in {@code requires_columns} stay out of the gloss.
     */
    public List<ColumnDictionary.Column> sources(String metricId) {
        MetricDefinition definition = catalog.find(metricId).orElse(null);
        if (definition == null) {
            return List.of();
        }
        String haystack = String.join(
                        " ",
                        nullToEmpty(definition.formula()),
                        nullToEmpty(definition.filter()),
                        nullToEmpty(definition.coverageExpr()))
                .toLowerCase();
        List<ColumnDictionary.Column> found = new ArrayList<>();
        for (String column : definition.requiresColumns()) {
            if (column == null || "month".equals(column) || "period".equals(column)) {
                continue;
            }
            if (!Pattern.compile("\\b" + Pattern.quote(column.toLowerCase()) + "\\b")
                    .matcher(haystack)
                    .find()) {
                continue;
            }
            columns.find(column).ifPresent(found::add);
        }
        return List.copyOf(found);
    }

    public Incident incident(Incident raw) {
        if (raw == null) {
            return null;
        }
        List<Evidence> evidence = raw.evidence().stream()
                .map(item -> new Evidence(rewrite(item.claim()), item.metricId(), item.entity()))
                .toList();
        return new Incident(
                raw.id(),
                rewrite(raw.title()),
                rewrite(raw.whyNow()),
                raw.priority(),
                raw.severity(),
                raw.findingIds(),
                rewrite(raw.explanation()),
                evidence,
                raw.recommendedActions(),
                raw.policy(),
                raw.quality(),
                raw.detectedAt(),
                raw.followUpAt(),
                raw.status());
    }

    public List<Incident> incidents(List<Incident> raw) {
        if (raw == null) {
            return List.of();
        }
        return raw.stream().map(this::incident).toList();
    }

    /**
     * Replaces catalog metric ids and dictionary column ids with operator words.
     * Incident ids use hyphens ({@code inc-escort-compliance-…}) and are left untouched.
     */
    public String rewrite(String text) {
        if (text == null || text.isBlank()) {
            return text;
        }
        String out = text;
        for (Replacement replacement : replacements) {
            out = replacement.pattern.matcher(out).replaceAll(replacement.quoted);
        }
        return out;
    }

    private static List<Replacement> buildReplacements(MetricCatalog catalog, ColumnDictionary columns) {
        Map<String, String> phrases = new LinkedHashMap<>();
        Map<String, String> hyphenatedMetrics = new LinkedHashMap<>();
        for (MetricDefinition definition : catalog.all()) {
            phrases.put(definition.id(), definition.label());
            String spaced = definition.id().replace('_', ' ');
            if (!spaced.equals(definition.id())) {
                phrases.putIfAbsent(spaced, definition.label());
            }
            String hyphenated = definition.id().replace('_', '-');
            if (!hyphenated.equals(definition.id())) {
                hyphenatedMetrics.put(hyphenated, definition.label());
            }
        }
        for (ColumnDictionary.Column column : columns.all()) {
            phrases.putIfAbsent(column.id(), column.label());
        }
        List<Replacement> built = new ArrayList<>();
        phrases.entrySet().stream()
                .filter(entry -> entry.getKey() != null && (entry.getKey().contains("_") || entry.getKey().contains(" ")))
                .sorted(Comparator.comparingInt((Map.Entry<String, String> e) -> e.getKey().length()).reversed())
                .forEach(entry -> built.add(new Replacement(
                        Pattern.compile("\\b" + Pattern.quote(entry.getKey()) + "\\b"),
                        Matcher.quoteReplacement(entry.getValue()))));
        hyphenatedMetrics.entrySet().stream()
                .sorted(Comparator.comparingInt((Map.Entry<String, String> e) -> e.getKey().length()).reversed())
                .forEach(entry -> built.add(new Replacement(
                        Pattern.compile("(?<!inc-)\\b" + Pattern.quote(entry.getKey()) + "\\b"),
                        Matcher.quoteReplacement(entry.getValue()))));
        return List.copyOf(built);
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private record Replacement(Pattern pattern, String quoted) {
    }
}
