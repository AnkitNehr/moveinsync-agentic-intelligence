package com.moveinsync.mi.controller;

import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.policy.SlaPolicy;
import java.util.List;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The metric layer, exposed. Every number the console shows comes from here.
 *
 * <p>There is deliberately no endpoint that accepts SQL, a filter or a formula. The only things this
 * API takes are a catalog metric id, one of that metric's declared grains, an entity value and a
 * period label — which is what makes "the dashboard, the chat answer and the nightly brief cannot
 * disagree" a structural property rather than a convention. Entity values and periods are bound as
 * JDBC parameters by the metric layer; identifiers are validated against the catalog before a query
 * is ever compiled.
 *
 * <p>Every observation carries all four reference frames, always. A frame with nothing to say reports
 * itself unavailable rather than being omitted from the JSON — "compared and fine" and "could not
 * compare" are different facts, and a missing key destroys the distinction.
 */
@RestController
@RequestMapping("/api/metrics")
@CrossOrigin
public class MetricController {

    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final BenchmarkService benchmarks;
    private final SlaPolicy slaPolicy;
    private final Environment environment;

    public MetricController(
            MetricCatalog catalog,
            MetricQueryService metrics,
            BenchmarkService benchmarks,
            SlaPolicy slaPolicy,
            Environment environment) {
        this.catalog = catalog;
        this.metrics = metrics;
        this.benchmarks = benchmarks;
        this.slaPolicy = slaPolicy;
        this.environment = environment;
    }

    /**
     * One catalog entry, as the console and the agent tool surface see it.
     *
     * @param id           stable metric identifier
     * @param label        human-readable name
     * @param description  what the metric means and how to read it
     * @param version      catalog version; bumped whenever the definition changes
     * @param unit         {@code rate}, {@code minutes} or {@code currency}
     * @param rateMetric   whether values are proportions, so deltas are points
     * @param direction    which way is better
     * @param sourceView   the relation the metric is computed over
     * @param grains       dimensions it may be sliced by, including {@code global}
     * @param minSample    the volume gate: the smallest slice it will report a number on
     * @param slaTarget    contractual target, or null when the metric has none
     * @param industryBenchmark configured external benchmark, or null
     * @param segmentBy    column that decides whether the metric is defined at all, or null
     * @param validSegments values of {@code segmentBy} where it is defined
     * @param periods      period labels the fact store currently holds for it
     * @param caveats      standing data-quality warnings carried into every observation
     */
    public record MetricSummary(
            String id,
            String label,
            String description,
            int version,
            String unit,
            boolean rateMetric,
            String direction,
            String sourceView,
            List<String> grains,
            long minSample,
            Double slaTarget,
            Double industryBenchmark,
            String segmentBy,
            List<String> validSegments,
            List<String> periods,
            List<String> caveats) {
    }

    /** The full catalog. This is the entire vocabulary the platform can answer questions in. */
    @GetMapping
    public List<MetricSummary> catalog() {
        return catalog.all().stream().map(this::summarise).toList();
    }

    /**
     * One fully contextualised observation.
     *
     * @param metricId  catalog metric id
     * @param dimension logical grain; defaults to {@code global}
     * @param entity    dimension member; defaults to {@code ALL}
     * @param period    {@code yyyy-MM}; defaults to the latest period the metric has data for
     * @return the observation, including trend, SLA, peer and industry frames
     */
    @GetMapping("/{metricId}")
    public MetricObservation observe(
            @PathVariable String metricId,
            @RequestParam(required = false) String dimension,
            @RequestParam(required = false) String entity,
            @RequestParam(required = false) String period) {

        MetricDefinition definition = require(metricId);
        String grain = resolveGrain(definition, dimension);
        String member = (entity == null || entity.isBlank()) ? MetricSpec.ALL : entity.trim();
        String resolvedPeriod = resolvePeriod(definition, period);

        return benchmarks.observe(definition.id(), grain, member, resolvedPeriod);
    }

    /**
     * Every entity on one dimension, each fully contextualised — the vendor or office scorecard.
     *
     * <p>Entities suppressed by the volume gate are included with a null value and their true row
     * count. Dropping them would leave a scorecard that silently omits the segments most likely to be
     * asked about.
     */
    @GetMapping("/{metricId}/series")
    public List<MetricObservation> series(
            @PathVariable String metricId,
            @RequestParam(required = false, defaultValue = MetricSpec.GLOBAL) String dimension,
            @RequestParam(required = false) String period) {

        MetricDefinition definition = require(metricId);
        String grain = resolveGrain(definition, dimension);
        return benchmarks.observeAll(definition.id(), grain, resolvePeriod(definition, period));
    }

    /** Period labels the fact store holds for a metric, oldest first. */
    @GetMapping("/{metricId}/periods")
    public Map<String, Object> periods(@PathVariable String metricId) {
        MetricDefinition definition = require(metricId);
        List<String> periods = metrics.periods(definition.id());
        return Map.of("metricId", definition.id(), "periods", periods);
    }

    // ---- resolution -------------------------------------------------------------------------------

    private MetricDefinition require(String metricId) {
        return catalog.find(metricId)
                .orElseThrow(() -> NotFoundException.of("metric", metricId, catalog.ids()));
    }

    /**
     * Validates the requested grain against the catalog.
     *
     * <p>A grain the metric does not declare is a 400 listing what it does declare, not a silent
     * fallback to global — an empty chart is a much worse answer than an error that says why.
     */
    private String resolveGrain(MetricDefinition definition, String dimension) {
        if (dimension == null || dimension.isBlank() || MetricDefinition.isGlobal(dimension)) {
            return MetricSpec.GLOBAL;
        }
        String grain = dimension.trim();
        if (!definition.supports(grain)) {
            throw new IllegalArgumentException(
                    "Metric '" + definition.id() + "' cannot be sliced by '" + grain
                            + "'. Declared grains: " + definition.grains());
        }
        return grain;
    }

    private String resolvePeriod(MetricDefinition definition, String period) {
        if (period != null && !period.isBlank()) {
            String canonical = MetricQueryService.canonicalPeriod(period);
            if (canonical == null) {
                throw new IllegalArgumentException(
                        "Malformed period '" + period + "'; expected a yyyy-MM label such as 2026-06.");
            }
            return canonical;
        }
        return metrics.latestPeriod(definition.id())
                .orElseThrow(() -> new NotFoundException(
                        "The fact store holds no periods for metric '" + definition.id()
                                + "'. Ingest may not have completed."));
    }

    private MetricSummary summarise(MetricDefinition definition) {
        Double slaTarget = slaPolicy.ruleFor(definition.id())
                .map(SlaPolicy.SlaRule::target)
                .orElse(null);
        Double industry = definition.industryPropertyKey() == null
                ? null
                : environment.getProperty(definition.industryPropertyKey(), Double.class);

        return new MetricSummary(
                definition.id(),
                definition.label(),
                definition.description(),
                definition.version(),
                definition.unit(),
                definition.rateMetric(),
                definition.direction(),
                definition.sourceView(),
                definition.grains(),
                definition.minSample(),
                slaTarget,
                industry,
                definition.segmentBy(),
                definition.validSegments(),
                metrics.periods(definition.id()),
                definition.caveats());
    }
}
