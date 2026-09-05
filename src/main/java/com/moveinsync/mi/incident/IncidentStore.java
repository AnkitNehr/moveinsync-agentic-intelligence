package com.moveinsync.mi.incident;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Durable agent memory: open incidents, suppressions and scheduled follow-ups.
 *
 * <p>Without memory the platform would re-derive the same conclusions every run and re-raise
 * everything an operator had already judged and closed. Three things are remembered:
 *
 * <ul>
 *   <li><strong>Incidents</strong> — so a movement already under investigation is recognised as the
 *       same story rather than raised again as a fresh one.</li>
 *   <li><strong>Suppressions</strong> — written on dismissal and honoured by the candidate ranker,
 *       so the system gets quieter as the operator teaches it what does not matter.</li>
 *   <li><strong>Follow-ups</strong> — scheduled promises to look again, which
 *       {@link FollowUpScheduler} acts on unprompted.</li>
 * </ul>
 *
 * <p>State is held in memory and mirrored to a single JSON document. Writes are serialised on a
 * monitor and land via a temp-file-then-move so a crash mid-write cannot leave a truncated file that
 * would silently wipe the operator's dismissal history on next boot. Postgres is the production
 * answer; this file-backed store keeps the assessment runnable with no external dependency while
 * preserving the same semantics.
 */
@Service
public class IncidentStore {

    private static final Logger log = LoggerFactory.getLogger(IncidentStore.class);

    /** Lifecycle states an incident can occupy. */
    public static final String STATUS_OPEN = "OPEN";
    public static final String STATUS_MONITORING = "MONITORING";
    public static final String STATUS_RESOLVED = "RESOLVED";
    public static final String STATUS_DISMISSED = "DISMISSED";

    /** Serialised shape of the state file. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    record IncidentState(
            List<Incident> incidents, List<Suppression> suppressions, List<FollowUp> followUps) {

        IncidentState {
            incidents = incidents == null ? List.of() : List.copyOf(incidents);
            suppressions = suppressions == null ? List.of() : List.copyOf(suppressions);
            followUps = followUps == null ? List.of() : List.copyOf(followUps);
        }

        static IncidentState empty() {
            return new IncidentState(List.of(), List.of(), List.of());
        }
    }

    private final Object lock = new Object();
    private final Map<String, Incident> incidents = new LinkedHashMap<>();
    private final Map<String, Suppression> suppressions = new LinkedHashMap<>();
    private final Map<String, FollowUp> followUps = new LinkedHashMap<>();

    private final Path stateFile;
    private final ObjectMapper mapper;

    public IncidentStore(@Value("${app.state.dir:./data/state}") String stateDir) {
        this.stateFile = Paths.get(stateDir).resolve("incidents.json");
        this.mapper = JsonMapper.builder()
                .addModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .enable(SerializationFeature.INDENT_OUTPUT)
                .build();
    }

    /** Path of the backing JSON document. Exposed for diagnostics and tests. */
    public Path stateFile() {
        return stateFile;
    }

    // ---- lifecycle ------------------------------------------------------------------------------

    /**
     * Rehydrates state from disk. A corrupt or unreadable file is logged and skipped rather than
     * thrown: losing memory degrades the system to a stateless one, but refusing to start makes it
     * useless entirely.
     */
    @PostConstruct
    public void load() {
        synchronized (lock) {
            if (!Files.exists(stateFile)) {
                log.info("No incident state at {}; starting with empty memory", stateFile.toAbsolutePath());
                return;
            }
            try {
                IncidentState state = mapper.readValue(stateFile.toFile(), IncidentState.class);
                incidents.clear();
                suppressions.clear();
                followUps.clear();
                state.incidents().forEach(incident -> incidents.put(incident.id(), incident));
                state.suppressions().forEach(suppression -> suppressions.put(suppression.id(), suppression));
                state.followUps().forEach(followUp -> followUps.put(followUp.incidentId(), followUp));
                log.info(
                        "Loaded incident memory from {}: {} incidents, {} suppressions, {} follow-ups",
                        stateFile.toAbsolutePath(),
                        incidents.size(),
                        suppressions.size(),
                        followUps.size());
            } catch (IOException e) {
                log.warn("Could not read incident state at {}; continuing with empty memory: {}",
                        stateFile.toAbsolutePath(), e.toString());
            }
        }
    }

