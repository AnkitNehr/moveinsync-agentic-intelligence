package com.moveinsync.mi.audit;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Append-only audit trail: what was detected, what backed it, what was recommended, who got told.
 *
 * <p>A system that recommends operational action against vendors has to be able to answer "why did
 * you say that, and what did it cost?" months later. Every pipeline stage appends one JSON line
 * here. The format is JSON Lines rather than a JSON array precisely because it is append-only: a new
 * record is a single {@code O(1)} write that cannot corrupt what came before, and the file stays
 * readable by {@code jq}, {@code grep} and DuckDB's {@code read_json_auto} without a parser that has
 * to hold the whole history in memory.
 *
 * <p>Token counts and model tier are recorded per stage so the run cost in
 * {@link com.moveinsync.mi.model.RunSummary} is reconstructible from the log rather than merely
 * asserted by it.
 */
@Service
public class AuditLog {

    private static final Logger log = LoggerFactory.getLogger(AuditLog.class);

    /** Canonical stage names, so the trail can be filtered reliably. */
    public static final String STAGE_INGEST = "INGEST";
    public static final String STAGE_SCAN = "SCAN";
    public static final String STAGE_ATTRIBUTE = "ATTRIBUTE";
    public static final String STAGE_TRIAGE = "TRIAGE";
    public static final String STAGE_NARRATE = "NARRATE";
    public static final String STAGE_POLICY = "POLICY";
    public static final String STAGE_DELIVER = "DELIVER";
    public static final String STAGE_FOLLOW_UP = "FOLLOW_UP";

    /**
     * One immutable audit record.
     *
     * @param runId            run this record belongs to
     * @param timestamp        ISO-8601 instant the record was appended
     * @param stage            pipeline stage, one of the {@code STAGE_*} constants
     * @param detected         identifiers of what the stage found (finding ids, incident ids, metrics)
     * @param evidence         claim-to-metric bindings that substantiate the detection
     * @param recommended      policy-gated actions proposed, including the denied ones
     * @param deliveredTo      channels or recipients the output reached
     * @param modelTier        LLM tier used, or null for a purely deterministic stage
     * @param promptTokens     prompt tokens consumed by this stage
     * @param completionTokens completion tokens produced by this stage
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record AuditEntry(
            String runId,
            String timestamp,
            String stage,
            List<String> detected,
            List<Evidence> evidence,
            List<Action> recommended,
            List<String> deliveredTo,
            String modelTier,
            long promptTokens,
            long completionTokens) {

        public AuditEntry {
            detected = detected == null ? List.of() : List.copyOf(detected);
            evidence = evidence == null ? List.of() : List.copyOf(evidence);
            recommended = recommended == null ? List.of() : List.copyOf(recommended);
            deliveredTo = deliveredTo == null ? List.of() : List.copyOf(deliveredTo);
        }
    }

    private final Object lock = new Object();
    private final Path logFile;
    private final ObjectMapper mapper;

    public AuditLog(@Value("${app.state.dir:./data/state}") String stateDir) {
        this.logFile = Paths.get(stateDir).resolve("audit.jsonl");
        this.mapper = JsonMapper.builder()
                .addModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                // One record per line: INDENT_OUTPUT must stay off or the JSONL contract breaks.
                .disable(SerializationFeature.INDENT_OUTPUT)
                .build();
    }

    /** Path of the backing JSON Lines file. */
    public Path logFile() {
        return logFile;
    }

    /**
     * Appends a fully-formed record.
     *
     * <p>Audit failures are logged, never thrown. Losing an audit line is bad; failing an analysis
     * run that has already completed because its receipt could not be written is worse.
     */
    public AuditEntry append(AuditEntry entry) {
        if (entry == null) {
            return null;
        }
        synchronized (lock) {
            try {
                Path parent = logFile.toAbsolutePath().getParent();
                if (parent != null) {
                    Files.createDirectories(parent);
                }
                String line = mapper.writeValueAsString(entry) + System.lineSeparator();
                Files.writeString(logFile, line, StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            } catch (IOException e) {
                log.error("Failed to append audit entry for run {} stage {}: {}",
                        entry.runId(), entry.stage(), e.toString());
            }
            return entry;
        }
    }

    /** Appends a record, stamping the current time. */
    public AuditEntry record(
            String runId,
            String stage,
            List<String> detected,
            List<Evidence> evidence,
            List<Action> recommended,
            List<String> deliveredTo,
            String modelTier,
            long promptTokens,
            long completionTokens) {
        return append(new AuditEntry(
                runId,
                Instant.now().toString(),
                stage,
                detected,
                evidence,
                recommended,
                deliveredTo,
                modelTier,
                promptTokens,
                completionTokens));
    }

    /** Appends a record for a deterministic stage that consumed no tokens. */
    public AuditEntry recordDeterministic(String runId, String stage, List<String> detected) {
        return record(runId, stage, detected, List.of(), List.of(), List.of(), null, 0L, 0L);
    }

    /** Reads the whole trail, oldest first. Unparseable lines are skipped, not fatal. */
    public List<AuditEntry> readAll() {
        synchronized (lock) {
            List<AuditEntry> entries = new ArrayList<>();
            if (!Files.exists(logFile)) {
                return List.of();
            }
            try {
                for (String line : Files.readAllLines(logFile, StandardCharsets.UTF_8)) {
                    if (line.isBlank()) {
                        continue;
                    }
                    try {
                        entries.add(mapper.readValue(line, AuditEntry.class));
                    } catch (IOException e) {
                        log.warn("Skipping unparseable audit line: {}", e.toString());
                    }
                }
            } catch (IOException e) {
                log.error("Failed to read audit log {}: {}", logFile.toAbsolutePath(), e.toString());
            }
            return List.copyOf(entries);
        }
    }

    /** The most recent {@code limit} records, oldest first within the window. */
    public List<AuditEntry> tail(int limit) {
        List<AuditEntry> all = readAll();
        if (limit <= 0 || all.size() <= limit) {
            return all;
        }
        return List.copyOf(all.subList(all.size() - limit, all.size()));
    }

    /** All records for a single run, in append order. */
    public List<AuditEntry> forRun(String runId) {
        if (runId == null) {
            return List.of();
        }
        return readAll().stream().filter(entry -> runId.equals(entry.runId())).toList();
    }
}
