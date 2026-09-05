package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.model.RunProgress;
import com.moveinsync.mi.model.RunProgress.StageTiming;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Copy-on-write snapshot of the in-flight run. The execute thread writes; HTTP polls read.
 *
 * <p>Mutations are synchronized so a half-updated map cannot leak. Readers take an immutable
 * {@link RunProgress} and never block the pipeline beyond a short lock.
 */
final class RunProgressTracker {

    private final AtomicReference<RunProgress> published = new AtomicReference<>(RunProgress.idle());

    private String runId;
    private String startedAt;
    private String currentStage;
    private final Map<String, StageTiming> completed = new LinkedHashMap<>();
    private Long trips;
    private Integer seriesEvaluated;
    private Integer findings;
    private Integer candidates;
    private Integer incidents;
    private boolean active;

    synchronized void begin(String runId, Instant startedAt) {
        this.runId = runId;
        this.startedAt = startedAt == null ? null : startedAt.toString();
        this.currentStage = null;
        this.completed.clear();
        this.trips = null;
        this.seriesEvaluated = null;
        this.findings = null;
        this.candidates = null;
        this.incidents = null;
        this.active = true;
        publishLocked();
    }

    synchronized void enter(String stage) {
        if (!active || stage == null || stage.isBlank()) {
            return;
        }
        this.currentStage = stage;
        publishLocked();
    }

    synchronized void complete(String stage, long millis, long promptTokens, long completionTokens) {
        if (!active || stage == null || stage.isBlank()) {
            return;
        }
        StageTiming prior = completed.get(stage);
        long ms = millis + (prior == null ? 0L : prior.millis());
        long prompt = promptTokens + (prior == null ? 0L : prior.promptTokens());
        long completion = completionTokens + (prior == null ? 0L : prior.completionTokens());
        completed.put(stage, new StageTiming(stage, ms, prompt, completion));
        if (stage.equals(currentStage)) {
            currentStage = null;
        }
        publishLocked();
    }

    synchronized void trips(long trips) {
        this.trips = trips;
        publishLocked();
    }

    synchronized void seriesEvaluated(int seriesEvaluated) {
        this.seriesEvaluated = seriesEvaluated;
        publishLocked();
    }

    synchronized void findings(int findings) {
        this.findings = findings;
        publishLocked();
    }

    synchronized void candidates(int candidates) {
        this.candidates = candidates;
        publishLocked();
    }

    synchronized void incidents(int incidents) {
        this.incidents = incidents;
        publishLocked();
    }

    synchronized void finish() {
        this.active = false;
        this.currentStage = null;
        publishLocked();
    }

    RunProgress snapshot() {
        return published.get();
    }

    private void publishLocked() {
        published.set(new RunProgress(
                active,
                runId,
                startedAt,
                currentStage,
                funnelCompleted(),
                trips,
                seriesEvaluated,
                findings,
                candidates,
                incidents));
    }

    private List<StageTiming> funnelCompleted() {
        List<StageTiming> ordered = new ArrayList<>();
        for (String stage : RunProgress.FUNNEL) {
            StageTiming timing = completed.get(stage);
            if (timing != null) {
                ordered.add(timing);
            }
        }
        for (StageTiming timing : completed.values()) {
            if (!RunProgress.FUNNEL.contains(timing.stage())) {
                ordered.add(timing);
            }
        }
        return List.copyOf(ordered);
    }
}