    // ---- incidents ------------------------------------------------------------------------------

    /**
     * Records an incident, replacing any earlier version with the same id. If the incident carries a
     * {@code followUpAt} timestamp, a matching follow-up is registered so the commitment to re-check
     * is never lost between the narrative stage and the scheduler.
     */
    public Incident open(Incident incident) {
        if (incident == null || incident.id() == null || incident.id().isBlank()) {
            throw new IllegalArgumentException("Incident must carry a non-blank id");
        }
        synchronized (lock) {
            incidents.put(incident.id(), incident);
            Instant due = parseInstant(incident.followUpAt());
            if (due != null && !followUps.containsKey(incident.id())) {
                followUps.put(incident.id(), buildFollowUp(incident, due, originPeriodOf(incident, null)));
            }
            persist();
            return incident;
        }
    }

    /** All known incidents, newest detection first, then by id for a stable total order. */
    public List<Incident> all() {
        synchronized (lock) {
            List<Incident> snapshot = new ArrayList<>(incidents.values());
            snapshot.sort(Comparator
                    .comparing((Incident incident) -> nullSafe(incident.detectedAt()))
                    .reversed()
                    .thenComparing(incident -> nullSafe(incident.id())));
            return List.copyOf(snapshot);
        }
    }

    /** Incidents in an actionable state: open or monitoring. */
    public List<Incident> openIncidents() {
        return all().stream()
                .filter(incident -> STATUS_OPEN.equalsIgnoreCase(incident.status())
                        || STATUS_MONITORING.equalsIgnoreCase(incident.status()))
                .toList();
    }

    /** Looks up an incident by id. */
    public Optional<Incident> byId(String id) {
        synchronized (lock) {
            return Optional.ofNullable(id == null ? null : incidents.get(id));
        }
    }

    /**
     * Dismisses an incident and writes the suppression that keeps it from coming back.
     *
     * <p>The suppression is derived from the incident's first evidence item, which names the metric
     * and entity the narrative was actually about. Any pending follow-up is cancelled — the operator
     * has already made the judgement the follow-up existed to inform.
     *
     * @return the dismissed incident, or empty if no such incident exists
     */
    public Optional<Incident> dismiss(String id, String reason) {
        synchronized (lock) {
            Incident existing = id == null ? null : incidents.get(id);
            if (existing == null) {
                return Optional.empty();
            }

            Incident dismissed = withStatus(existing, STATUS_DISMISSED);
            incidents.put(id, dismissed);

            String metricId = firstEvidenceMetric(existing);
            String entity = firstEvidenceEntity(existing);
            Suppression suppression = new Suppression(
                    "sup-" + UUID.nameUUIDFromBytes(("dismiss:" + id).getBytes()),
                    metricId == null ? Suppression.WILDCARD : metricId,
                    Suppression.WILDCARD,
                    entity == null ? Suppression.WILDCARD : entity,
                    reason == null || reason.isBlank() ? "dismissed by operator" : reason,
                    id,
                    Instant.now(),
                    null);
            suppressions.put(suppression.id(), suppression);

            FollowUp pending = followUps.get(id);
            if (pending != null && pending.pending()) {
                followUps.put(id, pending.completed(FollowUp.RECOVERED, "cancelled: incident dismissed"));
            }

            persist();
            log.info("Dismissed incident {} and wrote suppression {} ({}/{})",
                    id, suppression.id(), suppression.metricId(), suppression.entity());
            return Optional.of(dismissed);
        }
    }

    /** Marks an incident resolved without writing a suppression. */
    public Optional<Incident> resolve(String id) {
        synchronized (lock) {
            Incident existing = id == null ? null : incidents.get(id);
            if (existing == null) {
                return Optional.empty();
            }
            Incident resolved = withStatus(existing, STATUS_RESOLVED);
            incidents.put(id, resolved);
            persist();
            return Optional.of(resolved);
        }
    }

