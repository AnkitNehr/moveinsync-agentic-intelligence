package com.moveinsync.mi.model;

import java.util.List;

/**
 * Data-quality envelope attached to every metric observation.
 *
 * <p>Nulls in the source extracts are meaningful, not errors — an unacknowledged alert, a
 * non-boarding employee, an incomplete leg. Rows are never dropped; instead the coverage ratio and
 * the caveat list record exactly how much of the underlying population was usable.
 *
 * @param coverage   fraction of rows in the segment with a non-null, parseable value for the metric
 * @param confidence coarse band derived from coverage and sample size: HIGH / MEDIUM / LOW
 * @param caveats    human-readable data-quality warnings (negative km, delay &gt; 1440 minutes,
 *                   stwid placeholder rows, schema drift across the monthly ride files, ...)
 */
public record Quality(double coverage, String confidence, List<String> caveats) {

    public Quality {
        caveats = caveats == null ? List.of() : List.copyOf(caveats);
    }

    public static Quality unknown() {
        return new Quality(0.0, "LOW", List.of("coverage not computed"));
    }
}
