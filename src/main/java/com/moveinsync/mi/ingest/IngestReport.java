package com.moveinsync.mi.ingest;

import com.moveinsync.mi.model.Quality;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The data-quality receipt for one ingest run.
 *
 * <h2>The invariant</h2>
 *
 * {@code rowsKept == rowsRead}. Always. In this dataset a null is not a defect to be cleaned away —
 * an unacknowledged alert, a non-boarding employee, an incomplete leg and a fixed-rate billing line
 * with zero kilometres are all legitimate facts that happen to leave a column empty. Dropping those
 * rows would quietly bias every rate the platform computes: filtering out the 190,009 employee legs
 * with a null pickup epoch would push boarding rates to 100%, and filtering the 248,191 zero-km
 * billing lines would erase 40% of spend. So nothing is ever filtered, only <em>flagged</em>, and
 * {@link #validate()} fails the run loudly if that ever stops being true.
 *
 * @param rowsRead   rows parsed out of the CSV extracts
 * @param rowsKept   rows published to the query layer — equal to {@code rowsRead} by construction
 * @param flagCounts named data-quality counters, ordered for stable reporting
 * @param coverage   fraction of rows usable for the core on-time metric (trip id, date and delay
 *                   all parsed successfully)
 * @param caveats    human-readable warnings carried onto every downstream observation
 */
public record IngestReport(
        long rowsRead,
        long rowsKept,
        Map<String, Long> flagCounts,
        double coverage,
        List<String> caveats) {

    public IngestReport {
        flagCounts = flagCounts == null
                ? Map.of()
                : Collections.unmodifiableMap(new LinkedHashMap<>(flagCounts));
        caveats = caveats == null ? List.of() : List.copyOf(caveats);
    }

    /**
     * Enforces the no-drop invariant.
     *
     * @return this report, so it can be used inline
     * @throws IllegalStateException if any row was lost between the CSV and the query layer
     */
    public IngestReport validate() {
        if (rowsKept != rowsRead) {
            throw new IllegalStateException(
                    "Ingest invariant violated: rowsRead=" + rowsRead + " but rowsKept=" + rowsKept
                            + " (" + dropped() + " rows lost). Nulls are meaningful in this dataset "
                            + "and must be flagged, never filtered — a WHERE clause has leaked into "
                            + "an ingest view.");
        }
        if (coverage < 0.0 || coverage > 1.0) {
            throw new IllegalStateException("Coverage must be a fraction in [0,1] but was " + coverage);
        }
        return this;
    }

    /** Rows lost between read and publish. Zero unless something is broken. */
    public long dropped() {
        return rowsRead - rowsKept;
    }

    /** A named flag counter, or {@code 0} when the flag was not computed. */
    public long flag(String name) {
        return flagCounts.getOrDefault(name, 0L);
    }

    /** Share of rows carrying a given flag, in {@code [0,1]}. */
    public double flagRate(String name) {
        return rowsRead == 0 ? 0.0 : (double) flag(name) / rowsRead;
    }

    /** The quality envelope attached to observations produced from this run. */
    public Quality toQuality() {
        return new Quality(coverage, confidenceBand(coverage, rowsKept), caveats);
    }

    /** Same envelope, with one extra segment-specific caveat appended. */
    public Quality toQuality(String extraCaveat) {
        List<String> merged = new ArrayList<>(caveats);
        if (extraCaveat != null && !extraCaveat.isBlank() && !merged.contains(extraCaveat)) {
            merged.add(extraCaveat);
        }
        return new Quality(coverage, confidenceBand(coverage, rowsKept), merged);
    }

    /**
     * The single confidence-banding rule for the whole platform — the scanner, the attributor and
     * the incident writer must all agree on what "HIGH confidence" means, so they all call this.
     *
     * <p>Both inputs matter independently. Perfect coverage over 40 trips is still a coin flip
     * (edge case 14: {@code trip_nodal='SHUTTLE'} has 244 trips and produced a bogus -26.6 point
     * swing), and 200,000 trips with half the field missing is not evidence either.
     */
    public static String confidenceBand(double coverage, long sampleSize) {
        if (coverage >= 0.98 && sampleSize >= 10_000) {
            return "HIGH";
        }
        if (coverage >= 0.90 && sampleSize >= 500) {
            return "MEDIUM";
        }
        return "LOW";
    }

    /** Empty report for a run that has not ingested anything yet. */
    public static IngestReport empty() {
        return new IngestReport(0, 0, Map.of(), 0.0, List.of("ingest not yet run"));
    }
}
