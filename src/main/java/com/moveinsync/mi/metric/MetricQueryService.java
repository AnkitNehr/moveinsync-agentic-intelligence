package com.moveinsync.mi.metric;

import com.moveinsync.mi.ingest.DuckDbService;
import com.moveinsync.mi.metrics.spi.MetricCatalogPort;
import com.moveinsync.mi.metrics.spi.MetricSeriesPort;
import com.moveinsync.mi.metrics.spi.MetricSlice;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalDouble;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * The semantic layer: the only path from a metric id to a number.
 *
 * <p>Compiles a {@link MetricDefinition} plus a grain, an entity and a period into SQL, runs it
 * against the DuckDB fact store, and returns the value with the sample size behind it. Every other
 * component — the anomaly scanner, the attribution engine, the agent tool surface, the console, the
 * chat endpoint — asks this class. None of them writes SQL, and none of them can, because the only
 * things this API accepts are catalog-known identifiers and period labels.
 *
 * <h2>The volume gate is enforced here, not requested here</h2>
 *
 * <p>Below a metric's {@code min_sample} this service returns a null value and the true row count.
 * It never returns a number it does not trust, and callers cannot opt out. That is deliberate: the
 * SHUTTLE nodal segment has 244 trips across the whole quarter and swings 26.6 points, and SPOT_2.0
 * has 702. Both are noise, both look spectacular, and both would have reached a human as the top
 * finding of the day. A gate that any caller could bypass would eventually be bypassed.
 *
 * <h2>Injection safety</h2>
 *
 * <p>Two classes of input, two treatments. Identifiers — view names, dimension columns, aggregate
 * expressions — come from the version-controlled YAML catalog and are validated as bare identifiers
 * at load time; they are interpolated. Values — entity names like {@code "Denver Office"}, period
 * labels, segment values — can originate from data or from an agent, and are always bound as JDBC
 * parameters. Period labels are additionally regex-checked before they are used at all.
 *
 * @see MetricCatalog for where definitions come from
 * @see com.moveinsync.mi.benchmark.BenchmarkService for the reference frames layered on top
 */
@Service
public class MetricQueryService implements MetricCatalogPort, MetricSeriesPort {

    private static final Logger log = LoggerFactory.getLogger(MetricQueryService.class);

    /** Period label format. Everything in this system is monthly at present. */
    public static final DateTimeFormatter PERIOD_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM");

    /** Confidence band for a slice suppressed by the volume gate. Never carries a value. */
    public static final String CONFIDENCE_INSUFFICIENT_SAMPLE = "insufficient_sample";

    /**
     * Confidence band for a slice with adequate rows whose formula still produced no value — an
     * all-null denominator, or a cost-per-km segment with zero total distance. Distinct from
     * {@link #CONFIDENCE_INSUFFICIENT_SAMPLE} because the remedy is different: one needs more data,
     * the other needs a different question.
     */
    public static final String CONFIDENCE_NOT_COMPUTABLE = "not_computable";

    public static final String CONFIDENCE_HIGH = "HIGH";
    public static final String CONFIDENCE_MEDIUM = "MEDIUM";
    public static final String CONFIDENCE_LOW = "LOW";

    /** Coverage at or above which a value is treated as fully supported by its rows. */
    private static final double COVERAGE_HIGH = 0.98;

    /** Coverage below which a value is explicitly caveated in every narrative that cites it. */
    private static final double COVERAGE_MEDIUM = 0.90;

    /** Sample multiple of {@code min_sample} required for HIGH confidence. */
    private static final long HIGH_CONFIDENCE_SAMPLE_MULTIPLE = 4L;

    private final MetricCatalog catalog;
    private final DuckDbService duckDb;
    private final AtomicBoolean warnedNotReady = new AtomicBoolean();

    public MetricQueryService(MetricCatalog catalog, DuckDbService duckDb) {
        this.catalog = catalog;
        this.duckDb = duckDb;
    }

    // ---- MetricCatalogPort ----------------------------------------------------------------------

    @Override
    public List<MetricSpec> metrics() {
        return catalog.specs();
    }

    @Override
    public Optional<MetricSpec> find(String metricId) {
        return catalog.find(metricId).map(MetricDefinition::toSpec);
    }

    /** The full definition, for callers inside the metric layer that need the formula itself. */
    public MetricCatalog catalog() {
        return catalog;
    }

