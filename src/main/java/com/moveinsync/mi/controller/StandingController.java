package com.moveinsync.mi.controller;

import com.moveinsync.mi.anomaly.StandingOutlierScanner;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricQueryService;
import java.util.List;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Segments that are persistently poor rather than newly worse.
 *
 * <p>Deliberately not part of {@code /api/incidents}. An incident is something that happened and
 * carries a movement, an attribution and a policy verdict; these have none of those, because nothing
 * changed. They answer the other half of the question — "who is quietly bad?" — which the incident
 * pipeline is structurally unable to see.
 */
@RestController
@RequestMapping("/api/standing")
@CrossOrigin
public class StandingController {

    private final StandingOutlierScanner scanner;
    private final MetricQueryService metrics;
    private final MetricCatalog catalog;

    public StandingController(
            StandingOutlierScanner scanner, MetricQueryService metrics, MetricCatalog catalog) {
        this.scanner = scanner;
        this.metrics = metrics;
        this.catalog = catalog;
    }

    @GetMapping
    public List<StandingOutlierScanner.StandingOutlier> list(@RequestParam(required = false) String period) {
        String resolved = period == null || period.isBlank() ? latestLoadedPeriod() : period;
        return resolved == null ? List.of() : scanner.scan(resolved);
    }

    /**
     * The newest period any metric reports, so the endpoint works without a query parameter.
     *
     * <p>Asked per metric rather than globally because the fact store has no single answer: bills and
     * trips can be loaded to different months, and reporting a period one of them cannot serve would
     * return an empty list that looks like "nothing is wrong".
     */
    private String latestLoadedPeriod() {
        return catalog.ids().stream()
                .map(metrics::latestPeriod)
                .flatMap(java.util.Optional::stream)
                .max(String::compareTo)
                .orElse(null);
    }
}
