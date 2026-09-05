package com.moveinsync.mi.controller;

import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.glossary.OperatorCopy;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.PortRegistry;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The period brief: every open incident and the headline metrics, written for one reader.
 *
 * <p>Persona is a query parameter, not a separate report. A transport manager wants the vendor and
 * the operating lever; a facilities head wants the site and its cost exposure; a line manager wants
 * the trips their own people were on; an executive wants the risk and whether it is worsening. Same
 * numbers, four framings — and because the underlying figures are computed once by the metric layer
 * and merely rendered differently, two personas' briefs can be diffed and will disagree only in
 * emphasis. Four separately written reports would drift within a quarter.
 */
@RestController
@RequestMapping("/api/reports")
@CrossOrigin
public class ReportController {

    private static final Logger log = LoggerFactory.getLogger(ReportController.class);

    private final PortRegistry ports;
    private final IncidentStore incidents;
    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final BenchmarkService benchmarks;
    private final MetricFormat format;
    private final OperatorCopy copy;

    public ReportController(
            PortRegistry ports,
            IncidentStore incidents,
            MetricCatalog catalog,
            MetricQueryService metrics,
            BenchmarkService benchmarks,
            MetricFormat format,
            OperatorCopy copy) {
        this.ports = ports;
        this.incidents = incidents;
        this.catalog = catalog;
        this.metrics = metrics;
        this.benchmarks = benchmarks;
        this.format = format;
        this.copy = copy;
    }

    /**
     * A rendered brief.
     *
     * @param period      period covered
     * @param persona     reader it was written for, after canonicalisation
     * @param markdown    the brief itself
     * @param headline    the headline metric lines the brief was built from
     * @param incidentIds incidents it covers, most urgent first
     * @param tier        which implementation rendered it — a model id, or {@code deterministic}
     * @param generatedAt ISO-8601 instant of rendering
     */
    public record Brief(
            String period,
            String persona,
            String markdown,
            List<String> headline,
            List<String> incidentIds,
            String tier,
            String generatedAt) {
    }

    /**
     * Renders the brief.
     *
     * @param period  {@code yyyy-MM}; defaults to the latest period with data
     * @param persona one of {@link NarrativePort#PERSONAS}; anything else falls back to the transport
     *                manager, as the port contract requires
     * @param format  {@code json} (default) or {@code markdown} for the raw document
     */
    @GetMapping("/brief")
    public ResponseEntity<?> brief(
            @RequestParam(required = false) String period,
            @RequestParam(required = false, defaultValue = NarrativePort.TRANSPORT_MANAGER) String persona,
            @RequestParam(name = "format", required = false, defaultValue = "json") String responseFormat) {

        String resolvedPeriod = resolvePeriod(period);
        String reader = canonicalPersona(persona);
        // Triage priority, not detection order. A brief is read top-down and stops being read
        // somewhere in the middle, so the most urgent incident has to be first.
        List<Incident> open = copy.incidents(incidents.openIncidents()).stream()
                .sorted(Comparator.comparingInt(Incident::priority)
                        .thenComparing(Incident::id))
                .toList();
        List<String> headline = headlineMetrics(resolvedPeriod);

        String markdown = ports.narrative().brief(resolvedPeriod, reader, open, headline);
        log.info("Brief rendered for {} on {} ({} incidents, tier {})",
                reader, resolvedPeriod, open.size(), ports.narrative().tier());

        if ("markdown".equalsIgnoreCase(responseFormat) || "md".equalsIgnoreCase(responseFormat)) {
            return ResponseEntity.ok()
                    .contentType(MediaType.valueOf("text/markdown;charset=UTF-8"))
                    .body(markdown);
        }
        return ResponseEntity.ok(new Brief(
                resolvedPeriod,
                reader,
                markdown,
                headline,
                open.stream().map(Incident::id).toList(),
                ports.narrative().tier(),
                Instant.now().toString()));
    }

    /** The personas the platform renders for, in presentation order. */
    @GetMapping("/personas")
    public List<String> personas() {
        return NarrativePort.PERSONAS;
    }

    /**
     * Builds the headline block: every catalog metric's aggregate for the period, with its movement
     * and its SLA verdict where one applies.
     *
     * <p>A metric that could not be measured is listed as unmeasured rather than omitted. Silently
     * dropping it would let a segment that fell below its volume gate read as though it had been fine.
     */
    private List<String> headlineMetrics(String period) {
        List<String> lines = new ArrayList<>();
        for (MetricDefinition definition : catalog.all()) {
            MetricObservation observation;
            try {
                observation = benchmarks.observe(
                        definition.id(), MetricSpec.GLOBAL, MetricSpec.ALL, period);
            } catch (RuntimeException e) {
                log.debug("Headline skipped for {}: {}", definition.id(), e.toString());
                continue;
            }
            if (observation.value() == null) {
                lines.add("**%s**: not measurable in %s (%,d rows, below the reporting gate — not a zero)"
                        .formatted(definition.label(), period, observation.sampleSize()));
                continue;
            }

            StringBuilder line = new StringBuilder();
            line.append("**").append(definition.label()).append("**: ")
                    .append(format.value(definition.id(), observation.value()))
                    .append(String.format(Locale.ROOT, " over %,d rows", observation.sampleSize()));

            Trend trend = observation.references() == null ? null : observation.references().trend();
            if (trend != null && trend.delta() != null) {
                line.append(", ").append(format.effect(definition.id(), trend.delta()))
                        .append(" vs ").append(MetricQueryService.previousPeriod(period));
            }
            Sla sla = observation.references() == null ? null : observation.references().sla();
            if (sla != null && sla.target() != null) {
                line.append(sla.breached() ? " — **breaching** target " : " — clears target ")
                        .append(format.value(definition.id(), sla.target()));
            }
            lines.add(line.toString());
        }
        return List.copyOf(lines);
    }

    private String resolvePeriod(String period) {
        if (period != null && !period.isBlank()) {
            String canonical = MetricQueryService.canonicalPeriod(period);
            if (canonical == null) {
                throw new IllegalArgumentException(
                        "Malformed period '" + period + "'; expected a yyyy-MM label such as 2026-06.");
            }
            return canonical;
        }
        for (MetricDefinition definition : catalog.all()) {
            var latest = metrics.latestPeriod(definition.id());
            if (latest.isPresent()) {
                return latest.get();
            }
        }
        throw new NotFoundException(
                "No period could be resolved: the fact store holds no rows for any catalog metric.");
    }

    private static String canonicalPersona(String persona) {
        if (persona == null || persona.isBlank()) {
            return NarrativePort.TRANSPORT_MANAGER;
        }
        String normalised = persona.trim().toLowerCase(Locale.ROOT).replace('-', '_');
        return NarrativePort.PERSONAS.contains(normalised)
                ? normalised
                : NarrativePort.TRANSPORT_MANAGER;
    }
}
