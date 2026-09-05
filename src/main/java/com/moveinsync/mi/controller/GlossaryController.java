package com.moveinsync.mi.controller;

import com.moveinsync.mi.glossary.ColumnDictionary;
import com.moveinsync.mi.glossary.OperatorCopy;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import java.util.List;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Operator vocabulary: catalog metrics explained with the extract columns in {@code data/dictionary}.
 */
@RestController
@RequestMapping("/api/glossary")
@CrossOrigin
public class GlossaryController {

    private final MetricCatalog catalog;
    private final ColumnDictionary columns;
    private final OperatorCopy copy;

    public GlossaryController(MetricCatalog catalog, ColumnDictionary columns, OperatorCopy copy) {
        this.catalog = catalog;
        this.columns = columns;
        this.copy = copy;
    }

    @GetMapping
    public Glossary glossary() {
        List<MetricGloss> metrics = catalog.all().stream().map(this::metric).toList();
        return new Glossary(metrics, columns.all());
    }

    private MetricGloss metric(MetricDefinition definition) {
        return new MetricGloss(
                definition.id(),
                definition.label(),
                definition.description() == null ? "" : definition.description().trim(),
                copy.sources(definition.id()));
    }

    public record Glossary(List<MetricGloss> metrics, List<ColumnDictionary.Column> columns) {
    }

    public record MetricGloss(
            String id, String label, String description, List<ColumnDictionary.Column> sources) {
    }
}
