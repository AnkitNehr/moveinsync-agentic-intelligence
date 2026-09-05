package com.moveinsync.mi.controller;

import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.RunSummary;
import com.moveinsync.mi.pipeline.PortRegistry;
import com.moveinsync.mi.pipeline.SenseReasonActPipeline;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The demo button: one POST triggers a complete sense → reason → act pass and returns the receipt.
 *
 * <p>The endpoint is synchronous on purpose. A reviewer pressing "Run analysis" wants the run summary
 * in the response, not a job id to poll — and the run is seconds, not minutes, because every
 * expensive stage is deterministic SQL over an in-process DuckDB and only a handful of already-scored
 * findings ever reach a model. If it were slow enough to need a queue, that would be a signal the
 * funnel had stopped working.
 *
 * <p>Concurrent runs return 409 rather than queueing. Two runs share one token ledger, so a second
 * concurrent run would corrupt the accounting on both.
 */
@RestController
@RequestMapping("/api/runs")
@CrossOrigin
public class RunController {

    private static final Logger log = LoggerFactory.getLogger(RunController.class);

    private final SenseReasonActPipeline pipeline;
    private final PortRegistry ports;

    public RunController(SenseReasonActPipeline pipeline, PortRegistry ports) {
        this.pipeline = pipeline;
        this.ports = ports;
    }

    /**
     * Request body for a run. Both fields are optional.
     *
     * @param period      period to analyse, {@code yyyy-MM}; null means the latest period with data
     * @param priorPeriod comparison period; null means the month before {@code period}
     */
    public record RunRequest(String period, String priorPeriod) {
    }

    /**
     * Executes one pass.
     *
     * <p>Returns 200 with the summary, 400 on a malformed period, 409 while another run is executing,
     * and 503 when the fact store has no data to run against.
     */
    @PostMapping
    public ResponseEntity<RunSummary> run(@RequestBody(required = false) RunRequest request) {
        String period = request == null ? null : request.period();
        String priorPeriod = request == null ? null : request.priorPeriod();
        log.info("Run requested via API: period={} prior={}", period, priorPeriod);
        return ResponseEntity.ok(pipeline.run(period, priorPeriod));
    }

    /**
     * The most recent run, its incidents and which tier each agentic stage ran on.
     *
     * @return 200 with the summary, or 404 when the platform has not run since boot — an empty
     *         summary would be indistinguishable from a run that found nothing
     */
    @GetMapping("/latest")
    public LatestRun latest() {
        RunSummary summary = pipeline.latest()
                .orElseThrow(() -> new NotFoundException(
                        "No run has completed since startup. POST /api/runs to execute one."));
        return new LatestRun(summary, pipeline.latestIncidents(), ports.tiers(), pipeline.running());
    }

    /**
     * The latest run and everything a console needs to render it.
     *
     * @param summary   the run receipt: counts, tokens, cost, per-stage timings
     * @param incidents incidents this run opened, in triage priority order
     * @param tiers     which implementation each agentic stage resolved to
     * @param running   whether a further run is executing right now
     */
    public record LatestRun(
            RunSummary summary, List<Incident> incidents, Map<String, String> tiers, boolean running) {
    }
}
