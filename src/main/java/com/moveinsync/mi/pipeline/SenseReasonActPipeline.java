package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.anomaly.AnomalyScanner;
import com.moveinsync.mi.anomaly.CandidateRanker;
import com.moveinsync.mi.anomaly.RankingContext;
import com.moveinsync.mi.attribution.AttributionResult;
import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.ingest.DuckDbService;
import com.moveinsync.mi.ingest.IngestReport;
import com.moveinsync.mi.ingest.QualityFlagger;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.llm.UsageRecorder;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.RunSummary;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import com.moveinsync.mi.pipeline.spi.ReasoningPort;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import com.moveinsync.mi.policy.ActionGuard;
import com.moveinsync.mi.policy.SlaPolicy;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * The orchestrator: one pass of sense → reason → act over a period pair.
 *
 * <h2>The shape of a run</h2>
 *
 * <pre>
 *   ingest quality  →  scan  →  rank  →  policy  →  triage  →  reason  →  narrate
 *                   →  action guard  →  open incident + schedule follow-up  →  audit
 * </pre>
 *
 * <p>The ordering encodes a design commitment rather than a convenience. Detection, prioritisation
 * and governance all run <em>before</em> any model is involved, and each one narrows the input to the
 * next: the scanner emits every statistically real movement, the ranker cuts that to a scored top-N,
 * the policy engine decides breach and escalation depth by rule. Only the survivors — a few kilobytes
 * of already-computed JSON — reach the agentic stages. That is simultaneously the cost control and
 * the safety property: a model that never sees a trip row cannot invent one, and a model that never
 * decides an escalation cannot authorise one.
 *
 * <h2>Running with the model switched off</h2>
 *
 * <p>Triage, reasoning and narration are ports, resolved once by {@link PortRegistry}. With no API
 * key present every one of them resolves to a deterministic implementation and the pipeline still
 * produces governed, evidenced, actionable incidents — the narrative is drier, and nothing else
 * changes. That is why the run summary reports zero tokens rather than an estimate when the LLM layer
 * is off: an honest zero is more useful than a plausible number.
 *
 * <h2>Accounting</h2>
 *
 * <p>Each stage is timed and its token consumption is isolated by snapshotting {@link UsageRecorder}
 * before and after it, so {@code stageTimings} and the per-stage audit records describe what actually
 * happened rather than what was expected to. A run is serialised on a lock: two concurrent runs would
 * interleave their token accounting through the single recorder and produce two summaries that are
 * both wrong.
 */
@Service
public class SenseReasonActPipeline {

    private static final Logger log = LoggerFactory.getLogger(SenseReasonActPipeline.class);

    /** Stage names, used for timings, audit records and token attribution. */
    public static final String STAGE_INGEST = "ingest";
    public static final String STAGE_SCAN = "scan";
    public static final String STAGE_RANK = "rank";
    public static final String STAGE_POLICY = "policy";
    public static final String STAGE_TRIAGE = "triage";
    public static final String STAGE_REASON = "reason";
    public static final String STAGE_NARRATE = "narrate";
    public static final String STAGE_GUARD = "actionGuard";
    public static final String STAGE_PERSIST = "persist";
    public static final String STAGE_AUDIT = "audit";

    /** Severity thresholds used only when no SLA governs the metric. */
    private static final double SEVERITY_MAJOR = 0.66;
    private static final double SEVERITY_MINOR = 0.33;

    /**
     * Weight applied to a series that already has an open incident.
     *
     * <p>Not 1.0. An open incident should stop the platform shouting the same story every run, but it
     * must not delete the series from the sweep entirely — a movement that keeps deepening while an
     * incident is open is exactly the thing the follow-up loop needs to see.
     */
    private static final double OPEN_INCIDENT_SUPPRESSION = 0.6;

    private final DuckDbService duckDb;
    private final QualityFlagger qualityFlagger;
    private final MetricCatalog catalog;
    private final MetricQueryService metrics;
    private final AnomalyScanner scanner;
    private final CandidateRanker ranker;
    private final AttributionService attribution;
    private final SlaPolicy slaPolicy;
    private final ActionGuard actionGuard;
    private final IncidentStore incidents;
    private final AuditLog auditLog;
    private final UsageRecorder usage;
    private final PortRegistry ports;

