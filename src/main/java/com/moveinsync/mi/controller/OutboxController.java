package com.moveinsync.mi.controller;

import com.moveinsync.mi.delivery.Communication;
import com.moveinsync.mi.delivery.DeliveryService;
import com.moveinsync.mi.delivery.OutboxStore;
import java.util.List;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The communications outbox: every draft sent to the console, and every action policy refused.
 */
@RestController
@RequestMapping("/api/outbox")
@CrossOrigin
public class OutboxController {

    private final OutboxStore store;
    private final DeliveryService delivery;

    public OutboxController(OutboxStore store, DeliveryService delivery) {
        this.store = store;
        this.delivery = delivery;
    }

    @GetMapping
    public List<Communication> list(@RequestParam(required = false) String incidentId) {
        return incidentId == null || incidentId.isBlank() ? store.all() : store.forIncident(incidentId);
    }

    @GetMapping("/{id}")
    public Communication byId(@PathVariable String id) {
        return store.byId(id).orElseThrow(() -> NotFoundException.of("communication", id, null));
    }

    /**
     * Marks a drafted message sent. Idempotent for an already-sent row. Blocked rows are left as-is
     * — sending a refusal would pretend policy allowed it.
     */
    @PostMapping("/{id}/send")
    public Communication send(@PathVariable String id) {
        Communication existing = store.byId(id)
                .orElseThrow(() -> NotFoundException.of("communication", id, null));
        if (Communication.BLOCKED.equals(existing.status())) {
            return existing;
        }
        Communication sent = delivery.markSent(id);
        if (sent == null) {
            throw NotFoundException.of("communication", id, null);
        }
        return sent;
    }
}
