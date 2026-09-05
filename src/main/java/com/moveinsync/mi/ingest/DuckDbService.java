package com.moveinsync.mi.ingest;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Owns the single in-process DuckDB instance and the five typed relations the whole platform reads
 * from: {@code trips}, {@code bills}, {@code alerts}, {@code emp}, {@code feedback}.
 *
 * <h2>Why every column is parsed defensively</h2>
 *
 * The raw extracts are dirty in fifteen specific, reproducible ways. Each one is handled here at the
 * ingest boundary so that no downstream component ever has to think about it again. The numbered
 * references in the SQL comments below map to that list:
 *
 * <ol>
 *   <li><b>Comma-formatted trip ids.</b> {@code "1,097,076"} in ride / alerts / feedback, plain
 *       {@code 1123974} in bill, clean int64 in emp. Every relation applies
 *       {@code TRY_CAST(replace(trip_id, ',', '') AS BIGINT)} so the join key is one type everywhere.
 *   <li><b>{@code 'OverHead'} in {@code bill_data.trip_id}.</b> 160 rows carry the literal string
 *       instead of an id — a plain {@code CAST} aborts the whole scan. {@code TRY_CAST} is therefore
 *       mandatory, and the rows survive as {@code is_overhead = true} with a null trip id.
 *   <li><b>{@code stwid = 0} is a placeholder,</b> not an employee (22,165 alert rows, 1,414 emp
 *       rows). Nulled out via {@code nullif(..., 0)} and flagged as {@code stwid_placeholder} so
 *       per-rider analysis can exclude it without losing the row.
 *   <li><b>Four different date formats,</b> one per file — parsed per file, never globally:
 *       ride {@code %B %d, %Y}; emp ISO {@code 2026-07-09}; alerts / bill / feedback
 *       {@code %B %d, %Y, %I:%M %p}.
 *   <li><b>Epoch columns</b> are comma-strings in ride ({@code "1,782,864,900"}) and floats in emp
 *       ({@code 1783633500.0}) — ride strips commas, emp casts through DOUBLE before BIGINT.
 *   <li><b>Schema drift across the three monthly ride files</b> ({@code is_driver_nc} /
 *       {@code is_cab_nc} boolean in Jun-Jul but object+nulls in May; {@code planned_km} float in
 *       May-Jun, object in July). Read with {@code all_varchar=true} + {@code union_by_name=true},
 *       then {@code TRY_CAST} every single column.
 *   <li><b>Negative kilometres in emp</b> (down to -6.63, physically impossible) — kept and flagged
 *       as {@code km_negative}, never silently repaired.
 *   <li><b>{@code alerts_data.severity} carries a stray literal {@code "False"}</b> (15,037 rows)
 *       plus {@code "NA"} (16,348) among the real Sev-1/2/3 values. Both map to NULL; the original
 *       is preserved in {@code severity_raw}.
 *   <li><b>{@code trip_cost} and {@code delay_minutes} are comma-formatted strings</b> — commas
 *       stripped before any arithmetic.
 *   <li><b>Nulls are meaningful, not errors</b> (unacknowledged alert, non-boarding employee,
 *       incomplete leg). <b>No view has a WHERE clause.</b> Row counts in equal row counts out; the
 *       invariant is asserted at startup and again by {@link IngestReport#validate()}.
 *   <li><b>{@code delay_minutes} outliers to 10,644</b> (&gt; 7 days) — retained, flagged by
 *       {@link QualityFlagger} as {@code delay_over_24h}.
 *   <li><b>{@code bill_data.total_trip_km = 0} on ~40% of rows is not missing data</b> — it is
 *       fixed-rate contracting. {@code billing_regime} separates FIXED_RATE from DISTANCE_BASED and
 *       {@code cost_per_km} is computed <em>only</em> for distance-based rows with positive km.
 *   <li><b>{@code bill_data.slab_name} is ~20% null</b> — and the null arrives as the literal
 *       four-character string {@code "null"} (121,111 rows), which would otherwise pass straight
 *       through as a real category. Normalised to SQL NULL.
 *   <li><b>Tiny segments lie.</b> Not fixed here (that is the scanner's volume gate) but the row
 *       counts this class publishes are what the gate is applied against.
 *   <li><b>{@code trip_nodal} is null for non-nodal home trips</b> — expected, coalesced to
 *       {@code 'NA'}.
 * </ol>
 *
 * <h2>Views vs tables</h2>
 *
 * Each dataset produces three catalog objects: {@code <name>_raw} (the untouched CSV reader, used
 * only to count rows read), {@code <name>_src} (the parsing view — this is the SQL of record), and
 * {@code <name>} itself. With {@code app.data.materialize=true} (the default) {@code <name>} is a
 * table filled from {@code <name>_src}, so the 580 MB of CSV is parsed once at startup (~15 s)
 * instead of on every one of the several hundred queries the scanner issues. Set it to
 * {@code false} to keep {@code <name>} as a lazy view.
 *
 * <h2>Concurrency</h2>
 *
 * A DuckDB JDBC {@link Connection} is not safe for concurrent statements, so every execution is
 * serialised on a monitor. This costs nothing in practice: DuckDB parallelises each individual query
 * across all cores internally, which is the throughput that actually matters here.
 */
@Service
public class DuckDbService {

    private static final Logger log = LoggerFactory.getLogger(DuckDbService.class);

    /** The five relations published to the rest of the application, in dependency-free order. */
    public static final List<String> RELATIONS = List.of("trips", "bills", "alerts", "emp", "feedback");

    /** Guards {@link #count(String)} against identifier injection. */
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z_][A-Za-z0-9_]{0,62}");

    private final Path rawPath;
    private final boolean materialize;

    /** Serialises statement execution on the single connection. */
    private final Object lock = new Object();

    private final Map<String, Long> rowsRead = new LinkedHashMap<>();
    private final Map<String, Long> rowsKept = new LinkedHashMap<>();

    private volatile Connection connection;
    private volatile boolean ready;

    public DuckDbService(
            @Value("${app.data.raw-path:./data/raw}") String rawPath,
            @Value("${app.data.materialize:true}") boolean materialize) {
        this.rawPath = Paths.get(rawPath).toAbsolutePath().normalize();
        this.materialize = materialize;
    }

    // ------------------------------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------------------------------

    @PostConstruct
    public void createViews() {
        long t0 = System.currentTimeMillis();
        verifyRawDirectory();
        try {
            // JDBC 4 service discovery normally finds the driver; force it in case of an exotic
            // classloader so the failure is a clear message rather than "No suitable driver".
            try {
                Class.forName("org.duckdb.DuckDBDriver");
            } catch (ClassNotFoundException ignored) {
                // fall through to DriverManager
            }
            connection = DriverManager.getConnection("jdbc:duckdb:");
            log.info("DuckDB in-memory instance opened; raw data at {}", rawPath);

            // Give large spills somewhere to go rather than failing the run outright.
            execute("SET temp_directory = " + quote(
                    Paths.get(System.getProperty("java.io.tmpdir", "/tmp"), "duckdb-mi").toString()));

            defineRelation("trips", rideSource(), tripsSrcDdl());
            defineRelation("bills", billSource(), billsSrcDdl());
            defineRelation("alerts", alertSource(), alertsSrcDdl());
            defineRelation("emp", empSource(), empSrcDdl());
            defineRelation("feedback", feedbackSource(), feedbackSrcDdl());

            ready = true;
        } catch (SQLException e) {
            throw new IllegalStateException("Failed to open DuckDB / build ingest views", e);
        }

        logRelationSummary(System.currentTimeMillis() - t0);
    }

    @PreDestroy
    public void close() {
        ready = false;
        synchronized (lock) {
            if (connection != null) {
                try {
                    connection.close();
                } catch (SQLException e) {
                    log.warn("DuckDB connection did not close cleanly: {}", e.getMessage());
                }
                connection = null;
            }
        }
    }

    private void verifyRawDirectory() {
        if (!Files.isDirectory(rawPath)) {
            throw new IllegalStateException(
                    "Raw data directory not found: " + rawPath
                            + " (set app.data.raw-path to the folder holding the CSV extracts)");
        }
        // The monthly ride filenames contain a space ("Ride_data _trip-may_2026.csv"), which is why
        // everything downstream globs on Ride_data*.csv instead of naming the files.
        long rideFiles;
        try (Stream<Path> files = Files.list(rawPath)) {
            rideFiles = files.map(p -> p.getFileName().toString())
                    .filter(n -> n.startsWith("Ride_data") && n.endsWith(".csv"))
                    .count();
        } catch (Exception e) {
            throw new IllegalStateException("Cannot list raw data directory " + rawPath, e);
        }
        if (rideFiles == 0) {
            throw new IllegalStateException("No Ride_data*.csv files found under " + rawPath);
        }
        log.info("Found {} ride extract(s) matching Ride_data*.csv under {}", rideFiles, rawPath);
    }

    /**
     * Builds the three catalog objects for one dataset and records the row-count invariant.
     *
     * @param name       published relation name
     * @param csvReader  the bare {@code read_csv(...)} expression
     * @param srcDdl     the {@code CREATE OR REPLACE VIEW <name>_src} statement
     */
    private void defineRelation(String name, String csvReader, String srcDdl) throws SQLException {
        long t0 = System.currentTimeMillis();

        execute("CREATE OR REPLACE VIEW " + name + "_raw AS SELECT * FROM " + csvReader);
        execute(srcDdl);

        if (materialize) {
            execute("DROP VIEW IF EXISTS " + name);
            execute("CREATE OR REPLACE TABLE " + name + " AS SELECT * FROM " + name + "_src");
        } else {
            execute("DROP TABLE IF EXISTS " + name);
            execute("CREATE OR REPLACE VIEW " + name + " AS SELECT * FROM " + name + "_src");
        }

        long read = scalarLong("SELECT count(*) FROM " + name + "_raw");
        long kept = scalarLong("SELECT count(*) FROM " + name);
        rowsRead.put(name, read);
        rowsKept.put(name, kept);

        // Edge case 10: nulls are flagged, never filtered. No view carries a WHERE clause, so this
        // must hold. If it ever does not, a predicate has crept in and the run is not trustworthy.
        if (read != kept) {
            throw new IllegalStateException(
                    "Ingest dropped rows for relation '" + name + "': read=" + read + " kept=" + kept
                            + ". Views must never filter — nulls are meaningful, not errors.");
        }

        log.info("  {} rows={} ({} ms)", padRight(name, 8), kept, System.currentTimeMillis() - t0);
    }

    private void logRelationSummary(long elapsedMs) {
        long total = 0L;
        for (Long kept : rowsKept.values()) {
            total += kept;
        }
        log.info("Ingest complete in {} ms — {} as {}", elapsedMs, RELATIONS,
                materialize ? "materialised tables" : "lazy views");
        log.info("Row counts: trips={} bills={} alerts={} emp={} feedback={} (total {}; "
                        + "rowsKept == rowsRead for every relation — no row is ever filtered)",
                rowsKept.get("trips"), rowsKept.get("bills"), rowsKept.get("alerts"),
                rowsKept.get("emp"), rowsKept.get("feedback"), total);
        queryOne("SELECT memory_usage FROM pragma_database_size()")
                .map(r -> r.get("memory_usage"))
                .ifPresent(m -> log.info("DuckDB resident memory: {}", m));
    }

    // ------------------------------------------------------------------------------------------
    // Relation DDL — one method per dataset, each documenting the edge cases it absorbs
    // ------------------------------------------------------------------------------------------

    /** {@code read_csv(...)} over one glob. Everything is read as VARCHAR then TRY_CAST (edge 6). */
    private String source(String glob, boolean unionByName) {
        return "read_csv(" + quote(rawPath.resolve(glob).toString()) + ", header=true"
                + (unionByName ? ", union_by_name=true" : "")
                + ", null_padding=true, ignore_errors=true, all_varchar=true, sample_size=-1)";
    }

    /** Note the SPACE in "Ride_data _trip-may_2026.csv" — hence the glob rather than three names. */
    private String rideSource() {
        return source("Ride_data*.csv", true);
    }

    private String billSource() {
        return source("bill_data.csv", false);
    }

    private String alertSource() {
        return source("alerts_data.csv", false);
    }

    private String empSource() {
        return source("emp_Data.csv", false);
    }

    private String feedbackSource() {
        return source("trip_feedback.csv", false);
    }

    /**
     * Ride trips. Verified against the reference figures: 615,546 rows, on-time arrival
     * 95.31% (May) / 92.46% (June) / 94.69% (July), delay_reason share NODELAY 90.2 / TRAFFIC 3.8 /
     * EMPLOYEE 3.3 / DRIVER 2.7.
     *
     * <p>Edge cases 1 (comma trip ids), 4 (ride dates are {@code %B %d, %Y}), 5 (comma epochs),
     * 6 (schema drift — every column TRY_CAST), 9 (comma-formatted delay_minutes), 15 (null
     * trip_nodal means a non-nodal home trip, coalesced to 'NA').
     */
    private String tripsSrcDdl() {
        return """
                CREATE OR REPLACE VIEW trips_src AS
                SELECT
                    TRY_CAST(replace(trip_id, ',', '') AS BIGINT)            AS trip_id,
                    business_unit, office, product_type, vendor_id, trip_direction, shift_type,
                    coalesce(trip_nodal,'NA') AS trip_nodal, delay_reason,
                    actual_cab_fuel_type, route_source,
                    strptime(trip_date, '%B %d, %Y')::DATE                   AS trip_date,
                    date_trunc('month', strptime(trip_date, '%B %d, %Y'))::DATE AS month,
                    TRY_CAST(replace(delay_minutes, ',', '') AS DOUBLE)      AS delay_minutes,
                    TRY_CAST(replace(planned_end_epoch, ',', '') AS BIGINT)  AS planned_end_epoch,
                    TRY_CAST(replace(actual_end_epoch,  ',', '') AS BIGINT)  AS actual_end_epoch,
                    TRY_CAST(planned_km  AS DOUBLE)                          AS planned_km,
                    TRY_CAST(traveled_km AS DOUBLE)                          AS traveled_km,
                    TRY_CAST(actual_escort AS BOOLEAN)                       AS actual_escort,
                    TRY_CAST(is_driver_nc AS BOOLEAN)                        AS is_driver_nc,
                    TRY_CAST(is_cab_nc    AS BOOLEAN)                        AS is_cab_nc,
                    TRY_CAST(actual_cab_capacity AS INT)                     AS cab_capacity,
                    TRY_CAST(plannedemployee_cnt AS INT)                     AS emp_planned,
                    TRY_CAST(actualemployee_cnt  AS INT)                     AS emp_actual,
                    TRY_CAST(noshow_cnt AS INT)                              AS noshow,
                    CASE WHEN TRY_CAST(replace(delay_minutes,',','') AS DOUBLE) <= 5
                         THEN 1 ELSE 0 END                                   AS on_time
                FROM {{RIDE}}
                """.replace("{{RIDE}}", rideSource());
    }

    /**
     * Billing lines. 620,942 rows; average trip cost 1331 (May) / 1340 (June) / 1356 (July).
     *
     * <p>Edge case 2: 160 rows have {@code trip_id = 'OverHead'}. A plain CAST kills the query, so
     * TRY_CAST nulls the id and {@code is_overhead} marks the row — these are real charges and must
     * stay in the cost totals even though they join to no trip.
     *
     * <p>Edge case 12: {@code total_trip_km = 0} on ~40% of rows is the contract design, not a gap.
     * 4S-HYD / 6S-HYD are 100% zero, 4S-EV-Z 99.8%, *-ORRNEW 99.7%, and the Short/Medium/Long slabs
     * ~98%; the distance contracts (4Seater, 6Seater, Slab1/2/3, Zone_A/B/C) are 0% zero.
     * {@code cost_per_km} is therefore left NULL for FIXED_RATE rows — dividing by zero km there
     * would manufacture an infinite unit cost out of a perfectly normal fixed fee.
     *
     * <p>Edge cases 4 ({@code %B %d, %Y, %I:%M %p} cycle dates), 9 (comma-formatted trip_cost),
     * 13 (slab_name null ~20%, arriving as the literal string "null").
     */
    private String billsSrcDdl() {
        return """
                CREATE OR REPLACE VIEW bills_src AS
                SELECT *,
                    -- Unit cost is defined ONLY where distance is what is being billed. On a
                    -- fixed-rate line total_trip_km = 0 by design, so this stays NULL rather than
                    -- inventing an infinite cost per km out of a perfectly normal flat fee.
                    CASE WHEN billing_regime = 'DISTANCE_BASED'
                              AND total_trip_km > 0 AND trip_cost IS NOT NULL
                         THEN trip_cost / total_trip_km END                   AS cost_per_km,
                    (total_trip_km = 0)                                       AS zero_km
                FROM (
                    SELECT *,
                        CASE WHEN contract ILIKE '%HYD%' OR contract ILIKE '%ORRNEW%'
                                  OR contract ILIKE '%EV-Z%'
                                  OR slab_name IN ('Short','Medium','Long')
                             THEN 'FIXED_RATE' ELSE 'DISTANCE_BASED' END      AS billing_regime
                    FROM (
                    SELECT
                        TRY_CAST(replace(trip_id, ',', '') AS BIGINT)          AS trip_id,
                        trip_id                                               AS trip_id_raw,
                        (TRY_CAST(replace(trip_id, ',', '') AS BIGINT) IS NULL) AS is_overhead,
                        business_unit, office, vendor,
                        nullif(nullif(trim(contract),  'null'), '')           AS contract,
                        nullif(nullif(trim(slab_name), 'null'), '')           AS slab_name,
                        try_strptime(cycle_start, '%B %d, %Y, %I:%M %p')::DATE AS cycle_start,
                        try_strptime(cycle_end,   '%B %d, %Y, %I:%M %p')::DATE AS cycle_end,
                        date_trunc('month',
                            try_strptime(cycle_start, '%B %d, %Y, %I:%M %p'))::DATE AS month,
                        TRY_CAST(replace(total_trip_km, ',', '') AS DOUBLE)    AS total_trip_km,
                        TRY_CAST(replace(trip_cost,     ',', '') AS DOUBLE)    AS trip_cost
                    FROM {{BILL}}
                    )
                )
                """.replace("{{BILL}}", billSource());
    }

    /**
     * Device / safety alerts. 51,699 rows. Reference signal:
     * EMPLOYEE_SIGN_OFF_TIME_VIOLATION collapses 7,670 (May) to 46 (June) to 20 (July), -99.7%.
     *
     * <p>Edge case 8: {@code severity} holds a stray literal {@code "False"} (15,037 rows) and
     * {@code "NA"} (16,348) alongside Sev-1/2/3. Both become NULL in {@code severity}; the raw token
     * is kept in {@code severity_raw} so the corruption is auditable rather than erased.
     *
     * <p>Edge case 10: a null {@code acknowledge_time} (54 rows) is an unacknowledged alert — a
     * finding, not a defect. Surfaced as {@code unacknowledged}, with {@code ack_minutes} left null.
     *
     * <p>Edge cases 1 (comma trip ids), 3 (stwid = 0 placeholder on 22,165 rows),
     * 4 ({@code %B %d, %Y, %I:%M %p}).
     */
    private String alertsSrcDdl() {
        return """
                CREATE OR REPLACE VIEW alerts_src AS
                SELECT *,
                    CASE WHEN start_time IS NULL OR acknowledge_time IS NULL THEN NULL
                         ELSE date_diff('minute', start_time, acknowledge_time) END AS ack_minutes,
                    (acknowledge_time IS NULL)                                AS unacknowledged
                FROM (
                    SELECT
                        TRY_CAST(replace(trip_id, ',', '') AS BIGINT)          AS trip_id,
                        business_unit, event_id, event_type, state_text, source,
                        nullif(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) AS stwid,
                        (coalesce(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) = 0)
                                                                              AS stwid_placeholder,
                        CASE WHEN upper(trim(severity)) IN ('SEV-1','SEV-2','SEV-3')
                             THEN trim(severity) END                          AS severity,
                        severity                                              AS severity_raw,
                        try_strptime(start_time,       '%B %d, %Y, %I:%M %p') AS start_time,
                        try_strptime(acknowledge_time, '%B %d, %Y, %I:%M %p') AS acknowledge_time,
                        try_strptime(start_time, '%B %d, %Y, %I:%M %p')::DATE AS alert_date,
                        date_trunc('month',
                            try_strptime(start_time, '%B %d, %Y, %I:%M %p'))::DATE AS month
                    FROM {{ALERTS}}
                )
                """.replace("{{ALERTS}}", alertSource());
    }

    /**
     * Per-employee legs. 1,637,906 rows.
     *
     * <p>Edge case 7: {@code planned_km} / {@code traveled_km} go negative (48 rows, down to
     * -6.63) — physically impossible. The rows are kept and flagged {@code km_negative}; deleting
     * them would quietly change every distance aggregate.
     *
     * <p>Edge case 5: epochs arrive as floats ({@code 1783633500.0}) so they are cast through
     * DOUBLE before BIGINT — a direct BIGINT cast of "1783633500.0" yields NULL.
     *
     * <p>Edge case 10: 190,009 rows have null pickup/drop epochs and a null {@code signintype} —
     * every one of them is a "Not Boarded" employee. That null is the signal.
     *
     * <p>Edge cases 3 (stwid = 0 on 1,414 rows), 4 (emp dates are plain ISO, unlike every other
     * file).
     */
    private String empSrcDdl() {
        return """
                CREATE OR REPLACE VIEW emp_src AS
                SELECT *,
                    (coalesce(planned_km, 0) < 0 OR coalesce(traveled_km, 0) < 0) AS km_negative,
                    (actual_pickup_epoch IS NULL OR actual_drop_epoch IS NULL)    AS incomplete_leg
                FROM (
                    SELECT
                        TRY_CAST(replace(trip_id, ',', '') AS BIGINT)          AS trip_id,
                        business_unit, office, product_type, shift_type,
                        TRY_CAST(trip_date AS DATE)                            AS trip_date,
                        date_trunc('month', TRY_CAST(trip_date AS DATE))::DATE AS month,
                        nullif(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) AS stwid,
                        (coalesce(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) = 0)
                                                                              AS stwid_placeholder,
                        TRY_CAST(TRY_CAST(replace(planned_pickup_epoch, ',', '') AS DOUBLE) AS BIGINT)
                                                                              AS planned_pickup_epoch,
                        TRY_CAST(TRY_CAST(replace(planned_drop_epoch,   ',', '') AS DOUBLE) AS BIGINT)
                                                                              AS planned_drop_epoch,
                        TRY_CAST(TRY_CAST(replace(actual_pickup_epoch,  ',', '') AS DOUBLE) AS BIGINT)
                                                                              AS actual_pickup_epoch,
                        TRY_CAST(TRY_CAST(replace(actual_drop_epoch,    ',', '') AS DOUBLE) AS BIGINT)
                                                                              AS actual_drop_epoch,
                        TRY_CAST(replace(planned_km,  ',', '') AS DOUBLE)      AS planned_km,
                        TRY_CAST(replace(traveled_km, ',', '') AS DOUBLE)      AS traveled_km,
                        signintype, gender, emp_role, boarding_status,
                        nullif(trim(not_boarding_reason), '')                  AS not_boarding_reason,
                        TRY_CAST(is_no_show AS BOOLEAN)                        AS is_no_show,
                        (boarding_status = 'Boarded')                          AS boarded
                    FROM {{EMP}}
                )
                """.replace("{{EMP}}", empSource());
    }

    /**
     * Rider feedback. 512,873 rows.
     *
     * <p>Edge case 4: {@code trip_date} here is a timestamp ({@code "June 3, 2026, 11:00 AM"}),
     * not the bare date used in the ride files — parsed with the timestamp pattern then truncated.
     *
     * <p>Edge case 10: a rating of {@code 0} is "not rated", not a zero-star score — most visibly
     * {@code marshal_rating}, which is 0 on 473,692 of 512,873 rows because most trips carry no
     * marshal. Left as NULL so averages are taken over ratings that were actually given;
     * {@code avg_rating} likewise averages only the non-null components.
     *
     * <p>Edge cases 1 (comma trip ids), 3 (stwid also comma-formatted here: {@code "149,530"}).
     */
    private String feedbackSrcDdl() {
        return """
                CREATE OR REPLACE VIEW feedback_src AS
                SELECT *,
                    (coalesce(route_rating,0) + coalesce(driver_rating,0)
                     + coalesce(cab_rating,0) + coalesce(safety_rating,0))
                    / nullif(
                        (CASE WHEN route_rating  IS NULL THEN 0 ELSE 1 END)
                      + (CASE WHEN driver_rating IS NULL THEN 0 ELSE 1 END)
                      + (CASE WHEN cab_rating    IS NULL THEN 0 ELSE 1 END)
                      + (CASE WHEN safety_rating IS NULL THEN 0 ELSE 1 END), 0)  AS avg_rating
                FROM (
                    SELECT
                        TRY_CAST(replace(trip_id, ',', '') AS BIGINT)          AS trip_id,
                        business_unit, trip_type,
                        nullif(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) AS stwid,
                        (coalesce(TRY_CAST(replace(stwid, ',', '') AS BIGINT), 0) = 0)
                                                                              AS stwid_placeholder,
                        try_strptime(trip_date, '%B %d, %Y, %I:%M %p')::DATE   AS trip_date,
                        date_trunc('month',
                            try_strptime(trip_date, '%B %d, %Y, %I:%M %p'))::DATE AS month,
                        try_strptime(creation_time, '%B %d, %Y, %I:%M %p')     AS creation_time,
                        nullif(TRY_CAST(route_rating   AS INT), 0)             AS route_rating,
                        nullif(TRY_CAST(driver_rating  AS INT), 0)             AS driver_rating,
                        nullif(TRY_CAST(cab_rating     AS INT), 0)             AS cab_rating,
                        nullif(TRY_CAST(safety_rating  AS INT), 0)             AS safety_rating,
                        nullif(TRY_CAST(marshal_rating AS INT), 0)             AS marshal_rating
                    FROM {{FEEDBACK}}
                )
                """.replace("{{FEEDBACK}}", feedbackSource());
    }

    // ------------------------------------------------------------------------------------------
    // Query API
    // ------------------------------------------------------------------------------------------

    /**
     * Runs a read query and materialises every row as an ordered column-name to value map.
     *
     * <p>Null values are preserved in the maps — {@link LinkedHashMap} is used precisely because
     * {@code Map.of} / {@code Map.copyOf} reject nulls, and in this dataset a null is information.
     */
    public List<Map<String, Object>> query(String sql) {
        return query(sql, List.of());
    }

    /**
     * Parameterised variant. Use this whenever a value comes from the data itself — office names
     * ({@code "Denver Office"}), vendor names and business units all contain characters that make
     * hand-built SQL literals a hazard.
     */
    public List<Map<String, Object>> query(String sql, List<?> params) {
        requireReady();
        synchronized (lock) {
            try (PreparedStatement ps = connection.prepareStatement(sql)) {
                for (int i = 0; i < params.size(); i++) {
                    ps.setObject(i + 1, params.get(i));
                }
                try (ResultSet rs = ps.executeQuery()) {
                    return readAll(rs);
                }
            } catch (SQLException e) {
                throw new DuckDbQueryException(sql, e);
            }
        }
    }

    /** First row of the result, or empty when the query matched nothing. */
    public Optional<Map<String, Object>> queryOne(String sql) {
        return queryOne(sql, List.of());
    }

    public Optional<Map<String, Object>> queryOne(String sql, List<?> params) {
        List<Map<String, Object>> rows = query(sql, params);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    /** Row count of a published relation. The name is whitelisted, never interpolated blindly. */
    public long count(String view) {
        if (view == null || !IDENTIFIER.matcher(view).matches()) {
            throw new IllegalArgumentException("Not a legal relation name: " + view);
        }
        requireReady();
        return scalarLong("SELECT count(*) FROM " + view);
    }

    /** Executes DDL / SET statements. Exposed so tests can stage fixture relations. */
    public void execute(String sql) {
        Connection c = this.connection;
        if (c == null) {
            throw new IllegalStateException("DuckDB connection is not open");
        }
        synchronized (lock) {
            try (Statement st = c.createStatement()) {
                st.execute(sql);
            } catch (SQLException e) {
                throw new DuckDbQueryException(sql, e);
            }
        }
    }

    /** Rows read out of the CSV files, per relation. */
    public Map<String, Long> rowsRead() {
        return Collections.unmodifiableMap(new LinkedHashMap<>(rowsRead));
    }

    /** Rows published, per relation. Equal to {@link #rowsRead()} by construction — nothing drops. */
    public Map<String, Long> rowsKept() {
        return Collections.unmodifiableMap(new LinkedHashMap<>(rowsKept));
    }

    public Path rawPath() {
        return rawPath;
    }

    public boolean isReady() {
        return ready;
    }

    /** Single-quotes a SQL string literal, doubling any embedded quote. */
    public static String quote(String literal) {
        return "'" + literal.replace("'", "''") + "'";
    }

    // ------------------------------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------------------------------

    private long scalarLong(String sql) {
        Connection c = this.connection;
        if (c == null) {
            throw new IllegalStateException("DuckDB connection is not open");
        }
        synchronized (lock) {
            try (Statement st = c.createStatement(); ResultSet rs = st.executeQuery(sql)) {
                return rs.next() ? rs.getLong(1) : 0L;
            } catch (SQLException e) {
                throw new DuckDbQueryException(sql, e);
            }
        }
    }

    private static List<Map<String, Object>> readAll(ResultSet rs) throws SQLException {
        ResultSetMetaData md = rs.getMetaData();
        int cols = md.getColumnCount();
        String[] labels = new String[cols + 1];
        for (int i = 1; i <= cols; i++) {
            labels[i] = md.getColumnLabel(i).toLowerCase(Locale.ROOT);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        while (rs.next()) {
            Map<String, Object> row = new LinkedHashMap<>(Math.max(4, cols * 2));
            for (int i = 1; i <= cols; i++) {
                row.put(labels[i], normalise(rs.getObject(i)));
            }
            out.add(row);
        }
        return out;
    }

    /** Maps JDBC temporal / hugeint types onto types Jackson and the rest of the app understand. */
    private static Object normalise(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof java.sql.Date d) {
            return d.toLocalDate();
        }
        if (v instanceof java.sql.Timestamp t) {
            return t.toLocalDateTime();
        }
        if (v instanceof java.sql.Time t) {
            return t.toLocalTime();
        }
        if (v instanceof BigInteger b) {
            return b.longValueExact();
        }
        return v;
    }

    private void requireReady() {
        if (!ready || connection == null) {
            throw new IllegalStateException(
                    "DuckDbService is not initialised — createViews() has not completed");
        }
    }

    private static String padRight(String s, int width) {
        return s.length() >= width ? s : s + " ".repeat(width - s.length());
    }

    /** Carries the offending SQL, which is what you actually need when a DuckDB cast blows up. */
    public static class DuckDbQueryException extends RuntimeException {
        private final String sql;

        DuckDbQueryException(String sql, Throwable cause) {
            super("DuckDB statement failed: " + abbreviate(sql) + " — " + cause.getMessage(), cause);
            this.sql = sql;
        }

        public String sql() {
            return sql;
        }

        private static String abbreviate(String sql) {
            String flat = sql.replaceAll("\\s+", " ").trim();
            return flat.length() <= 400 ? flat : flat.substring(0, 400) + " ...";
        }
    }
}