    private final int followUpDays;
    private final String defaultPersona;
    private final boolean countSeries;

    /** One run at a time: the token recorder is a single generation counter and cannot be shared. */
    private final ReentrantLock runLock = new ReentrantLock();

    private final AtomicReference<RunSummary> latestSummary = new AtomicReference<>();
    private final AtomicReference<List<Incident>> latestIncidents = new AtomicReference<>(List.of());

    public SenseReasonActPipeline(
            DuckDbService duckDb,
            QualityFlagger qualityFlagger,
            MetricCatalog catalog,
            MetricQueryService metrics,
            AnomalyScanner scanner,
            CandidateRanker ranker,
            AttributionService attribution,
            SlaPolicy slaPolicy,
            ActionGuard actionGuard,
            IncidentStore incidents,
            AuditLog auditLog,
            UsageRecorder usage,
            PortRegistry ports,
            @Value("${app.followup.days:7}") int followUpDays,
            @Value("${app.narrative.default-persona:transport_manager}") String defaultPersona,
            @Value("${app.pipeline.count-series:true}") boolean countSeries) {
        this.duckDb = duckDb;
        this.qualityFlagger = qualityFlagger;
        this.catalog = catalog;
        this.metrics = metrics;
        this.scanner = scanner;
        this.ranker = ranker;
        this.attribution = attribution;
        this.slaPolicy = slaPolicy;
        this.actionGuard = actionGuard;
        this.incidents = incidents;
        this.auditLog = auditLog;
        this.usage = usage;
        this.ports = ports;
        this.followUpDays = Math.max(1, followUpDays);
        this.defaultPersona = defaultPersona;
        this.countSeries = countSeries;
    }

    // ---- entry points -----------------------------------------------------------------------------

    /** Runs the latest period against the one before it. */
    public RunSummary run() {
        String period = defaultPeriod();
        return run(period, priorPeriodOf(period));
    }

    /**
     * Executes one end-to-end pass.
     *
     * @param period      current period label, {@code yyyy-MM}; null resolves to the latest period
     *                    the fact store holds
     * @param priorPeriod comparison period; null resolves to the month before {@code period}
     * @return the run summary, with real token counts and per-stage timings
     * @throws IllegalStateException when a run is already in progress, or when no period can be
     *                               resolved because the fact store is empty
     */
    public RunSummary run(String period, String priorPeriod) {
        if (!runLock.tryLock()) {
            throw new IllegalStateException(
                    "A pipeline run is already in progress. Runs are serialised because they share a "
                            + "single token ledger; retry when the current run completes.");
        }
        try {
            return execute(period, priorPeriod);
        } finally {
            runLock.unlock();
        }
    }

    /** The most recent run summary, or empty when the platform has not run since boot. */
    public Optional<RunSummary> latest() {
        return Optional.ofNullable(latestSummary.get());
    }

    /** Incidents opened or refreshed by the most recent run, most urgent first. */
    public List<Incident> latestIncidents() {
        return latestIncidents.get();
    }

    /** Whether a run is currently executing. */
    public boolean running() {
        return runLock.isLocked();
    }

    /**
     * The most recent period the fact store holds data for.
     *
     * <p>Resolved from the catalog rather than from a constant, so the platform follows the data
     * instead of needing a config change when a new monthly extract lands.
     */
    public String defaultPeriod() {
        for (MetricDefinition definition : catalog.all()) {
            Optional<String> latest = metrics.latestPeriod(definition.id());
            if (latest.isPresent()) {
                return latest.get();
            }
        }
        throw new IllegalStateException(
                "No period could be resolved: the fact store holds no rows for any catalog metric. "
                        + "Ingest has not completed, and an empty result is not a clean bill of health.");
    }

    /** The month before a period label. */
    public String priorPeriodOf(String period) {
        String prior = MetricQueryService.previousPeriod(period);
        if (prior == null) {
            throw new IllegalArgumentException(
                    "Malformed period '" + period + "'; expected a yyyy-MM label such as 2026-06.");
        }
        return prior;
    }

    // ---- the run ----------------------------------------------------------------------------------

