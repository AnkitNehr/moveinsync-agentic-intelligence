package com.moveinsync.mi.glossary;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

/**
 * Operator meanings for source columns, transcribed from {@code data/dictionary}.
 *
 * <p>Catalog metrics like {@code escort_compliance} are not columns. This glossary is what lets the
 * console explain a metric in terms of the extract field a transport manager would recognise —
 * {@code actual_escort}, "whether an escort was actually present on the trip" — instead of a
 * snake_case id.
 */
@Service
public class ColumnDictionary {

    public static final String RESOURCE = "glossary/columns.yaml";

    private final Map<String, Column> byId;

    public ColumnDictionary() {
        this(RESOURCE);
    }

    ColumnDictionary(String classpathResource) {
        this.byId = load(classpathResource);
    }

    public Optional<Column> find(String id) {
        return Optional.ofNullable(id == null ? null : byId.get(id));
    }

    public String label(String id, String fallback) {
        Column column = byId.get(id);
        if (column != null && column.label() != null && !column.label().isBlank()) {
            return column.label();
        }
        if (fallback != null && !fallback.isBlank()) {
            return fallback.replace('_', ' ');
        }
        return id == null ? "" : id.replace('_', ' ');
    }

    public String meaning(String id) {
        Column column = byId.get(id);
        return column == null ? null : column.meaning();
    }

    public List<Column> all() {
        return List.copyOf(byId.values());
    }

    private static Map<String, Column> load(String resource) {
        ObjectMapper mapper = JsonMapper.builder(new YAMLFactory())
                .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();
        ClassPathResource file = new ClassPathResource(resource);
        try (InputStream in = file.getInputStream()) {
            File payload = mapper.readValue(in, File.class);
            Map<String, Column> index = new LinkedHashMap<>();
            List<Column> columns = payload.columns() == null ? List.of() : payload.columns();
            for (Column column : columns) {
                if (column.id() == null || column.id().isBlank()) {
                    throw new IllegalStateException("glossary column is missing id in " + resource);
                }
                index.put(column.id(), column);
            }
            return Map.copyOf(index);
        } catch (IOException e) {
            throw new IllegalStateException("Cannot load column glossary " + resource + ": " + e.getMessage(), e);
        }
    }

    public record File(List<Column> columns) {
        public File {
            columns = columns == null ? List.of() : List.copyOf(columns);
        }
    }

    /**
     * One extract column, as the dictionary states it.
     *
     * @param id      column or logical grain id
     * @param table   dictionary file it was taken from
     * @param label   short noun used in sentences
     * @param meaning dictionary "Meaning" cell
     */
    public record Column(String id, String table, String label, String meaning) {
    }
}