    // ---- suppressions ---------------------------------------------------------------------------

    /** Suppressions currently in force. */
    public List<Suppression> openSuppressions() {
        return openSuppressions(Instant.now());
    }

    /** Suppressions in force at a specific instant; the overload keeps tests free of wall-clock time. */
    public List<Suppression> openSuppressions(Instant now) {
        synchronized (lock) {
            return suppressions.values().stream()
                    .filter(suppression -> suppression.activeAt(now))
                    .sorted(Comparator.comparing(suppression -> nullSafe(suppression.id())))
                    .toList();
        }
    }

    /**
     * Whether a candidate finding is covered by an active suppression. Consulted by the candidate
     * ranker before a finding is ever scored, so dismissed patterns cost nothing downstream.
     */
    public boolean isSuppressed(Finding finding) {
        if (finding == null) {
            return false;
        }
        Instant now = Instant.now();
        synchronized (lock) {
            return suppressions.values().stream()
                    .filter(suppression -> suppression.activeAt(now))
                    .anyMatch(suppression ->
                            suppression.matches(finding.metricId(), finding.dimension(), finding.entity()));
        }
    }

    /** Adds a suppression directly, for operator rules not tied to a dismissal. */
    public Suppression suppress(Suppression suppression) {
        if (suppression == null || suppression.id() == null || suppression.id().isBlank()) {
            throw new IllegalArgumentException("Suppression must carry a non-blank id");
        }
        synchronized (lock) {
            suppressions.put(suppression.id(), suppression);
            persist();
            return suppression;
        }
    }

    // ---- follow-ups -----------------------------------------------------------------------------

    /**
     * Schedules a re-check of an incident a number of days out.
     *
     * <p>The clock is read here rather than passed in because scheduling is an operational act, not
     * a governance verdict; {@link #scheduleFollowUp(String, int, Instant)} exists for deterministic
     * tests.
     *
     * @return the scheduled follow-up, or empty when the incident is unknown
     */
    public Optional<FollowUp> scheduleFollowUp(String incidentId, int days) {
        return scheduleFollowUp(incidentId, days, Instant.now());
    }

    /** Schedules a re-check relative to an explicit base instant. */
    public Optional<FollowUp> scheduleFollowUp(String incidentId, int days, Instant from) {
        return scheduleFollowUp(incidentId, days, from, null);
    }

    /**
     * Schedules a re-check, capturing the originating period so the loop can re-measure a
     * <em>later</em> month rather than the month that already failed.
     */
    public Optional<FollowUp> scheduleFollowUp(String incidentId, int days, Instant from, String originPeriod) {
        synchronized (lock) {
            Incident incident = incidentId == null ? null : incidents.get(incidentId);
            if (incident == null) {
                return Optional.empty();
            }
            Instant base = from == null ? Instant.now() : from;
            FollowUp followUp = buildFollowUp(
                    incident,
                    base.plus(Math.max(0, days), ChronoUnit.DAYS),
                    originPeriod);
            followUps.put(incidentId, followUp);
            persist();
            return Optional.of(followUp);
        }
    }

    /**
     * Makes a pending follow-up due immediately so the console can fire the loop without waiting
     * for the calendar. A completed follow-up is re-opened as pending at {@code now}.
     */
    public Optional<FollowUp> markDue(String incidentId, Instant now) {
        synchronized (lock) {
            Incident incident = incidentId == null ? null : incidents.get(incidentId);
            if (incident == null) {
                return Optional.empty();
            }
            Instant due = now == null ? Instant.now() : now;
            FollowUp existing = followUps.get(incidentId);
            FollowUp dueNow = existing == null
                    ? buildFollowUp(incident, due, originPeriodOf(incident, null))
                    : new FollowUp(
                            existing.incidentId(),
                            existing.metricId(),
                            existing.dimension(),
                            existing.entity(),
                            existing.period(),
                            due,
                            FollowUp.PENDING,
                            existing.note());
            followUps.put(incidentId, dueNow);
            persist();
            return Optional.of(dueNow);
        }
    }