    private RunSummary execute(String requestedPeriod, String requestedPrior) {
        Instant startedAt = Instant.now();
        String period = (requestedPeriod == null || requestedPeriod.isBlank())
                ? defaultPeriod()
                : requestedPeriod.trim();
        if (MetricQueryService.parsePeriod(period) == null) {
            throw new IllegalArgumentException(
                    "Malformed period '" + requestedPeriod + "'; expected a yyyy-MM label such as 2026-06.");
        }
        String priorPeriod = (requestedPrior == null || requestedPrior.isBlank())
                ? priorPeriodOf(period)
                : requestedPrior.trim();

        String runId = "run-" + startedAt.toString().replaceAll("[^0-9A-Za-z]", "") + "-" + period;
        usage.beginRun(runId);
        RunLedger ledger = new RunLedger();
        long wallStart = System.nanoTime();

        log.info("Run {} starting: {} vs {} (ports: {})", runId, period, priorPeriod, ports.tiers());

        // ---- 1. ingest quality ---------------------------------------------------------------------
        IngestReport ingest = ledger.time(STAGE_INGEST, this::ingestReport);
        long trips = ledger.time(STAGE_INGEST, this::tripCount);
        auditLog.recordDeterministic(runId, AuditLog.STAGE_INGEST, List.of(
                "trips=" + trips,
                "rowsRead=" + ingest.rowsRead(),
                "rowsKept=" + ingest.rowsKept(),
                "coverage=" + String.format(Locale.ROOT, "%.4f", ingest.coverage())));

        // ---- 2. scan -------------------------------------------------------------------------------
        List<Finding> raw = ledger.time(STAGE_SCAN, () -> scanner.scan(period, priorPeriod));
        int seriesEvaluated = ledger.time(STAGE_SCAN, () -> countSeries(period));
        auditLog.recordDeterministic(runId, AuditLog.STAGE_SCAN,
                raw.stream().map(Finding::id).toList());

        // ---- 3. rank -------------------------------------------------------------------------------
        RankingContext context = ledger.time(STAGE_RANK, () -> memoryContext(raw, period));
        List<Finding> ranked = ledger.time(STAGE_RANK, () -> ranker.rank(raw, context));
        Map<String, Finding> byId = new LinkedHashMap<>();
        ranked.forEach(finding -> byId.put(finding.id(), finding));

        // ---- 4. policy -----------------------------------------------------------------------------
        Map<String, PolicyDecision> decisions = ledger.time(STAGE_POLICY, () -> evaluatePolicy(ranked, context));
        auditLog.recordDeterministic(runId, AuditLog.STAGE_POLICY, decisions.entrySet().stream()
                .map(entry -> entry.getKey() + "=" + entry.getValue().ruleId()
                        + ":" + entry.getValue().severityBand()
                        + ":depth" + entry.getValue().consecutivePeriods())
                .toList());

        // ---- 5. triage -----------------------------------------------------------------------------
        List<TriagePort.IncidentDraft> drafts =
                ledger.time(STAGE_TRIAGE, () -> safeTriage(ranked, period));
        auditLog.record(runId, AuditLog.STAGE_TRIAGE,
                drafts.stream().map(TriagePort.IncidentDraft::clusterKey).toList(),
                List.of(), List.of(), List.of(),
                ports.triage().tier(),
                ledger.promptTokens(STAGE_TRIAGE), ledger.completionTokens(STAGE_TRIAGE));

        // ---- 6-9. reason, narrate, guard, persist --------------------------------------------------
        Map<String, AttributionResult> attributions = new HashMap<>();
        List<Incident> opened = new ArrayList<>(drafts.size());

        for (TriagePort.IncidentDraft draft : drafts) {
            List<Finding> members = draft.findingIds().stream()
                    .map(byId::get)
                    .filter(java.util.Objects::nonNull)
                    .toList();
            if (members.isEmpty()) {
                log.warn("Draft {} references no surviving finding; skipping", draft.clusterKey());
                continue;
            }
            Finding lead = members.getFirst();
            PolicyDecision decision = decisions.getOrDefault(lead.id(), slaPolicy.decide(lead));

            AttributionResult attributed = ledger.time(STAGE_REASON, () ->
                    attributions.computeIfAbsent(lead.metricId(),
                            metricId -> safeAttribute(metricId, period, priorPeriod)));

            ReasoningPort.Explanation explanation = ledger.time(STAGE_REASON, () ->
                    safeExplain(draft, members, attributed));

            Incident skeleton = draft(draft, lead, members, decision, explanation, period, startedAt);

            List<Action> actions = ledger.time(STAGE_GUARD, () ->
                    actionGuard.permittedActions(skeleton, decision));

            Incident governed = withActions(skeleton, actions);

            NarrativePort.Narrative narrative = ledger.time(STAGE_NARRATE, () ->
                    safeNarrate(governed, members, defaultPersona));

            Incident finished = preserveOperatorStatus(withNarrative(governed, narrative));

            ledger.time(STAGE_PERSIST, () -> {
                incidents.open(finished);
                incidents.scheduleFollowUp(finished.id(), followUpDays, startedAt);
                return null;
            });

            auditLog.record(runId, AuditLog.STAGE_NARRATE, List.of(finished.id()),
                    finished.evidence(), finished.recommendedActions(), List.of(),
                    ports.narrative().tier(),
                    0L, 0L);
            opened.add(finished);
        }

        // ---- 10. audit -----------------------------------------------------------------------------
        // Written before the summary is assembled so that the audit stage's own cost appears in the
        // timings the summary reports. Token totals are read from the recorder rather than from the
        // summary for the same reason: the summary does not exist yet.
        ledger.time(STAGE_AUDIT, () -> {
            UsageRecorder.Snapshot snapshot = usage.snapshot();
            auditLog.record(runId, AuditLog.STAGE_DELIVER,
                    opened.stream().map(Incident::id).toList(),
                    opened.stream().flatMap(incident -> incident.evidence().stream()).limit(32).toList(),
                    opened.stream().flatMap(incident -> incident.recommendedActions().stream()).toList(),
                    List.of("console", "api"),
                    ports.reasoning().tier(),
                    snapshot.promptTokens(),
                    snapshot.completionTokens());
            return null;
        });

        long wallClockMs = (System.nanoTime() - wallStart) / 1_000_000L;
        RunSummary summary = usage.fill(new RunSummary(
                runId,
                startedAt.toString(),
                trips,
                seriesEvaluated,
                ranked.size(),
                opened.size(),
                0L,
                0L,
                0.0,
                wallClockMs,
                ledger.timings()));

        latestSummary.set(summary);
        latestIncidents.set(List.copyOf(opened));

        log.info("Run {} complete in {} ms: {} trips, {} series, {} candidates, {} incidents, "
                        + "{} prompt / {} completion tokens (${})",
                runId, wallClockMs, trips, seriesEvaluated, ranked.size(), opened.size(),
                summary.promptTokens(), summary.completionTokens(),
                String.format(Locale.ROOT, "%.4f", summary.estimatedCostUsd()));
        return summary;
    }

