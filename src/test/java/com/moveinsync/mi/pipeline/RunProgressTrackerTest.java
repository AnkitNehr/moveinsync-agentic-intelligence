package com.moveinsync.mi.pipeline;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.model.RunProgress;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class RunProgressTrackerTest {

    private final RunProgressTracker tracker = new RunProgressTracker();

    @Test
    @DisplayName("idle snapshot is not running and has no counts")
    void idleIsEmpty() {
        RunProgress idle = tracker.snapshot();
        assertThat(idle.running()).isFalse();
        assertThat(idle.currentStage()).isNull();
        assertThat(idle.completed()).isEmpty();
        assertThat(idle.trips()).isNull();
    }

    @Test
    @DisplayName("enter then complete fills the funnel in catalog order, not alphabetical")
    void completedFollowsFunnelOrder() {
        tracker.begin("run-1", Instant.parse("2026-06-01T00:00:00Z"));
        tracker.enter("scan");
        tracker.complete("scan", 10, 0, 0);
        tracker.enter("ingest");
        tracker.complete("ingest", 8, 0, 0);
        tracker.enter("actionGuard");
        tracker.complete("actionGuard", 1, 0, 0);

        assertThat(tracker.snapshot().completed())
                .extracting(RunProgress.StageTiming::stage)
                .containsExactly("ingest", "scan", "actionGuard");
    }

    @Test
    @DisplayName("repeated timings of the same stage accumulate")
    void repeatedStageMergesMillisAndTokens() {
        tracker.begin("run-1", Instant.parse("2026-06-01T00:00:00Z"));
        tracker.enter("reason");
        tracker.complete("reason", 100, 10, 4);
        tracker.enter("reason");
        tracker.complete("reason", 50, 5, 2);

        RunProgress.StageTiming reason = tracker.snapshot().completed().getFirst();
        assertThat(reason.millis()).isEqualTo(150);
        assertThat(reason.promptTokens()).isEqualTo(15);
        assertThat(reason.completionTokens()).isEqualTo(6);
    }

    @Test
    @DisplayName("counts appear as stages land, and finish clears current without wiping them")
    void countsSurviveFinish() {
        tracker.begin("run-1", Instant.parse("2026-06-01T00:00:00Z"));
        tracker.enter("ingest");
        tracker.trips(615_546L);
        tracker.complete("ingest", 8000, 0, 0);
        tracker.findings(50);
        tracker.seriesEvaluated(1900);
        tracker.candidates(20);
        tracker.incidents(2);
        tracker.finish();

        RunProgress done = tracker.snapshot();
        assertThat(done.running()).isFalse();
        assertThat(done.currentStage()).isNull();
        assertThat(done.trips()).isEqualTo(615_546L);
        assertThat(done.seriesEvaluated()).isEqualTo(1900);
        assertThat(done.findings()).isEqualTo(50);
        assertThat(done.candidates()).isEqualTo(20);
        assertThat(done.incidents()).isEqualTo(2);
        assertThat(done.runId()).isEqualTo("run-1");
    }

    @Test
    @DisplayName("currentStage is the in-flight step until complete")
    void currentStageWhileRunning() {
        tracker.begin("run-1", Instant.parse("2026-06-01T00:00:00Z"));
        tracker.enter("policy");
        assertThat(tracker.snapshot().running()).isTrue();
        assertThat(tracker.snapshot().currentStage()).isEqualTo("policy");
        tracker.complete("policy", 4, 0, 0);
        assertThat(tracker.snapshot().currentStage()).isNull();
        assertThat(tracker.snapshot().running()).isTrue();
    }
}
