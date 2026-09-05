package com.moveinsync.mi.metrics.spi;

import java.util.List;
import java.util.Optional;

/**
 * What the scanner needs from the metric catalog: the list of things worth scanning.
 *
 * <p>Implemented by the metric layer's {@code MetricQueryService}. Declared as a port here so the
 * anomaly and attribution engines depend on an interface they own rather than on the catalog's
 * internals — the scanner is generic over metrics by construction, and this interface is what makes
 * that structural rather than merely intended.
 */
public interface MetricCatalogPort {

    /**
     * Every metric eligible for scanning, in catalog order.
     *
     * @return metric specs; empty when the catalog has not been loaded
     */
    List<MetricSpec> metrics();

    /**
     * Looks up a single metric definition.
     *
     * @param metricId stable metric identifier
     * @return the spec, or empty when the id is not in the catalog
     */
    Optional<MetricSpec> find(String metricId);
}