    // ---- stages -----------------------------------------------------------------------------------

    private IngestReport ingestReport() {
        try {
            IngestReport report = qualityFlagger.report();
            return report == null ? IngestReport.empty() : report;
        } catch (RuntimeException e) {
            log.warn("Ingest quality report unavailable: {}", e.toString());
            return IngestReport.empty();
        }
    }

    private long tripCount() {
        try {
            return duckDb.isReady() ? duckDb.count("trips") : 0L;
        } catch (RuntimeException e) {
            log.warn("Trip count unavailable: {}", e.toString());
            return 0L;
        }
    }

    /**
     * Counts the entity series present in the current period across the whole catalog.
     *
     * <p>Reported rather than estimated, because "how much of the search space did you actually look
     * at" is the question that separates a generic scanner from one pointed at a handful of
     * pre-chosen segments. The scanner compares the intersection with the prior period, so this is the
     * current-period population it drew from; it is deliberately computed through the metric layer
     * rather than by reaching into the fact store.
     */
    private int countSeries(String period) {
        if (!countSeries) {
            return 0;
        }
        int total = 0;
        for (MetricSpec spec : catalog.specs()) {
            for (String grain : spec.grains()) {
                try {
                    total += metrics.slices(spec.id(), grain, period).size();
                } catch (RuntimeException e) {
                    log.debug("Series count skipped {}/{}: {}", spec.id(), grain, e.toString());
                }
            }
        }
        return total;
    }