    // ---- MetricSeriesPort -----------------------------------------------------------------------

    /**
     * Every entity slice for one metric on one dimension in one period.
     *
     * <p>Under-sampled entities are returned with a null value and their true row count rather than
     * being dropped. The attribution engine needs their volume to weight the mix effect correctly
     * even when it may not quote their rate, and a caller that silently never saw them would compute
     * shares against an incomplete denominator.
     */
    @Override
    public List<MetricSlice> slices(String metricId, String dimension, String period) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        if (maybe.isEmpty() || !ready()) {
            return List.of();
        }
        MetricDefinition definition = maybe.get();
        if (MetricDefinition.isGlobal(dimension)) {
            return overall(metricId, period).map(List::of).orElseGet(List::of);
        }
        if (!definition.supports(dimension)) {
            log.debug("Metric {} is not sliceable by '{}' (grains: {})", metricId, dimension, definition.grains());
            return List.of();
        }
        YearMonth month = parsePeriod(period);
        if (month == null) {
            return List.of();
        }

        String entityExpr = entityExpression(definition, dimension);
        Query query = new Query();
        query.append("SELECT ").append(entityExpr).append(" AS entity, ")
                .append(measureProjection(definition))
                .append(" FROM ").append(definition.sourceView());
        appendWhere(query, definition, month, null, null);
        query.append(" GROUP BY 1 ORDER BY 1");

