package com.moveinsync.mi.ingest;

import com.moveinsync.mi.model.Quality;
import jakarta.annotation.PostConstruct;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Counts every known data defect once per run and turns those counts into the {@link Quality}
 * envelope that travels with every observation, finding and incident the platform emits.
 *
 * <p>The contract is deliberately narrow: this class <b>never repairs and never filters</b>. It
 * reports. A negative distance, a delay of 10,644 minutes, an unacknowledged alert and a billing
 * line whose trip id is the word {@code OverHead} all stay exactly where they are; what changes is
 * that a reader of a downstream number can see how many of them were in the denominator.
 *
 * <p>Headline {@code coverage} is measured on the {@code trips} relation against the fields the
 * on-time-arrival metric actually needs — trip id, trip date and delay minutes. Field-level
 * coverage, including GPS-derived {@code actual_end_epoch}, is published separately through
 * {@link #coverageByField()}.
 */
@Service
public class QualityFlagger {

    private static final Logger log = LoggerFactory.getLogger(QualityFlagger.class);

    /** Edge case 11: delays beyond a full day are data artefacts, not operations. */
    public static final double DELAY_OUTLIER_MINUTES = 1440.0;

    private final DuckDbService db;

    private volatile IngestReport report = IngestReport.empty();
    private volatile Map<String, Double> coverageByField = Map.of();

    public QualityFlagger(DuckDbService db) {
        this.db = db;
    }

    @PostConstruct
    public void init() {
        refresh();
        logReport();
    }

    /** The cached report for this run. Computed once at startup. */
    public IngestReport report() {
        return report;
    }

    /** The quality envelope every observation inherits. */
    public Quality quality() {
        return report.toQuality();
    }

    /** Raw defect counters, insertion-ordered: trips first, then bills / alerts / emp / feedback. */
    public Map<String, Long> flagCounts() {
        return report.flagCounts();
    }

    /** Per-field non-null coverage on {@code trips}, including the GPS-derived actual end time. */
    public Map<String, Double> coverageByField() {
        return coverageByField;
    }

    /** Re-runs every quality query and replaces the cached report. */
    public IngestReport refresh() {
        Map<String, Long> flags = new LinkedHashMap<>();

        Map<String, Object> t = row("""
                SELECT
                    count(*)                                                          AS rows_read,
                    count(*) FILTER (WHERE trip_id       IS NULL)                     AS bad_trip_id,
                    count(*) FILTER (WHERE trip_date     IS NULL)                     AS bad_date,
                    count(*) FILTER (WHERE delay_minutes IS NULL)                     AS null_delay,
                    count(*) FILTER (WHERE actual_end_epoch IS NULL)                  AS null_actual_end,
                    count(*) FILTER (WHERE planned_km    IS NULL)                     AS null_planned_km,
                    count(*) FILTER (WHERE traveled_km   IS NULL)                     AS null_traveled_km,
                    count(*) FILTER (WHERE is_driver_nc  IS NULL)                     AS null_driver_nc,
                    count(*) FILTER (WHERE is_cab_nc     IS NULL)                     AS null_cab_nc,
                    count(*) FILTER (WHERE planned_km < 0 OR traveled_km < 0)         AS negative_km,
                    count(*) FILTER (WHERE delay_minutes > 1440)                      AS delay_over_24h,
                    count(*) FILTER (WHERE trip_nodal = 'NA')                         AS trip_nodal_na,
                    count(*) FILTER (WHERE trip_id IS NOT NULL
                                       AND trip_date IS NOT NULL
                                       AND delay_minutes IS NOT NULL)                 AS usable_core,
                    coalesce(round(max(delay_minutes)), 0)                            AS max_delay_minutes
                FROM trips
                """);

        long rows = asLong(t.get("rows_read"));
        putAll(flags, t,
                "bad_trip_id", "bad_date", "null_delay", "null_actual_end", "null_planned_km",
                "null_traveled_km", "null_driver_nc", "null_cab_nc", "negative_km",
                "delay_over_24h", "trip_nodal_na", "max_delay_minutes");

        Map<String, Double> coverage = new LinkedHashMap<>();
        coverage.put("trip_id", share(rows - asLong(t.get("bad_trip_id")), rows));
        coverage.put("trip_date", share(rows - asLong(t.get("bad_date")), rows));
        coverage.put("delay_minutes", share(rows - asLong(t.get("null_delay")), rows));
        // "GPS coverage" in practice: did the trip report an actual end time at all?
        coverage.put("actual_end_epoch", share(rows - asLong(t.get("null_actual_end")), rows));
        coverage.put("planned_km", share(rows - asLong(t.get("null_planned_km")), rows));
        coverage.put("traveled_km", share(rows - asLong(t.get("null_traveled_km")), rows));
        coverage.put("is_driver_nc", share(rows - asLong(t.get("null_driver_nc")), rows));
        this.coverageByField = Collections.unmodifiableMap(coverage);

        double headline = share(asLong(t.get("usable_core")), rows);

        // ---- Cross-relation defects. Same rule: count, never correct. ------------------------
        Map<String, Object> b = row("""
                SELECT
                    count(*)                                                          AS rows_read,
                    count(*) FILTER (WHERE is_overhead)                               AS overhead_rows,
                    count(*) FILTER (WHERE slab_name IS NULL)                         AS null_slab,
                    count(*) FILTER (WHERE billing_regime = 'FIXED_RATE')             AS fixed_rate_rows,
                    count(*) FILTER (WHERE zero_km)                                   AS zero_km_rows,
                    count(*) FILTER (WHERE billing_regime = 'DISTANCE_BASED'
                                       AND zero_km)                                   AS distance_zero_km,
                    count(*) FILTER (WHERE trip_cost IS NULL)                         AS null_cost,
                    count(*) FILTER (WHERE cost_per_km IS NOT NULL)                   AS cost_per_km_defined
                FROM bills
                """);
        flags.put("bill_rows", asLong(b.get("rows_read")));
        flags.put("bill_overhead_rows", asLong(b.get("overhead_rows")));
        flags.put("bill_null_slab", asLong(b.get("null_slab")));
        flags.put("bill_fixed_rate_rows", asLong(b.get("fixed_rate_rows")));
        flags.put("bill_zero_km_rows", asLong(b.get("zero_km_rows")));
        flags.put("bill_distance_zero_km", asLong(b.get("distance_zero_km")));
        flags.put("bill_null_cost", asLong(b.get("null_cost")));
        flags.put("bill_cost_per_km_defined", asLong(b.get("cost_per_km_defined")));

        Map<String, Object> a = row("""
                SELECT
                    count(*)                                                          AS rows_read,
                    count(*) FILTER (WHERE severity IS NULL)                          AS severity_null,
                    count(*) FILTER (WHERE severity_raw = 'False')                    AS severity_false,
                    count(*) FILTER (WHERE unacknowledged)                            AS unacknowledged,
                    count(*) FILTER (WHERE stwid_placeholder)                         AS placeholder_stwid,
                    count(*) FILTER (WHERE start_time IS NULL)                        AS bad_start_time
                FROM alerts
                """);
        flags.put("alerts_rows", asLong(a.get("rows_read")));
        flags.put("alerts_severity_null", asLong(a.get("severity_null")));
        flags.put("alerts_severity_false", asLong(a.get("severity_false")));
        flags.put("alerts_unacknowledged", asLong(a.get("unacknowledged")));
        flags.put("alerts_placeholder_stwid", asLong(a.get("placeholder_stwid")));
        flags.put("alerts_bad_start_time", asLong(a.get("bad_start_time")));

        Map<String, Object> e = row("""
                SELECT
                    count(*)                                                          AS rows_read,
                    count(*) FILTER (WHERE km_negative)                               AS negative_km,
                    count(*) FILTER (WHERE stwid_placeholder)                         AS placeholder_stwid,
                    count(*) FILTER (WHERE incomplete_leg)                            AS incomplete_leg,
                    count(*) FILTER (WHERE trip_date IS NULL)                         AS bad_date,
                    coalesce(round(min(least(coalesce(planned_km, 0),
                                             coalesce(traveled_km, 0))), 2), 0)       AS min_km
                FROM emp
                """);
        flags.put("emp_rows", asLong(e.get("rows_read")));
        flags.put("emp_negative_km", asLong(e.get("negative_km")));
        flags.put("emp_placeholder_stwid", asLong(e.get("placeholder_stwid")));
        flags.put("emp_incomplete_leg", asLong(e.get("incomplete_leg")));
        flags.put("emp_bad_date", asLong(e.get("bad_date")));
        double minEmpKm = asDouble(e.get("min_km"));

        Map<String, Object> f = row("""
                SELECT
                    count(*)                                                          AS rows_read,
                    count(*) FILTER (WHERE trip_date IS NULL)                         AS bad_date,
                    count(*) FILTER (WHERE marshal_rating IS NULL)                    AS no_marshal_rating,
                    count(*) FILTER (WHERE stwid_placeholder)                         AS placeholder_stwid,
                    count(*) FILTER (WHERE avg_rating IS NULL)                        AS unrated
                FROM feedback
                """);
        flags.put("feedback_rows", asLong(f.get("rows_read")));
        flags.put("feedback_bad_date", asLong(f.get("bad_date")));
        flags.put("feedback_no_marshal_rating", asLong(f.get("no_marshal_rating")));
        flags.put("feedback_placeholder_stwid", asLong(f.get("placeholder_stwid")));
        flags.put("feedback_unrated", asLong(f.get("unrated")));

        List<String> caveats = buildCaveats(rows, flags, coverage, minEmpKm);

        // rowsRead / rowsKept are stated for trips, the fact table the headline coverage describes.
        // The other four relations are invariant-checked here as well.
        long tripsRead = db.rowsRead().getOrDefault("trips", rows);
        IngestReport built = new IngestReport(tripsRead, rows, flags, headline, caveats).validate();
        assertNoRelationDroppedRows();

        this.report = built;
        return built;
    }

    /** Every ingest view is unfiltered, so every relation must round-trip its row count. */
    private void assertNoRelationDroppedRows() {
        Map<String, Long> read = db.rowsRead();
        Map<String, Long> kept = db.rowsKept();
        for (String relation : DuckDbService.RELATIONS) {
            long r = read.getOrDefault(relation, 0L);
            long k = kept.getOrDefault(relation, 0L);
            if (r != k) {
                throw new IllegalStateException("Relation '" + relation + "' dropped rows: read="
                        + r + " kept=" + k + " — ingest views must never filter.");
            }
        }
    }

    /**
     * Turns counters into sentences a transport manager can act on. Only defects that are actually
     * present get a caveat; a clean run says so instead of reciting a checklist.
     */
    private List<String> buildCaveats(
            long rows, Map<String, Long> flags, Map<String, Double> coverage, double minEmpKm) {

        List<String> c = new ArrayList<>();

        // Always stated: these shape how every number below was produced.
        c.add("Schema drifts across the three monthly ride extracts (is_driver_nc/is_cab_nc typed in "
                + "Jun-Jul but untyped in May, planned_km untyped in July); all columns are read as "
                + "text and TRY_CAST, so a bad value becomes NULL instead of failing the run.");
        c.add("No row is ever dropped: " + fmt(rows) + " trips read, " + fmt(rows)
                + " kept. Nulls are flagged as findings, not filtered as errors.");

        long badId = flags.getOrDefault("bad_trip_id", 0L);
        if (badId > 0) {
            c.add(fmt(badId) + " trips (" + pct(badId, rows) + ") have an unparseable trip_id and "
                    + "cannot be joined to billing, alerts or feedback.");
        }
        long badDate = flags.getOrDefault("bad_date", 0L);
        if (badDate > 0) {
            c.add(fmt(badDate) + " trips have an unparseable trip_date and are excluded from every "
                    + "month-over-month comparison.");
        }
        long negKm = flags.getOrDefault("negative_km", 0L);
        long empNeg = flags.getOrDefault("emp_negative_km", 0L);
        if (negKm > 0 || empNeg > 0) {
            c.add("Negative distances are present and physically impossible (" + fmt(negKm)
                    + " trip rows, " + fmt(empNeg) + " employee rows, minimum " + minEmpKm
                    + " km); they are flagged, not corrected, so distance aggregates are affected.");
        }
        long outliers = flags.getOrDefault("delay_over_24h", 0L);
        if (outliers > 0) {
            c.add(fmt(outliers) + " trips report a delay beyond 24 hours (maximum "
                    + fmt(flags.getOrDefault("max_delay_minutes", 0L))
                    + " minutes, over 7 days); treat mean delay with suspicion and prefer the "
                    + "on-time rate, which is threshold-based and immune to these.");
        }
        double gps = coverage.getOrDefault("actual_end_epoch", 1.0);
        if (gps < 1.0) {
            c.add("Actual end time is missing on " + pct(rows - Math.round(gps * rows), rows)
                    + " of trips, so completion-time metrics cover " + pctOf(gps) + " of the fleet.");
        }
        long nullNc = flags.getOrDefault("null_driver_nc", 0L)
                + flags.getOrDefault("null_cab_nc", 0L);
        if (nullNc > 0) {
            c.add(fmt(nullNc) + " non-compliance flags did not parse to a boolean (May extract "
                    + "stores them untyped) and are counted as unknown, not as compliant.");
        }
        long overhead = flags.getOrDefault("bill_overhead_rows", 0L);
        if (overhead > 0) {
            c.add(fmt(overhead) + " billing lines carry the literal trip_id 'OverHead'. They are real "
                    + "charges kept in cost totals but join to no trip, so per-trip cost is computed "
                    + "over the remainder.");
        }
        long fixed = flags.getOrDefault("bill_fixed_rate_rows", 0L);
        long billRows = flags.getOrDefault("bill_rows", 0L);
        long zeroKm = flags.getOrDefault("bill_zero_km_rows", 0L);
        if (zeroKm > 0) {
            c.add("total_trip_km is 0 on " + pct(zeroKm, billRows) + " of billing lines. This is "
                    + "fixed-rate contracting (" + pct(fixed, billRows) + " of lines: HYD, ORRNEW, "
                    + "EV-Z and the Short/Medium/Long slabs), not missing data — cost per km is "
                    + "reported only for the " + fmt(flags.getOrDefault("bill_cost_per_km_defined", 0L))
                    + " distance-based lines with positive distance.");
        }
        long nullSlab = flags.getOrDefault("bill_null_slab", 0L);
        if (nullSlab > 0) {
            c.add("slab_name is absent on " + pct(nullSlab, billRows) + " of billing lines, so "
                    + "slab-level cost comparisons cover only part of spend.");
        }
        long sevNull = flags.getOrDefault("alerts_severity_null", 0L);
        long sevFalse = flags.getOrDefault("alerts_severity_false", 0L);
        long alertRows = flags.getOrDefault("alerts_rows", 0L);
        if (sevNull > 0) {
            c.add("Alert severity is unusable on " + pct(sevNull, alertRows) + " of alerts ("
                    + fmt(sevFalse) + " rows contain the literal token 'False'); severity-weighted "
                    + "views cover the remainder only.");
        }
        long unack = flags.getOrDefault("alerts_unacknowledged", 0L);
        if (unack > 0) {
            c.add(fmt(unack) + " alerts were never acknowledged. The null acknowledge_time is the "
                    + "signal — those rows are retained and excluded from acknowledgement-time "
                    + "averages rather than counted as instant.");
        }
        long placeholders = flags.getOrDefault("emp_placeholder_stwid", 0L)
                + flags.getOrDefault("alerts_placeholder_stwid", 0L)
                + flags.getOrDefault("feedback_placeholder_stwid", 0L);
        if (placeholders > 0) {
            c.add(fmt(placeholders) + " rows carry stwid = 0, a placeholder rather than a person; "
                    + "they are nulled for per-rider analysis but still counted at trip level.");
        }
        long incomplete = flags.getOrDefault("emp_incomplete_leg", 0L);
        if (incomplete > 0) {
            c.add(fmt(incomplete) + " employee legs have no actual pickup or drop time — these are "
                    + "the non-boarding employees; excluding them would push boarding rates to 100%.");
        }
        long nodalNa = flags.getOrDefault("trip_nodal_na", 0L);
        if (nodalNa > 0) {
            c.add("trip_nodal is absent on " + pct(nodalNa, rows) + " of trips (non-nodal home "
                    + "trips) and is reported as the explicit category 'NA'.");
        }
        return c;
    }

    private void logReport() {
        IngestReport r = report;
        log.info("Data quality: coverage={} confidence={} rowsRead={} rowsKept={} (dropped={})",
                pctOf(r.coverage()), IngestReport.confidenceBand(r.coverage(), r.rowsKept()),
                fmt(r.rowsRead()), fmt(r.rowsKept()), r.dropped());
        log.info("Trips flags: bad_trip_id={} bad_date={} null_delay={} null_actual_end={} "
                        + "null_planned_km={} null_driver_nc={} negative_km={} delay_over_24h={}",
                r.flag("bad_trip_id"), r.flag("bad_date"), r.flag("null_delay"),
                r.flag("null_actual_end"), r.flag("null_planned_km"), r.flag("null_driver_nc"),
                r.flag("negative_km"), r.flag("delay_over_24h"));
        log.info("Cross-relation flags: bill_overhead={} bill_zero_km={} bill_null_slab={} "
                        + "alerts_severity_null={} alerts_unacked={} emp_negative_km={} "
                        + "emp_incomplete_leg={} placeholder_stwid={}",
                r.flag("bill_overhead_rows"), r.flag("bill_zero_km_rows"), r.flag("bill_null_slab"),
                r.flag("alerts_severity_null"), r.flag("alerts_unacknowledged"),
                r.flag("emp_negative_km"), r.flag("emp_incomplete_leg"),
                r.flag("emp_placeholder_stwid") + r.flag("alerts_placeholder_stwid")
                        + r.flag("feedback_placeholder_stwid"));
        log.info("Field coverage on trips: {}", coverageByField);
        for (String caveat : r.caveats()) {
            log.info("  caveat: {}", caveat);
        }
    }

    // ------------------------------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------------------------------

    private Map<String, Object> row(String sql) {
        return db.queryOne(sql).orElseThrow(
                () -> new IllegalStateException("Quality query returned no rows: " + sql));
    }

    private static void putAll(
            Map<String, Long> target, Map<String, Object> source, String... keys) {
        for (String key : keys) {
            target.put(key, asLong(source.get(key)));
        }
    }

    private static long asLong(Object v) {
        if (v == null) {
            return 0L;
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        if (v instanceof BigInteger b) {
            return b.longValueExact();
        }
        return Long.parseLong(v.toString());
    }

    private static double asDouble(Object v) {
        if (v == null) {
            return 0.0;
        }
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        return Double.parseDouble(v.toString());
    }

    private static double share(long numerator, long denominator) {
        return denominator <= 0 ? 0.0 : (double) numerator / denominator;
    }

    private static String pct(long numerator, long denominator) {
        return denominator <= 0 ? "0.0%"
                : String.format(Locale.ROOT, "%.1f%%", 100.0 * numerator / denominator);
    }

    private static String pctOf(double fraction) {
        return String.format(Locale.ROOT, "%.2f%%", 100.0 * fraction);
    }

    private static String fmt(long n) {
        return String.format(Locale.ROOT, "%,d", n);
    }
}