    /**
     * Builds the ranking context from durable agent memory.
     *
     * <p>Two things are carried forward. Dismissals become full suppressions, so a judgement an
     * operator already made is not re-litigated every run. Series with an incident still open are
     * partially suppressed and carry their breach depth forward, which is what makes persistence a
     * real signal rather than a constant.
     *
     * <p>Incidents raised for the period being re-run are excluded from the depth calculation, so
     * pressing the run button twice on the same month does not manufacture a two-period streak.
     */
    private RankingContext memoryContext(List<Finding> findings, String period) {
        Map<String, Double> suppression = new HashMap<>();
        Map<String, Integer> consecutive = new HashMap<>();

        Map<String, Integer> depthByMetricEntity = new HashMap<>();
        Map<String, Boolean> openByMetricEntity = new HashMap<>();
        String periodSuffix = "-" + period;

        for (Incident incident : incidents.openIncidents()) {
            if (incident.id() != null && incident.id().contains(periodSuffix)) {
                continue;
            }
            int depth = incident.policy() == null ? 1 : Math.max(1, incident.policy().consecutivePeriods());
            for (Evidence evidence : incident.evidence()) {
                if (evidence == null || evidence.metricId() == null || evidence.entity() == null) {
                    continue;
                }
                String key = evidence.metricId() + "|" + evidence.entity();
                depthByMetricEntity.merge(key, depth, Math::max);
                openByMetricEntity.put(key, Boolean.TRUE);
            }
        }

        for (Finding finding : findings) {
            if (finding == null) {
                continue;
            }
            String key = RankingContext.key(finding);
            if (incidents.isSuppressed(finding)) {
                suppression.put(key, 1.0);
                continue;
            }
            String memoryKey = finding.metricId() + "|" + finding.entity();
            if (Boolean.TRUE.equals(openByMetricEntity.get(memoryKey))) {
                suppression.put(key, OPEN_INCIDENT_SUPPRESSION);
            }
            Integer depth = depthByMetricEntity.get(memoryKey);
            if (depth != null) {
                consecutive.put(key, depth + 1);
            }
        }
        return new RankingContext(suppression, consecutive);
    }

    /** Applies the SLA rules to every ranked finding, carrying breach depth from memory. */
    private Map<String, PolicyDecision> evaluatePolicy(List<Finding> ranked, RankingContext context) {
        Map<String, PolicyDecision> decisions = new LinkedHashMap<>();
        for (Finding finding : ranked) {
            Integer known = context.consecutiveFor(finding);
            PolicyDecision decision = known == null
                    ? slaPolicy.decide(finding)
                    : slaPolicy.decide(finding, Math.max(0, known - 1));
            decisions.put(finding.id(), decision);
        }
        return decisions;
    }

    private List<TriagePort.IncidentDraft> safeTriage(List<Finding> ranked, String period) {
        try {
            List<TriagePort.IncidentDraft> drafts = ports.triage().triage(ranked, period);
            return drafts == null ? List.of() : drafts;
        } catch (RuntimeException e) {
            log.error("Triage failed on tier {}: {}", ports.triage().tier(), e.toString());
            return List.of();
        }
    }

    private AttributionResult safeAttribute(String metricId, String period, String priorPeriod) {
        try {
            return attribution.attribute(metricId, period, priorPeriod);
        } catch (RuntimeException e) {
            log.warn("Attribution failed for {}: {}", metricId, e.toString());
            return AttributionResult.empty(metricId, period, priorPeriod);
        }
    }

