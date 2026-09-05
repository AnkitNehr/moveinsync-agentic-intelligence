package com.moveinsync.mi.metric;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.moveinsync.mi.metrics.spi.MetricSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * The versioned metric catalog: every metric this platform knows how to compute, loaded from
 * {@code classpath:metrics/*.yaml} at startup.
 *
 * <h2>Why a catalog rather than queries in services</h2>
 *
 * <p>The dashboard, the conversational agent, the reasoning agent's tool surface and the nightly
 * scan all need on-time arrival. If each computes it, they will disagree — not immediately, but the
 * first time someone adjusts a grace window or excludes a product type in one place. One definition
 * of OTA, in one file, versioned, is the difference between a system whose numbers reconcile and a
 * system whose numbers merely usually reconcile.
 *
 * <h2>Fail fast, loudly</h2>
 *
 * <p>Every file is parsed and validated during construction. Unknown YAML keys are a hard error, not
 * a shrug: {@code min_samples: 500} instead of {@code min_sample: 500} would otherwise load cleanly,
 * silently apply the default gate and let a 244-trip segment report a 26-point swing. A metric that
 * cannot be loaded must break the boot, because downstream a missing metric is indistinguishable
 * from a clean bill of health.
 */
@Service
public class MetricCatalog {

    private static final Logger log = LoggerFactory.getLogger(MetricCatalog.class);

    /** Where catalog files live. One file per metric; the filename should match the metric id. */
    public static final String CATALOG_LOCATION = "classpath*:metrics/*.yaml";

    private final Map<String, MetricDefinition> byId;
    private final List<MetricDefinition> ordered;

    public MetricCatalog() {
        this(CATALOG_LOCATION);
    }

    /**
     * Loads a catalog from an arbitrary resource pattern. Exposed for tests, which stage fixture
     * catalogs rather than depending on the shipped one.
     *
     * @param location Spring resource pattern resolving to YAML metric files
     */
    public MetricCatalog(String location) {
        long t0 = System.currentTimeMillis();
        this.ordered = load(location);
        Map<String, MetricDefinition> index = new LinkedHashMap<>();
        for (MetricDefinition definition : ordered) {
            MetricDefinition clash = index.put(definition.id(), definition);
            if (clash != null) {
                throw new IllegalStateException(
                        "Duplicate metric id '" + definition.id() + "' in the catalog. Metric ids are the "
                                + "join key between the catalog, the SLA policy and every narrative citation, "
                                + "so they must be unique.");
            }
        }
        this.byId = Map.copyOf(index);

        if (ordered.isEmpty()) {
            log.error("Metric catalog is EMPTY (no files matched {}). Every downstream scan will report "
                    + "nothing to see, which is not the same as nothing being wrong.", location);
        } else {
            log.info("Metric catalog loaded: {} metrics in {} ms", ordered.size(), System.currentTimeMillis() - t0);
            for (MetricDefinition definition : ordered) {
                log.info("  {}", definition.summary());
            }
        }
    }

    private static List<MetricDefinition> load(String location) {
        ObjectMapper mapper = JsonMapper.builder(new YAMLFactory())
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                // A typo'd key must fail the boot. See the class javadoc.
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();

        Resource[] resources;
        try {
            resources = new PathMatchingResourcePatternResolver().getResources(location);
        } catch (IOException e) {
            throw new IllegalStateException("Cannot scan metric catalog location " + location, e);
        }

        List<MetricDefinition> loaded = new ArrayList<>(resources.length);
        for (Resource resource : resources) {
            String name = resource.getFilename() == null ? resource.getDescription() : resource.getFilename();
            try (InputStream in = resource.getInputStream()) {
                MetricDefinition definition = mapper.readValue(in, MetricDefinition.class);
                definition.validate();
                warnOnFilenameMismatch(name, definition);
                loaded.add(definition);
            } catch (IOException e) {
                throw new IllegalStateException("Cannot parse metric catalog file " + name + ": " + e.getMessage(), e);
            }
        }
        loaded.sort(Comparator.comparing(MetricDefinition::id));
        return List.copyOf(loaded);
    }

    private static void warnOnFilenameMismatch(String filename, MetricDefinition definition) {
        if (filename == null) {
            return;
        }
        String stem = filename.replaceFirst("\\.ya?ml$", "");
        if (!stem.equals(definition.id())) {
            log.warn("Metric file {} declares id '{}'. Convention is one file per metric named after its id; "
                    + "the mismatch is legal but makes the catalog harder to navigate.", filename, definition.id());
        }
    }

    // ---- lookup ---------------------------------------------------------------------------------

    /**
     * Returns a metric definition by id.
     *
     * @param metricId stable metric identifier
     * @return the definition, never null
     * @throws IllegalArgumentException listing the known ids when the metric does not exist — a
     *         typo'd metric id in an agent tool call should produce a usable error, not a null
     */
    public MetricDefinition get(String metricId) {
        MetricDefinition definition = byId.get(metricId);
        if (definition == null) {
            throw new IllegalArgumentException(
                    "Unknown metric '" + metricId + "'. Known metrics: " + ids());
        }
        return definition;
    }

    /** Non-throwing lookup, for callers that treat an unknown metric as a normal outcome. */
    public Optional<MetricDefinition> find(String metricId) {
        return Optional.ofNullable(metricId == null ? null : byId.get(metricId));
    }

    /** Every metric in the catalog, ordered by id. */
    public List<MetricDefinition> all() {
        return ordered;
    }

    /** Every metric id, ordered. */
    public List<String> ids() {
        return ordered.stream().map(MetricDefinition::id).toList();
    }

    /**
     * Every metric's display label, ordered — what to show a human.
     *
     * <p>Separate from {@link #ids()} because the two are for different audiences and mixing them up
     * is a recurring tell. An id like {@code driver_noncompliance} is a stable key for URLs, audit
     * records and cross-references; it is not a name, and it belongs nowhere a transport manager
     * reads. The chat refusal listed ids for exactly this reason — it had a list of metrics to hand
     * and reached for the wrong one.
     */
    public List<String> labels() {
        return ordered.stream().map(MetricDefinition::label).toList();
    }

    /**
     * Logical grains a metric may be sliced by, including {@code global}.
     *
     * @param metricId stable metric identifier
     * @return the grain list; empty when the metric is unknown
     */
    public List<String> grainsFor(String metricId) {
        return find(metricId).map(MetricDefinition::grains).orElseGet(List::of);
    }

    /** Grains excluding {@code global} — what the scanner iterates when looking for attribution. */
    public List<String> sliceableGrainsFor(String metricId) {
        return find(metricId).map(MetricDefinition::sliceableGrains).orElseGet(List::of);
    }

    /** Whether a metric may be sliced on a grain. Unknown metric or grain returns false. */
    public boolean supports(String metricId, String grain) {
        return find(metricId).map(d -> d.supports(grain)).orElse(false);
    }

    /** The narrow specs the scanner consumes, ordered by id. */
    public List<MetricSpec> specs() {
        return ordered.stream().map(MetricDefinition::toSpec).toList();
    }

    /** Metrics reading from one source relation, e.g. everything defined over {@code bills}. */
    public List<MetricDefinition> forView(String sourceView) {
        return ordered.stream().filter(d -> d.sourceView().equals(sourceView)).toList();
    }

    /** Distinct source relations the catalog depends on. Used to check ingest published them all. */
    public List<String> sourceViews() {
        return ordered.stream().map(MetricDefinition::sourceView).distinct().sorted().toList();
    }

    public int size() {
        return ordered.size();
    }
}
