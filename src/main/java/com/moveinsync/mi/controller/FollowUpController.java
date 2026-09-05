package com.moveinsync.mi.controller;

import com.moveinsync.mi.incident.FollowUp;
import com.moveinsync.mi.incident.FollowUpScheduler;
import com.moveinsync.mi.incident.IncidentStore;
import com.moveinsync.mi.model.Incident;
import java.time.Instant;
import java.util.List;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * On-demand follow-up: the demo button for the autonomous loop.
 */
@RestController
@RequestMapping("/api/followups")
@CrossOrigin
public class FollowUpController {

    private final IncidentStore store;
    private final FollowUpScheduler scheduler;

    public FollowUpController(IncidentStore store, FollowUpScheduler scheduler) {
        this.store = store;
        this.scheduler = scheduler;
    }

    public record RunRequest(String asOf, String period) {
    }

    public record RunResponse(List<Incident> escalations, List<FollowUp> followUps) {
    }

    @GetMapping
    public List<FollowUp> list() {
        return store.allFollowUps();
    }

    /**
     * Fires every follow-up that is due at {@code asOf} (default: now). Optional {@code period}
     * forces the re-check month (pass {@code 2026-07} on stage).
     */
    @PostMapping("/run")
    public RunResponse run(@RequestBody(required = false) RunRequest request) {
        Instant asOf = parseInstant(request == null ? null : request.asOf());
        String period = request == null ? null : request.period();
        List<Incident> escalations = scheduler.runDueFollowUps(asOf, period);
        return new RunResponse(escalations, store.allFollowUps());
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) {
            return Instant.now();
        }
        try {
            return Instant.parse(value);
        } catch (RuntimeException e) {
            return Instant.now();
        }
    }
}
