package com.moveinsync.mi.metric;

import com.moveinsync.mi.metrics.spi.MetricSpec;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * One versioned metric catalog entry, loaded from {@code resources/metrics/<id>.yaml}.
 *
 * <p>This record is the declarative half of "the catalog is the only way to get a number". A metric
 * is a data file, not a query embedded in a service: changing how on-time arrival is defined means
 * editing {@code ota.yaml} and bumping its version, which is a reviewable diff, rather than editing
 * one of several places where the same {@code avg(on_time)} was written by hand and hoping they all
 * moved together.
 *
 * <h2>Why the extra fields</h2>
 *
 * <p>The minimum viable catalog entry is formula plus grain. Everything beyond that exists because
 * this dataset punished its absence:
 *
 * <ul>
 *   <li>{@code filter} — {@code delay_p90} is meaningless unless conditioned on the trip actually
 *       being delayed; 90.2% of trips report NODELAY and drag the unconditioned p90 to zero.
 *   <li>{@code segmentBy} / {@code validSegments} — {@code cost_per_km} is undefined on fixed-rate
 *       contracts, where 42% of bill rows carry zero distance by design. Declaring the guard here
 *       means the metric layer enforces it for every caller instead of trusting each one to
 *       remember.
 *   <li>{@code coverageExpr} — every observation reports what fraction of its rows carried a usable
 *       value, so a number built on holes says so rather than passing as solid.
 *   <li>{@code caveats} — data-quality warnings travel with the metric into the narrative, which is
 *       what turns "94.7%" into "94.7%, on 99.99% coverage, with delay outliers past seven days
 *       retained".
 *   <li>{@code dimensionSql} — the ride extracts call the vendor {@code vendor_id} and the billing
 *       extract calls it {@code vendor}. One logical grain, two physical columns; the mapping lives
 *       in the catalog so the scanner can speak in logical grains throughout.
 * </ul>
 *
 * <h2>Trust boundary</h2>
 *
 * <p>{@code formula}, {@code filter} and {@code coverageExpr} are SQL fragments interpolated into
 * generated queries. They come from version-controlled resources authored by engineers, never from
 * a user, an agent or a request parameter — the same trust level as the code itself. Everything
 * that <em>can</em> come from outside (entity values, periods) is bound as a JDBC parameter by
 * {@code MetricQueryService}. Identifier-shaped fields are additionally regex-validated here so a
 * typo fails at startup rather than at the first query.
 *
 * @param id              stable identifier, e.g. {@code ota}; also the SLA lookup key
 * @param label           human-readable name used in narratives
 * @param description     what the metric means and how to read it
 * @param version         catalog version; bump when the definition changes so narratives can cite it
 * @param sourceView      DuckDB relation to aggregate over, e.g. {@code trips} or {@code bills}
 * @param formula         SQL aggregate expression producing the value
 * @param filter          optional SQL predicate restricting the population, or null
 * @param timeColumn      date column carrying the period, defaults to {@code month}
 * @param direction       {@link MetricSpec#HIGHER_IS_BETTER} or {@link MetricSpec#LOWER_IS_BETTER}
 * @param unit            {@code rate}, {@code minutes} or {@code currency}; drives formatting
 * @param rateMetric      whether the value is a proportion, so deltas are expressed in points
 * @param slaKey          config key under {@code app.} of the governing target, or null
 * @param slaAdvisory     when true the SLA frame is reported but excluded from severity scoring
 * @param industryKey     config key under {@code app.} of the external benchmark, or null
 * @param minSample       smallest slice this metric may report a number on
 * @param grains          logical dimensions this metric may be sliced by, including {@code global}
 * @param dimensionSql    logical grain to physical column overrides; grains default to their own name
 * @param segmentBy       column whose value determines whether the metric is defined at all, or null
 * @param validSegments   values of {@code segmentBy} where the metric is defined
 * @param coverageExpr    SQL count expression for rows carrying a usable value
 * @param caveats         static data-quality warnings carried into every observation
 * @param requiresColumns columns the source view must expose; documents the contract with ingest
 */
public record MetricDefinition(
        String id,
        String label,
        String description,
        int version,
        String sourceView,
        String formula,
        String filter,
        String timeColumn,
        String direction,
        String unit,
        boolean rateMetric,
        String slaKey,
        boolean slaAdvisory,
        String industryKey,
        long minSample,
        List<String> grains,
        Map<String, String> dimensionSql,
        String segmentBy,
        List<String> validSegments,
        String coverageExpr,
        List<String> caveats,
        List<String> requiresColumns) {

    /** Default time column. Every published relation exposes a month-truncated date under this name. */
    public static final String DEFAULT_TIME_COLUMN = "month";

    /** Default coverage expression: every row counts as covered unless the metric says otherwise. */
    public static final String DEFAULT_COVERAGE_EXPR = "count(*)";

    /** Entity label for dimension values that are null in the source. */
    public static final String NULL_ENTITY = "NA";

    /** SQL identifiers this catalog will interpolate. Anything else is rejected at load time. */
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z_][A-Za-z0-9_]*");

    public MetricDefinition {
        grains = grains == null ? List.of() : List.copyOf(grains);
        validSegments = validSegments == null ? List.of() : List.copyOf(validSegments);
        caveats = caveats == null ? List.of() : List.copyOf(caveats);
        requiresColumns = requiresColumns == null ? List.of() : List.copyOf(requiresColumns);
        dimensionSql = dimensionSql == null ? Map.of() : Map.copyOf(dimensionSql);
        timeColumn = blankToNull(timeColumn) == null ? DEFAULT_TIME_COLUMN : timeColumn.trim();
        coverageExpr = blankToNull(coverageExpr) == null ? DEFAULT_COVERAGE_EXPR : coverageExpr.trim();
        direction = blankToNull(direction) == null ? MetricSpec.HIGHER_IS_BETTER : direction.trim();
        unit = blankToNull(unit) == null ? "rate" : unit.trim();
        slaKey = blankToNull(slaKey);
        industryKey = blankToNull(industryKey);
        segmentBy = blankToNull(segmentBy);
        filter = blankToNull(filter);
        version = version <= 0 ? 1 : version;
        minSample = Math.max(1L, minSample);
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }

    /**
     * Fails fast on a malformed catalog entry.
     *
     * <p>Called once per file at startup. A metric that cannot be compiled into SQL should break the
     * boot, not the first agent run at 06:00 — a silently missing metric reads downstream as "nothing
     * to report", which is the most dangerous failure this system has.
     *
     * @throws IllegalStateException with the offending file's metric id in the message
     */
    public void validate() {
        require(id != null && IDENTIFIER.matcher(id).matches(), "id must be a bare identifier, got: " + id);
        require(label != null && !label.isBlank(), "label is required");
        require(sourceView != null && IDENTIFIER.matcher(sourceView).matches(),
                "source_view must be a bare identifier, got: " + sourceView);
        require(formula != null && !formula.isBlank(), "formula is required");
        require(IDENTIFIER.matcher(timeColumn).matches(), "time_column must be a bare identifier");
        require(MetricSpec.HIGHER_IS_BETTER.equals(direction) || MetricSpec.LOWER_IS_BETTER.equals(direction),
                "direction must be higher_is_better or lower_is_better, got: " + direction);
        require(!grains.isEmpty(), "at least one grain is required");
        require(grains.contains(MetricSpec.GLOBAL),
                "grains must include '" + MetricSpec.GLOBAL + "'; every metric needs an un-sliced total");

        for (String grain : grains) {
            require(IDENTIFIER.matcher(grain).matches(), "grain is not an identifier: " + grain);
            require(IDENTIFIER.matcher(column(grain)).matches(),
                    "dimension_sql for grain '" + grain + "' is not an identifier: " + column(grain));
        }
        for (String grain : dimensionSql.keySet()) {
            require(grains.contains(grain), "dimension_sql references unknown grain: " + grain);
        }

        // The segment guard is the whole defence for cost_per_km. A segment_by with no valid values
        // would compile to a predicate that excludes everything and report "no data" forever.
        if (segmentBy != null) {
            require(IDENTIFIER.matcher(segmentBy).matches(), "segment_by must be a bare identifier");
            require(!validSegments.isEmpty(), "segment_by requires a non-empty valid_segments list");
            require(!grains.contains(segmentBy),
                    "segment_by column '" + segmentBy + "' must not also be a grain: slicing by the "
                            + "column that decides whether the metric is defined would emit an "
                            + "out-of-segment row");
        } else {
            require(validSegments.isEmpty(), "valid_segments requires segment_by");
        }
    }

    private void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException("Invalid metric definition '" + id + "': " + message);
        }
    }

    /** Physical column backing a logical grain. Grains map to their own name unless overridden. */
    public String column(String grain) {
        return dimensionSql.getOrDefault(grain, grain);
    }

    /** Whether this metric may be sliced on the given logical grain. */
    public boolean supports(String grain) {
        return grain != null && grains.contains(grain);
    }

    /** True for the pseudo-dimension representing the un-sliced total. */
    public static boolean isGlobal(String grain) {
        return grain == null || grain.isBlank()
                || MetricSpec.GLOBAL.equalsIgnoreCase(grain)
                || MetricSpec.ALL.equalsIgnoreCase(grain);
    }

    /** True when a higher value is the better outcome. */
    public boolean higherIsBetter() {
        return MetricSpec.HIGHER_IS_BETTER.equals(direction);
    }

    /**
     * Whether a movement of this sign is bad news.
     *
     * <p>OTA falling and no-show rate rising are both adverse. The sign alone does not say so, which
     * is exactly why direction is declared in the catalog rather than guessed downstream.
     */
    public boolean isAdverse(double delta) {
        return higherIsBetter() ? delta < 0 : delta > 0;
    }

    /** Every grain except {@code global}, in catalog order. */
    public List<String> sliceableGrains() {
        return grains.stream().filter(g -> !isGlobal(g)).toList();
    }

    /** The narrow projection the anomaly scanner and attribution engine consume. */
    public MetricSpec toSpec() {
        return new MetricSpec(id, label, grains, direction, slaKey, minSample, rateMetric, version);
    }

    /** Fully-qualified config key of the SLA target, e.g. {@code app.sla.ota}, or null. */
    public String slaPropertyKey() {
        return slaKey == null ? null : "app." + slaKey;
    }

    /** Fully-qualified config key of the industry benchmark, e.g. {@code app.industry.ota}, or null. */
    public String industryPropertyKey() {
        return industryKey == null ? null : "app." + industryKey;
    }

    /** Short one-line form for logs and error messages. */
    public String summary() {
        return "%s v%d [%s over %s, min_sample=%d, grains=%d]"
                .formatted(id, version, direction.toLowerCase(Locale.ROOT), sourceView, minSample, grains.size());
    }

    /** Ordered copy of the grain-to-column mapping actually in force, for diagnostics. */
    public Map<String, String> resolvedDimensions() {
        Map<String, String> resolved = new LinkedHashMap<>();
        for (String grain : sliceableGrains()) {
            resolved.put(grain, column(grain));
        }
        return resolved;
    }
}
