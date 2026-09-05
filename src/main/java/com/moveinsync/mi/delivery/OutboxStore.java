package com.moveinsync.mi.delivery;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Durable outbox: every communication the platform drafted, sent or refused.
 *
 * <p>Same persistence contract as incident memory — a single JSON document, temp-file-then-move —
 * so a crash cannot truncate the trail of who was told what.
 */
@Service
public class OutboxStore {

    private static final Logger log = LoggerFactory.getLogger(OutboxStore.class);

    @JsonIgnoreProperties(ignoreUnknown = true)
    record OutboxState(List<Communication> messages) {
        OutboxState {
            messages = messages == null ? List.of() : List.copyOf(messages);
        }

        static OutboxState empty() {
            return new OutboxState(List.of());
        }
    }

    private final Object lock = new Object();
    private final Map<String, Communication> messages = new LinkedHashMap<>();
    private final Path stateFile;
    private final ObjectMapper mapper;

    public OutboxStore(@Value("${app.state.dir:./data/state}") String stateDir) {
        this.stateFile = Paths.get(stateDir).resolve("outbox.json");
        this.mapper = JsonMapper.builder()
                .addModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .enable(SerializationFeature.INDENT_OUTPUT)
                .build();
    }

    public Path stateFile() {
        return stateFile;
    }

    @PostConstruct
    public void load() {
        synchronized (lock) {
            if (!Files.exists(stateFile)) {
                log.info("No outbox state at {}; starting empty", stateFile.toAbsolutePath());
                return;
            }
            try {
                OutboxState state = mapper.readValue(stateFile.toFile(), OutboxState.class);
                messages.clear();
                state.messages().forEach(message -> messages.put(message.id(), message));
                log.info("Loaded {} outbox message(s) from {}", messages.size(), stateFile.toAbsolutePath());
            } catch (IOException e) {
                log.warn("Could not read outbox at {}; continuing empty: {}",
                        stateFile.toAbsolutePath(), e.toString());
            }
        }
    }

    /**
     * Inserts a message. A prior live {@code notify} for the same incident is marked
     * {@link Communication#SUPERSEDED} so a re-run does not leave two "current" drafts.
     */
    public Communication put(Communication message) {
        if (message == null || message.id() == null || message.id().isBlank()) {
            throw new IllegalArgumentException("Communication must carry a non-blank id");
        }
        synchronized (lock) {
            if (Communication.SENT.equals(message.status())
                    || Communication.DRAFTED.equals(message.status())) {
                supersedeLive(message.incidentId(), message.actionType(), message.id());
            }
            if (Communication.BLOCKED.equals(message.status())) {
                replaceBlocked(message.incidentId(), message.actionType());
            }
            messages.put(message.id(), message);
            persist();
            return message;
        }
    }

    public Optional<Communication> byId(String id) {
        synchronized (lock) {
            return Optional.ofNullable(id == null ? null : messages.get(id));
        }
    }

    public List<Communication> all() {
        synchronized (lock) {
            List<Communication> snapshot = new ArrayList<>(messages.values());
            snapshot.sort(Comparator
                    .comparing((Communication c) -> nullSafe(c.createdAt()))
                    .reversed()
                    .thenComparing(c -> nullSafe(c.id())));
            return List.copyOf(snapshot);
        }
    }

    public List<Communication> forIncident(String incidentId) {
        if (incidentId == null || incidentId.isBlank()) {
            return all();
        }
        return all().stream()
                .filter(c -> incidentId.equals(c.incidentId()))
                .toList();
    }

    public Communication markSent(String id) {
        synchronized (lock) {
            Communication existing = messages.get(id);
            if (existing == null) {
                return null;
            }
            if (Communication.SENT.equals(existing.status())) {
                return existing;
            }
            if (Communication.BLOCKED.equals(existing.status())) {
                return existing;
            }
            Communication sent = existing.withStatus(Communication.SENT, existing.blockedReason());
            messages.put(id, sent);
            persist();
            return sent;
        }
    }

    private void supersedeLive(String incidentId, String actionType, String keepId) {
        if (incidentId == null || actionType == null) {
            return;
        }
        for (Communication existing : List.copyOf(messages.values())) {
            if (keepId.equals(existing.id())) {
                continue;
            }
            if (!incidentId.equals(existing.incidentId()) || !actionType.equals(existing.actionType())) {
                continue;
            }
            if (Communication.SENT.equals(existing.status())
                    || Communication.DRAFTED.equals(existing.status())) {
                messages.put(existing.id(), existing.withStatus(Communication.SUPERSEDED, null));
            }
        }
    }

    private void replaceBlocked(String incidentId, String actionType) {
        if (incidentId == null || actionType == null) {
            return;
        }
        List<String> stale = messages.values().stream()
                .filter(c -> incidentId.equals(c.incidentId())
                        && actionType.equals(c.actionType())
                        && Communication.BLOCKED.equals(c.status()))
                .map(Communication::id)
                .toList();
        stale.forEach(messages::remove);
    }

    private static String nullSafe(String value) {
        return value == null ? "" : value;
    }

    private void persist() {
        try {
            Path parent = stateFile.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            OutboxState state = new OutboxState(new ArrayList<>(messages.values()));
            Path temp = Files.createTempFile(parent, "outbox-", ".json.tmp");
            mapper.writeValue(temp.toFile(), state);
            try {
                Files.move(temp, stateFile,
                        StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException e) {
                Files.move(temp, stateFile, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.error("Failed to persist outbox to {}: {}", stateFile.toAbsolutePath(), e.toString());
        }
    }
}