    /** Pending follow-ups whose due time has arrived, oldest first. */
    public List<FollowUp> dueFollowUps(Instant now) {
        synchronized (lock) {
            return followUps.values().stream()
                    .filter(followUp -> followUp.dueAt(now))
                    .sorted(Comparator.comparing(FollowUp::dueAt))
                    .toList();
        }
    }

    /** All follow-ups regardless of state. */
    public List<FollowUp> allFollowUps() {
        synchronized (lock) {
            return List.copyOf(followUps.values());
        }
    }

    /** Marks a follow-up complete with an outcome, so it is not actioned twice. */
    public Optional<FollowUp> completeFollowUp(String incidentId, String status, String note) {
        synchronized (lock) {
            FollowUp existing = incidentId == null ? null : followUps.get(incidentId);
            if (existing == null) {
                return Optional.empty();
            }
            FollowUp completed = existing.completed(status, note);
            followUps.put(incidentId, completed);
            persist();
            return Optional.of(completed);
        }
    }

    // ---- internals ------------------------------------------------------------------------------

    private FollowUp buildFollowUp(Incident incident, Instant dueAt, String originPeriod) {
        return new FollowUp(
                incident.id(),
                firstEvidenceMetric(incident),
                null,
                firstEvidenceEntity(incident),
                originPeriodOf(incident, originPeriod),
                dueAt,
                FollowUp.PENDING,
                null);
    }

    /**
     * Prefer an explicit origin period, then the {@code yyyy-MM} suffix on the incident id
     * ({@code inc-ota-2026-06}), then nothing — the scheduler will refuse to re-measure the
     * originating month once a later period exists.
     */
    public static String originPeriodOf(Incident incident, String explicit) {
        if (explicit != null && explicit.matches("\\d{4}-\\d{2}")) {
            return explicit;
        }
        if (incident != null && incident.id() != null) {
            java.util.regex.Matcher matcher =
                    java.util.regex.Pattern.compile("(\\d{4}-\\d{2})$").matcher(incident.id());
            if (matcher.find()) {
                return matcher.group(1);
            }
        }
        return explicit;
    }

    private static String firstEvidenceMetric(Incident incident) {
        return incident.evidence().stream()
                .filter(evidence -> evidence != null && evidence.metricId() != null
                        && !evidence.metricId().isBlank())
                .map(evidence -> evidence.metricId())
                .findFirst()
                .orElse(null);
    }

    private static String firstEvidenceEntity(Incident incident) {
        return incident.evidence().stream()
                .filter(evidence -> evidence != null && evidence.entity() != null
                        && !evidence.entity().isBlank())
                .map(evidence -> evidence.entity())
                .findFirst()
                .orElse(null);
    }

    private static Incident withStatus(Incident incident, String status) {
        return new Incident(
                incident.id(),
                incident.title(),
                incident.whyNow(),
                incident.priority(),
                incident.severity(),
                incident.findingIds(),
                incident.explanation(),
                incident.evidence(),
                incident.recommendedActions(),
                incident.policy(),
                incident.quality(),
                incident.detectedAt(),
                incident.followUpAt(),
                status);
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Instant.parse(value);
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static String nullSafe(String value) {
        return value == null ? "" : value;
    }

    /**
     * Mirrors memory to disk. Writes to a sibling temp file and moves it into place so an interrupted
     * write cannot destroy existing state.
     */
    private void persist() {
        try {
            Path parent = stateFile.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            IncidentState state = new IncidentState(
                    new ArrayList<>(incidents.values()),
                    new ArrayList<>(suppressions.values()),
                    new ArrayList<>(followUps.values()));
            Path temp = Files.createTempFile(parent, "incidents-", ".json.tmp");
            mapper.writeValue(temp.toFile(), state);
            try {
                Files.move(temp, stateFile,
                        StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(temp, stateFile, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.error("Failed to persist incident state to {}: {}", stateFile.toAbsolutePath(), e.toString());
        }
    }
}