    /**
     * Explains a cluster, degrading to a statement of what is known rather than fabricating a cause.
     *
     * <p>A failed reasoning call must not produce a confident-sounding explanation. The fallback text
     * says the explanation stage did not complete, which is a fact a reader can act on.
     */
    private ReasoningPort.Explanation safeExplain(
            TriagePort.IncidentDraft draft, List<Finding> members, AttributionResult attributed) {
        try {
            ReasoningPort.Explanation explanation =
                    ports.reasoning().explain(draft, members, attributed);
            if (explanation != null) {
                return explanation;
            }
        } catch (RuntimeException e) {
            log.error("Reasoning failed on tier {}: {}", ports.reasoning().tier(), e.toString());
        }
        Finding lead = members.getFirst();
        return new ReasoningPort.Explanation(
                "The explanation stage did not complete for this incident, so no cause is asserted. "
                        + "The movement itself is computed and stands: " + lead.metricId() + " on "
                        + lead.dimension() + "=" + lead.entity() + " moved " + lead.deltaPts()
                        + " between " + lead.priorPeriod() + " and " + lead.period() + ".",
                List.of(new Evidence(
                        "Movement recorded by the scanner without an accompanying explanation.",
                        lead.metricId(), lead.entity())),
                null);
    }

    private NarrativePort.Narrative safeNarrate(
            Incident incident, List<Finding> members, String persona) {
        try {
            NarrativePort.Narrative narrative = ports.narrative().narrate(incident, members, persona);
            if (narrative != null) {
                return narrative;
            }
        } catch (RuntimeException e) {
            log.error("Narration failed on tier {}: {}", ports.narrative().tier(), e.toString());
        }
        return new NarrativePort.Narrative(incident.title(), incident.whyNow(), incident.explanation());
    }

    // ---- incident assembly ------------------------------------------------------------------------

    private Incident draft(
            TriagePort.IncidentDraft draft,
            Finding lead,
            List<Finding> members,
            PolicyDecision decision,
            ReasoningPort.Explanation explanation,
            String period,
            Instant detectedAt) {

        List<Evidence> evidence = new ArrayList<>();
        // The lead evidence item names the metric and entity, and IncidentStore derives the follow-up
        // target from exactly that first item — so it must be the one the incident is really about.
        evidence.add(new Evidence(
                "%s on %s=%s measured %s in %s against %s in %s across %,d trips.".formatted(
                        lead.metricId(), lead.dimension(), lead.entity(),
                        String.format(Locale.ROOT, "%.4f", lead.current()), lead.period(),
                        String.format(Locale.ROOT, "%.4f", lead.prior()), lead.priorPeriod(),
                        lead.sampleSize()),
                lead.metricId(),
                lead.entity()));
        evidence.addAll(explanation.evidence());

        return new Incident(
                incidentId(draft, period),
                draft.title(),
                draft.whyNow(),
                draft.priority(),
                severityBand(decision, lead),
                draft.findingIds(),
                explanation.explanation(),
                evidence,
                List.of(),
                decision,
                qualityOf(lead),
                detectedAt.toString(),
                detectedAt.plus(followUpDays, ChronoUnit.DAYS).toString(),
                IncidentStore.STATUS_OPEN);
    }

    private static Incident withActions(Incident incident, List<Action> actions) {
        return new Incident(
                incident.id(), incident.title(), incident.whyNow(), incident.priority(),
                incident.severity(), incident.findingIds(), incident.explanation(), incident.evidence(),
                actions, incident.policy(), incident.quality(), incident.detectedAt(),
                incident.followUpAt(), incident.status());
    }

    private static Incident withNarrative(Incident incident, NarrativePort.Narrative narrative) {
        if (narrative == null) {
            return incident;
        }
        return new Incident(
                incident.id(),
                blankTo(narrative.title(), incident.title()),
                blankTo(narrative.whyNow(), incident.whyNow()),
                incident.priority(),
                incident.severity(),
                incident.findingIds(),
                blankTo(narrative.body(), incident.explanation()),
                incident.evidence(),
                incident.recommendedActions(),
                incident.policy(),
                incident.quality(),
                incident.detectedAt(),
                incident.followUpAt(),
                incident.status());
    }