        List<Map<String, Object>> rows = duckDb.query(query.sql(), query.params());
        List<MetricSlice> result = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            result.add(toSlice(definition, text(row.get("entity")), row));
        }
        return List.copyOf(result);
    }

    /**
     * The un-sliced aggregate.
     *
     * <p>Queried independently rather than summed from {@link #slices}, because the parts do not add
     * up to the whole and pretending otherwise hides real coverage gaps: {@code slab_name} is absent
     * on 19.5% of bill rows, so a cost total assembled from slab slices would quietly lose a fifth
     * of the spend.
     */
    @Override
    public Optional<MetricSlice> overall(String metricId, String period) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        YearMonth month = parsePeriod(period);
        if (maybe.isEmpty() || month == null || !ready()) {
            return Optional.empty();
        }
        MetricDefinition definition = maybe.get();

        Query query = new Query();
        query.append("SELECT ").append(measureProjection(definition))
                .append(" FROM ").append(definition.sourceView());
        appendWhere(query, definition, month, null, null);

        return duckDb.queryOne(query.sql(), query.params())
                .map(row -> toSlice(definition, MetricSpec.ALL, row));
    }

    /**
     * Historical values for one series, oldest first, ending at and including {@code throughPeriod}.
     *
     * <p>Only periods that exist are returned; the series is never zero-padded, because a month with
     * no rows and a month with a genuine zero are different facts and the robust z-score would read
     * the padding as a catastrophic collapse. Periods below the metric's volume gate are likewise
     * omitted rather than included at their unreliable value.
     */
    @Override
    public List<Double> history(String metricId, String dimension, String entity, String throughPeriod, int lookback) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        YearMonth through = parsePeriod(throughPeriod);
        if (maybe.isEmpty() || through == null || lookback <= 0 || !ready()) {
            return List.of();
        }
        MetricDefinition definition = maybe.get();
        boolean global = MetricDefinition.isGlobal(dimension);
        if (!global && !definition.supports(dimension)) {
            return List.of();
        }

        Query query = new Query();
        query.append("SELECT strftime(").append(definition.timeColumn()).append(", '%Y-%m') AS period, ")
                .append(measureProjection(definition))
                .append(" FROM ").append(definition.sourceView());
        appendWhere(query, definition, null, global ? null : dimension, global ? null : entity);
        query.append(" AND ").append(definition.timeColumn()).append(" IS NOT NULL")
                .append(" AND ").append(definition.timeColumn()).append(" <= CAST(? AS DATE)");
        query.param(firstOfMonth(through));
        query.append(" GROUP BY 1 ORDER BY 1");

        List<Map<String, Object>> rows = duckDb.query(query.sql(), query.params());
        List<Double> values = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            MetricSlice slice = toSlice(definition, text(row.get("period")), row);
            if (slice.measured()) {
                values.add(slice.value());
            }
        }
        // Keep the most recent `lookback` points, still oldest-first.
        int from = Math.max(0, values.size() - lookback);
        return List.copyOf(values.subList(from, values.size()));
    }

    // ---- the two headline accessors -------------------------------------------------------------

    /**
     * All measurable entity values for one metric on one dimension in one period.
     *
     * @param metricId  stable metric identifier
     * @param dimension logical grain, or {@code global} for the un-sliced total
     * @param period    period label, e.g. {@code 2026-06}
     * @return entity to {@code {value, sampleSize}}, containing only entities that cleared the
     *         volume gate. Callers that need to see what was suppressed — the attribution engine
     *         does, since suppressed slices still carry volume — should use {@link #slices} instead.
     */
    public Map<String, double[]> series(String metricId, String dimension, String period) {
        List<MetricSlice> all = slices(metricId, dimension, period);
        Map<String, double[]> measured = new LinkedHashMap<>();
        for (MetricSlice slice : all) {
            if (slice.measured()) {
                measured.put(slice.entity(), new double[] {slice.value(), slice.sampleSize()});
            }
        }
        return measured;
    }

    /**
     * One value for one entity.
     *
     * @return the value, or empty when the metric is unknown, the period has no rows, or the slice
     *         is below its metric's {@code min_sample}. Empty is never a zero and must never be read
     *         as one.
     */
    public OptionalDouble value(String metricId, String dimension, String entity, String period) {
        MetricSlice slice = measure(metricId, dimension, entity, period);
        return slice.measured() ? OptionalDouble.of(slice.value()) : OptionalDouble.empty();
    }

    /**
     * One slice, with its sample size and coverage — the measurement behind {@link #value}.
     *
     * @return the slice; a zero-sample slice with a null value when nothing matched
     */
    public MetricSlice measure(String metricId, String dimension, String entity, String period) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        YearMonth month = parsePeriod(period);
        String label = entity == null ? MetricSpec.ALL : entity;
        if (maybe.isEmpty() || month == null || !ready()) {
            return new MetricSlice(label, null, 0L, 0.0);
        }
        MetricDefinition definition = maybe.get();
        if (MetricDefinition.isGlobal(dimension) || MetricSpec.ALL.equals(entity)) {
            return overall(metricId, period).orElseGet(() -> new MetricSlice(MetricSpec.ALL, null, 0L, 0.0));
        }
        if (!definition.supports(dimension)) {
            return new MetricSlice(label, null, 0L, 0.0);
        }

        Query query = new Query();
        query.append("SELECT ").append(measureProjection(definition))
                .append(" FROM ").append(definition.sourceView());
        appendWhere(query, definition, month, dimension, label);

        return duckDb.queryOne(query.sql(), query.params())
                .map(row -> toSlice(definition, label, row))
                .orElseGet(() -> new MetricSlice(label, null, 0L, 0.0));
    }

    /**
     * A measurement wrapped as a {@link MetricObservation}, with empty reference frames.
     *
     * <p>This is the metric layer's own contribution to the observation contract: the value, the
     * sample size and the data-quality envelope. The four reference frames are attached by the
     * benchmark engine, which is the only component that knows what an SLA target or a peer cohort
     * is. Callers that want a fully contextualised observation should ask
     * {@code BenchmarkService.observe(...)} instead — this method exists for the paths that only
     * need a governed number, and for tests.
     */
    public MetricObservation observation(String metricId, String dimension, String entity, String period) {
        MetricSlice slice = measure(metricId, dimension, entity, period);
        String grain = MetricDefinition.isGlobal(dimension) ? MetricSpec.GLOBAL : dimension;
        return new MetricObservation(
                metricId,
                grain,
                slice.entity(),
                period,
                slice.value(),
                slice.sampleSize(),
                References.empty(),
                0.0,
                qualityFor(metricId, slice.value(), slice.sampleSize(), slice.coverage()));
    }

    // ---- quality --------------------------------------------------------------------------------

    /**
     * Builds the data-quality envelope for a measured value.
     *
     * <p>Shared with the benchmark engine so that both paths to an observation describe quality the
     * same way. The metric's static caveats — negative distance on 6S-PREMIUMNEW, delay outliers
     * past seven days, escort requirement not being recorded in the trip extracts — are carried in
     * from the catalog and joined by whatever this particular slice turned up.
     *
     * @param metricId   metric being measured
     * @param value      the computed value, or null when it was suppressed or not computable
     * @param sampleSize rows behind the slice
     * @param coverage   fraction of those rows carrying a usable value
     * @return the quality envelope; confidence is {@link #CONFIDENCE_INSUFFICIENT_SAMPLE} whenever
     *         the volume gate suppressed the value
     */
    public Quality qualityFor(String metricId, Double value, long sampleSize, double coverage) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        List<String> caveats = new ArrayList<>();
        long minSample = maybe.map(MetricDefinition::minSample).orElse(0L);
        boolean gated = sampleSize < minSample;

        String confidence;
        if (value == null || !Double.isFinite(value)) {
            if (gated) {
                confidence = CONFIDENCE_INSUFFICIENT_SAMPLE;
                caveats.add(("Suppressed: %d rows is below the %d-row minimum sample for %s. "
                        + "No value is reported — this is not a zero and must not be read as recovery.")
                        .formatted(sampleSize, minSample, metricId));
            } else {
                confidence = CONFIDENCE_NOT_COMPUTABLE;
                caveats.add(("Not computable: %d rows matched but the metric produced no value, "
                        + "which for %s means an empty or zero denominator.")
                        .formatted(sampleSize, metricId));
            }
        } else if (coverage >= COVERAGE_HIGH && sampleSize >= minSample * HIGH_CONFIDENCE_SAMPLE_MULTIPLE) {
            confidence = CONFIDENCE_HIGH;
        } else if (coverage >= COVERAGE_MEDIUM) {
            confidence = CONFIDENCE_MEDIUM;
        } else {
            confidence = CONFIDENCE_LOW;
        }

        if (value != null && coverage < COVERAGE_HIGH) {
            caveats.add("Computed on %.1f%% coverage: %.1f%% of the %d rows in this slice carried no usable value."
                    .formatted(coverage * 100.0, (1.0 - coverage) * 100.0, sampleSize));
        }
        if (value != null && !gated && sampleSize < minSample * 2) {
            caveats.add("Sample of %d rows only just clears the %d-row gate; treat movement as indicative."
                    .formatted(sampleSize, minSample));
        }
        maybe.ifPresent(definition -> caveats.addAll(definition.caveats()));

        return new Quality(coverage, confidence, caveats);
    }

    // ---- period helpers -------------------------------------------------------------------------

    /**
     * Parses a {@code yyyy-MM} period label.
     *
     * @return the month, or null when the label is absent or malformed. Returning null rather than
     *         throwing keeps a bad period label from taking down a whole scan; every caller here
     *         degrades to an empty result, which is visible as missing rather than as zero.
     */
    public static YearMonth parsePeriod(String period) {
        if (period == null || period.isBlank()) {
            return null;
        }
        try {
            return YearMonth.parse(period.trim(), PERIOD_FORMAT);
        } catch (DateTimeParseException e) {
            log.warn("Malformed period label '{}' (expected yyyy-MM)", period);
            return null;
        }
    }

    /** Formats a month as a period label. */
    public static String formatPeriod(YearMonth month) {
        return month == null ? null : month.format(PERIOD_FORMAT);
    }

    /** The period immediately before this one, or null when the label is malformed. */
    public static String previousPeriod(String period) {
        YearMonth month = parsePeriod(period);
        return month == null ? null : formatPeriod(month.minusMonths(1));
    }

    /** Period labels present in a metric's source view, oldest first. */
    public List<String> periods(String metricId) {
        Optional<MetricDefinition> maybe = catalog.find(metricId);
        if (maybe.isEmpty() || !ready()) {
            return List.of();
        }
        MetricDefinition definition = maybe.get();
        Query query = new Query();
        query.append("SELECT DISTINCT strftime(").append(definition.timeColumn()).append(", '%Y-%m') AS period FROM ")
                .append(definition.sourceView());
        appendWhere(query, definition, null, null, null);
        query.append(" AND ").append(definition.timeColumn()).append(" IS NOT NULL ORDER BY 1");

        return duckDb.query(query.sql(), query.params()).stream()
                .map(row -> text(row.get("period")))
                .filter(p -> p != null && !p.isBlank())
                .toList();
    }

    /** The most recent period a metric has data for. Used when a caller says "now". */
    public Optional<String> latestPeriod(String metricId) {
        List<String> all = periods(metricId);
        return all.isEmpty() ? Optional.empty() : Optional.of(all.get(all.size() - 1));
    }

    // ---- SQL compilation ------------------------------------------------------------------------

    /** {@code (formula) AS value, count(*) AS n, (coverage) AS covered} — the shape every query returns. */
    private String measureProjection(MetricDefinition definition) {
        return "(" + definition.formula() + ") AS value, count(*) AS n, (" + definition.coverageExpr() + ") AS covered";
    }

    /** Null dimension values become {@code NA} so entity keys are stable and never null (edge case 15). */
    private String entityExpression(MetricDefinition definition, String dimension) {
        return "coalesce(CAST(" + definition.column(dimension) + " AS VARCHAR), '"
                + MetricDefinition.NULL_ENTITY + "')";
    }

    /**
     * Appends the WHERE clause. Always emits {@code WHERE 1=1} so callers can chain {@code AND}
     * fragments without tracking whether they are first.
     *
     * @param month     period to restrict to, or null for all periods
     * @param dimension grain to restrict to, or null for no entity predicate
     * @param entity    entity value, bound as a parameter
     */
    private void appendWhere(Query query, MetricDefinition definition, YearMonth month, String dimension, String entity) {
        query.append(" WHERE 1=1");

        if (month != null) {
            query.append(" AND ").append(definition.timeColumn()).append(" = CAST(? AS DATE)");
            query.param(firstOfMonth(month));
        }
        if (definition.filter() != null) {
            // Parenthesised: escort_compliance's night-shift predicate is an OR, and without the
            // brackets it would swallow every other condition in this clause.
            query.append(" AND (").append(definition.filter()).append(")");
        }
        if (definition.segmentBy() != null) {
            // The cost_per_km guard. Applied to every query for the metric, so no caller can ask for
            // cost per km on a fixed-rate contract and get a number back.
            query.append(" AND ").append(definition.segmentBy()).append(" IN (");
            for (int i = 0; i < definition.validSegments().size(); i++) {
                query.append(i == 0 ? "?" : ", ?");
                query.param(definition.validSegments().get(i));
            }
            query.append(")");
        }
        if (dimension != null && entity != null) {
            query.append(" AND ").append(entityExpression(definition, dimension)).append(" = ?");
            query.param(entity);
        }
    }

    /** Applies the volume gate and packages one result row. */
    private MetricSlice toSlice(MetricDefinition definition, String entity, Map<String, Object> row) {
        long n = toLong(row.get("n"));
        long covered = toLong(row.get("covered"));
        double coverage = n <= 0 ? 0.0 : (double) covered / (double) n;
        Double raw = toDouble(row.get("value"));

        // The gate. Below min_sample there is no number, only a row count.
        if (n < definition.minSample() || raw == null || !Double.isFinite(raw)) {
            return new MetricSlice(entity, null, n, coverage);
        }
        return new MetricSlice(entity, raw, n, coverage);
    }

    private boolean ready() {
        if (duckDb.isReady()) {
            return true;
        }
        if (warnedNotReady.compareAndSet(false, true)) {
            log.warn("Fact store is not ready; metric queries return empty results until ingest completes. "
                    + "An empty result is not a zero and downstream must not treat it as one.");
        }
        return false;
    }

    private static String firstOfMonth(YearMonth month) {
        return month.atDay(1).toString();
    }

    private static String text(Object value) {
        return value == null ? null : value.toString();
    }

    private static Double toDouble(Object value) {
        if (value instanceof Number number) {
            double d = number.doubleValue();
            return Double.isFinite(d) ? d : null;
        }
        if (value instanceof String s && !s.isBlank()) {
            try {
                return Double.valueOf(s);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    private static long toLong(Object value) {
        return value instanceof Number number ? number.longValue() : 0L;
    }

    /** Small mutable builder pairing generated SQL with its ordered bind parameters. */
    private static final class Query {
        private final StringBuilder sql = new StringBuilder(256);
        private final List<Object> params = new ArrayList<>(4);

        Query append(String fragment) {
            sql.append(fragment);
            return this;
        }

        void param(Object value) {
            params.add(value);
        }

        String sql() {
            return sql.toString();
        }

        List<Object> params() {
            return params;
        }
    }
}
