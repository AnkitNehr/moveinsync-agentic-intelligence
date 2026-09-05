package com.moveinsync.mi.controller;

import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.ingest.DuckDbService;
import com.moveinsync.mi.ingest.IngestReport;
import com.moveinsync.mi.ingest.QualityFlagger;
import com.moveinsync.mi.llm.ModelClient;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.pipeline.CadenceScheduler;
import com.moveinsync.mi.pipeline.PortRegistry;
import com.moveinsync.mi.pipeline.SenseReasonActPipeline;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Is the platform actually loaded, and is a model in the loop?
 *
 * <p>Two questions a reviewer asks in the first thirty seconds, and both have to be answerable
 * without reading logs. The row counts prove the extracts parsed — all seven files, nothing silently
 * dropped, {@code rowsRead == rowsKept} because nulls in this dataset are facts rather than defects.
 * The {@code llmAvailable} flag and the per-stage tiers prove whether the narratives being shown were
 * written by a model or by the deterministic fallbacks, which is exactly the thing that would
 * otherwise be indistinguishable from the outside.
 *
 * <p>Degraded state is reported, never faked. If DuckDB has not finished loading, this endpoint says
 * so rather than reporting zeros that read like an empty but healthy dataset.
 */
@RestController
@RequestMapping("/api/health")
@CrossOrigin
public class HealthController {

    private final DuckDbService duckDb;
    private final QualityFlagger qualityFlagger;
    private final MetricCatalog catalog;
    private final IncidentStore incidents;
    private final PortRegistry ports;
    private final SenseReasonActPipeline pipeline;
    private final CadenceScheduler cadence;
    private final ObjectProvider<ModelClient> claudeProvider;

    public HealthController(
            DuckDbService duckDb,
            QualityFlagger qualityFlagger,
            MetricCatalog catalog,
            IncidentStore incidents,
            PortRegistry ports,
            SenseReasonActPipeline pipeline,
            CadenceScheduler cadence,
            ObjectProvider<ModelClient> claudeProvider) {
        this.duckDb = duckDb;
        this.qualityFlagger = qualityFlagger;
        this.catalog = catalog;
        this.incidents = incidents;
        this.ports = ports;
        this.pipeline = pipeline;
        this.cadence = cadence;
        this.claudeProvider = claudeProvider;
    }

    /**
     * The health document.
     *
     * @param status          {@code UP} when the fact store answered, {@code DEGRADED} otherwise
     * @param datasetReady    whether the DuckDB relations are queryable
     * @param rows            row count per published relation
     * @param rowsRead        rows parsed from the CSV extracts
     * @param rowsKept        rows published — equal to {@code rowsRead} by construction
     * @param droppedRows     rows lost in ingest; must be zero
     * @param coverage        fraction of trip rows usable for the core on-time metric
     * @param qualityFlags    named data-quality counters raised during ingest
     * @param caveats         warnings carried onto every downstream observation
     * @param metrics         catalog metric ids
     * @param llmAvailable    whether model calls will be attempted
     * @param llmReason       why the LLM layer is off, or null when it is on
     * @param stageTiers      which implementation each agentic stage resolved to
     * @param nightlyEnabled  whether the scheduled sweep is armed
     * @param runInProgress   whether a pipeline run is executing right now
     * @param lastRunId       id of the most recent completed run, or null
     * @param openIncidents   incidents currently open or monitoring
     * @param totalIncidents  incidents in memory, including dismissed and resolved
     * @param checkedAt       ISO-8601 instant of this check
     */
    public record Health(
            String status,
            boolean datasetReady,
            Map<String, Long> rows,
            long rowsRead,
            long rowsKept,
            long droppedRows,
            double coverage,
            Map<String, Long> qualityFlags,
            List<String> caveats,
            List<String> metrics,
            boolean llmAvailable,
            String llmReason,
            Map<String, String> stageTiers,
            boolean nightlyEnabled,
            boolean runInProgress,
            String lastRunId,
            int openIncidents,
            int totalIncidents,
            String checkedAt) {
    }

    /** The full health check. Always 200: a degraded platform still has to be able to say so. */
    @GetMapping
    public Health health() {
        boolean ready = duckDb.isReady();
        Map<String, Long> rows = new LinkedHashMap<>();
        for (String relation : DuckDbService.RELATIONS) {
            rows.put(relation, ready ? safeCount(relation) : 0L);
        }

        IngestReport ingest = safeReport();
        ModelClient claude = claudeProvider.getIfAvailable();
        boolean llmAvailable = claude != null && claude.isAvailable();
        String llmReason = claude == null
                ? "No model provider is registered; every agentic stage runs deterministically."
                : claude.unavailableReason();

        return new Health(
                ready ? "UP" : "DEGRADED",
                ready,
                Map.copyOf(rows),
                ingest.rowsRead(),
                ingest.rowsKept(),
                ingest.dropped(),
                ingest.coverage(),
                ingest.flagCounts(),
                ingest.caveats(),
                catalog.ids(),
                llmAvailable,
                llmReason,
                ports.tiers(),
                cadence.isEnabled(),
                pipeline.running(),
                pipeline.latest().map(summary -> summary.runId()).orElse(null),
                incidents.openIncidents().size(),
                incidents.all().size(),
                Instant.now().toString());
    }

    private long safeCount(String relation) {
        try {
            return duckDb.count(relation);
        } catch (RuntimeException e) {
            // A relation that cannot be counted reports -1 rather than 0: an unknown count and an
            // empty table are different facts and must not render identically in a console.
            return -1L;
        }
    }

    private IngestReport safeReport() {
        try {
            IngestReport report = qualityFlagger.report();
            return report == null ? IngestReport.empty() : report;
        } catch (RuntimeException e) {
            return IngestReport.empty();
        }
    }
}