    /**
     * Keeps an operator's lifecycle decision when a re-run re-derives the same incident.
     *
     * <p>Ids are stable by design, so a nightly sweep over an unchanged period rewrites the incident
     * it raised yesterday. Rewriting the numbers is correct — they may have moved. Rewriting the
     * <em>status</em> is not: an incident someone escalated to {@code MONITORING}, or resolved, would
     * silently revert to {@code OPEN} and appear on the morning list as though the operator had never
     * touched it. Machine judgement refreshes the evidence; human judgement outranks it on lifecycle.
     */
    private Incident preserveOperatorStatus(Incident incident) {
        String existing = this.incidents.byId(incident.id())
                .map(Incident::status)
                .orElse(null);
        if (existing == null || existing.isBlank()
                || IncidentStore.STATUS_OPEN.equalsIgnoreCase(existing)
                || existing.equalsIgnoreCase(incident.status())) {
            return incident;
        }
        log.debug("Incident {} keeps operator status {} across the re-run", incident.id(), existing);
        return new Incident(
                incident.id(), incident.title(), incident.whyNow(), incident.priority(),
                incident.severity(), incident.findingIds(), incident.explanation(), incident.evidence(),
                incident.recommendedActions(), incident.policy(), incident.quality(),
                incident.detectedAt(), incident.followUpAt(), existing);
    }

    /**
     * Stable incident id: cluster key plus period.
     *
     * <p>Stability is what makes a re-run idempotent — the same movement in the same month updates
     * one incident rather than opening a second one every night. {@code FollowUpScheduler} appends
     * {@code -esc<n>} to this when a breach persists, and strips it when computing the root.
     */
    private static String incidentId(TriagePort.IncidentDraft draft, String period) {
        String key = draft.clusterKey() == null ? "incident" : draft.clusterKey();
        return "inc-" + slug(key) + "-" + period;
    }

    private static String slug(String value) {
        return value.trim().toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-|-$", "");
    }

    /**
     * The severity band shown on the incident.
     *
     * <p>An SLA verdict wins whenever there is one, so the incident and the policy decision cannot
     * disagree. Metrics with no contractual target — occupancy, cost per trip — fall back to the
     * benchmark engine's severity score, banded with the same vocabulary so the console never has to
     * handle two severity scales.
     */
    private static String severityBand(PolicyDecision decision, Finding lead) {
        if (decision != null && decision.breached() && decision.severityBand() != null) {
            return decision.severityBand();
        }
        double severity = lead.observation() == null ? 0.0 : lead.observation().severity();
        if (severity >= SEVERITY_MAJOR) {
            return SlaPolicy.BAND_MAJOR;
        }
        return severity >= SEVERITY_MINOR ? SlaPolicy.BAND_MINOR : SlaPolicy.BAND_NONE;
    }

    private Quality qualityOf(Finding lead) {
        if (lead.observation() != null && lead.observation().quality() != null) {
            return lead.observation().quality();
        }
        return ingestReport().toQuality();
    }

    private static String blankTo(String candidate, String fallback) {
        return candidate == null || candidate.isBlank() ? fallback : candidate;
    }

    // ---- accounting -------------------------------------------------------------------------------

    /**
     * Per-stage wall clock and token attribution.
     *
     * <p>Token counts are taken as the difference between two {@link UsageRecorder} snapshots around
     * each stage. That is the only way to get a real number: the recorder is written by the LLM client
     * deep inside a port implementation, and the orchestrator has no visibility of individual calls.
     */
    private final class RunLedger {

        private final Map<String, Long> millis = new LinkedHashMap<>();
        private final Map<String, long[]> tokens = new LinkedHashMap<>();

        <T> T time(String stage, Supplier<T> work) {
            UsageRecorder.Snapshot before = usage.snapshot();
            long started = System.nanoTime();
            try {
                return work.get();
            } finally {
                millis.merge(stage, (System.nanoTime() - started) / 1_000_000L, Long::sum);
                UsageRecorder.Snapshot after = usage.snapshot();
                long[] delta = {
                        Math.max(0L, after.promptTokens() - before.promptTokens()),
                        Math.max(0L, after.completionTokens() - before.completionTokens())};
                tokens.merge(stage, delta, (a, b) -> new long[] {a[0] + b[0], a[1] + b[1]});
            }
        }

        long promptTokens(String stage) {
            long[] value = tokens.get(stage);
            return value == null ? 0L : value[0];
        }

        long completionTokens(String stage) {
            long[] value = tokens.get(stage);
            return value == null ? 0L : value[1];
        }

        List<String> timings() {
            return millis.entrySet().stream()
                    .sorted(Comparator.comparing(Map.Entry::getKey))
                    .map(entry -> entry.getKey() + "=" + entry.getValue() + "ms")
                    .toList();
        }
    }
}
