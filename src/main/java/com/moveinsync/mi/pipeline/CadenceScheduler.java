package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.model.RunSummary;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * Runs the pipeline on a schedule, so the platform produces findings nobody asked for.
 *
 * <p>That is the whole distinction between this and a dashboard. A dashboard answers questions; an
 * agent notices things. Everything else in the platform executes because a human pressed something —
 * this class executes because the calendar said so, and {@code FollowUpScheduler} executes because
 * the system previously promised to look again. Those two loops are what make the behaviour
 * autonomous rather than merely automated.
 *
 * <h2>Cadence tiers are configuration, not a redesign</h2>
 *
 * <p>The obvious challenge to a nightly batch is "what about the things that need reacting to in five
 * minutes?" The answer is that cadence is a property of the <em>schedule</em>, not of the pipeline.
 * {@link SenseReasonActPipeline#run(String, String)} takes a period pair and is stateless across
 * runs; nothing in it assumes a monthly grain or a nightly trigger. Four tiers fall out of
 * configuration alone:
 *
 * <ul>
 *   <li><b>5-minute</b> — safety-critical signals: panic alerts, escort violations on a night shift,
 *       a vehicle that stopped reporting. Same scan, a period grain of hours and a metric subset with
 *       a low {@code min_sample}. Wire with a second {@code @Scheduled(fixedDelay = 300_000)} method
 *       calling {@code run} for the current hour.</li>
 *   <li><b>Hourly</b> — operational drift within the working day: on-time arrival for the morning
 *       login peak, no-shows against a route's plan.</li>
 *   <li><b>Daily</b> — the default here. Yesterday against the day before, or the current month
 *       against the last, which is the grain the shipped extracts support.</li>
 *   <li><b>Weekly / monthly</b> — contract-level review: cost per kilometre by vendor, slab drift,
 *       billing regime mix. These want the longer window because their metrics are noisy below it.</li>
 * </ul>
 *
 * <p>What changes between those tiers is the cron expression, the period labels passed in, and the
 * volume gate the catalog declares — none of which is code. What deliberately does <em>not</em>
 * change is the detection, ranking, policy and governance path, because a five-minute alert that
 * bypassed the volume gate would be exactly the noise generator this design exists to avoid.
 *
 * <p>The nightly job is disabled by default. An assessment reviewer starting the app should get the
 * demo button, not a full sweep firing at 02:30 against whatever data happens to be mounted; set
 * {@code app.cadence.enabled=true} to arm it.
 */
@Service
public class CadenceScheduler {

    private static final Logger log = LoggerFactory.getLogger(CadenceScheduler.class);

    private final SenseReasonActPipeline pipeline;
    private final boolean enabled;

    public CadenceScheduler(
            SenseReasonActPipeline pipeline,
            @Value("${app.cadence.enabled:false}") boolean enabled) {
        this.pipeline = pipeline;
        this.enabled = enabled;
    }

    /**
     * The nightly sweep: the latest period the fact store holds, against the one before it.
     *
     * <p>Defaults to 02:30 in the configured zone — after any overnight extract has landed and before
     * the morning login peak, so an operator reading the brief at 07:00 is reading last night's
     * verdict rather than a run that is still executing.
     *
     * <p>Failures are logged and swallowed. A scheduled method that throws is silently unscheduled by
     * some executors, which would leave the platform looking healthy while having quietly stopped
     * being an agent at all.
     */
    @Scheduled(
            cron = "${app.cadence.nightly-cron:0 30 2 * * *}",
            zone = "${app.cadence.zone:UTC}")
    public void nightly() {
        if (!enabled) {
            log.debug("Nightly cadence is disabled (app.cadence.enabled=false); skipping");
            return;
        }
        try {
            RunSummary summary = pipeline.run();
            log.info("Nightly run {} complete: {} candidates, {} incidents, {} ms, ${}",
                    summary.runId(), summary.candidates(), summary.incidents(), summary.wallClockMs(),
                    String.format(Locale.ROOT, "%.4f", summary.estimatedCostUsd()));
        } catch (IllegalStateException e) {
            // Either a run is already in progress or the fact store is empty. Both are expected
            // operational states, not faults.
            log.warn("Nightly run skipped: {}", e.getMessage());
        } catch (RuntimeException e) {
            log.error("Nightly run failed: {}", e.toString(), e);
        }
    }

    /** Whether the nightly sweep is armed. Surfaced by the health endpoint. */
    public boolean isEnabled() {
        return enabled;
    }
}
