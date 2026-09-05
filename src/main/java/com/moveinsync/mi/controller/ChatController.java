package com.moveinsync.mi.controller;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.moveinsync.mi.audit.AuditLog;
import com.moveinsync.mi.glossary.OperatorCopy;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.pipeline.PortRegistry;
import com.moveinsync.mi.pipeline.SenseReasonActPipeline;
import com.moveinsync.mi.pipeline.spi.ChatPort;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Conversational access to the metric layer — routing only, never generation of figures.
 *
 * <p>The model's job on this endpoint is to turn "how did on-time arrival do for Denver in June" into
 * {@code observe(ota, office, Denver, 2026-06)}. The number that comes back is computed by the same
 * SQL that produces the dashboard value. That separation is the entire design: an endpoint that let a
 * model produce figures would be a fluent way to be confidently wrong, and it would disagree with
 * every other surface in the platform.
 *
 * <p>Because routing is small and well-bounded it runs on the cheap tier. Two rules make that safe:
 * the model may only choose from the catalog, and when it cannot map a question it must say so.
 * Declining with {@value ChatPort#DECLINE_REASON} is a first-class outcome here, not a failure — the
 * alternative is answering the nearest question the platform happens to know, which is worse than
 * saying no.
 *
 * <p>Every response carries its citations and its token cost, so a reader can re-derive any figure
 * and an operator can see what the conversation spent.
 */
@RestController
@RequestMapping("/api/chat")
@CrossOrigin
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);

    private final PortRegistry ports;
    private final MetricCatalog catalog;
    private final SenseReasonActPipeline pipeline;
    private final AuditLog auditLog;
    private final OperatorCopy copy;

    public ChatController(
            PortRegistry ports,
            MetricCatalog catalog,
            SenseReasonActPipeline pipeline,
            AuditLog auditLog,
            OperatorCopy copy) {
        this.ports = ports;
        this.catalog = catalog;
        this.pipeline = pipeline;
        this.auditLog = auditLog;
        this.copy = copy;
    }

    /**
     * A question.
     *
     * @param question the question, verbatim
     * @param period   period to assume when the question names none; optional
     */
    public record ChatRequest(String question, String period) {
    }

    /**
     * Token accounting for one question.
     *
     * @param promptTokens     prompt tokens consumed
     * @param completionTokens completion tokens produced
     * @param calls            model requests made; zero on the deterministic router
     * @param estimatedCostUsd priced spend
     */
    public record Usage(long promptTokens, long completionTokens, long calls, double estimatedCostUsd) {
    }

    /**
     * The answer.
     *
     * @param answer       the reply, or the explanation of why the question was declined
     * @param resolvedCall the metric-layer call the question mapped to, or null when declined
     * @param citations    claim-to-metric bindings for every figure quoted
     * @param usage        what the question cost
     * @param declined     true when the question fell outside the metric catalog
     * @param tier         which implementation answered — a model id, or {@code deterministic}
     * @param knownMetrics the vocabulary the endpoint can answer in, so a declined question can be
     *                     usefully rephrased rather than merely rejected
     */
    @JsonInclude(JsonInclude.Include.ALWAYS)
    public record ChatResponse(
            String answer,
            ChatPort.ResolvedCall resolvedCall,
            List<Evidence> citations,
            Usage usage,
            boolean declined,
            String tier,
            List<String> knownMetrics) {
    }

    /**
     * Answers one question against the metric catalog.
     *
     * @return 200 always — a decline is a valid answer, not an error. 400 only when the body carries
     *         no question at all.
     */
    @PostMapping
    public ChatResponse ask(@RequestBody ChatRequest request) {
        if (request == null || request.question() == null || request.question().isBlank()) {
            throw new IllegalArgumentException(
                    "A question is required, e.g. {\"question\": \"why did on-time arrival drop in June?\"}");
        }
        String defaultPeriod = request.period() != null && !request.period().isBlank()
                ? request.period().trim()
                : safeDefaultPeriod();

        ChatPort.Answer answer = ports.chat().ask(request.question(), defaultPeriod);
        if (answer == null) {
            answer = ChatPort.Answer.decline(request.question(), catalog.labels());
        }

        auditLog.record("chat", AuditLog.STAGE_DELIVER,
                List.of(describe(answer)),
                answer.citations(), List.of(), List.of("chat"),
                ports.chat().tier(),
                answer.usage().promptTokens(),
                answer.usage().completionTokens());

        log.info("Chat '{}' -> {} (tier {})",
                request.question(), describe(answer), ports.chat().tier());

        return new ChatResponse(
                copy.rewrite(answer.answer()),
                answer.resolvedCall(),
                answer.citations().stream()
                        .map(item -> new Evidence(copy.rewrite(item.claim()), item.metricId(), item.entity()))
                        .toList(),
                new Usage(
                        answer.usage().promptTokens(),
                        answer.usage().completionTokens(),
                        answer.usage().calls(),
                        answer.usage().estimatedCostUsd()),
                answer.declined(),
                ports.chat().tier(),
                catalog.labels());
    }

    /**
     * The vocabulary the chat endpoint understands.
     *
     * <p>Published deliberately: a user whose question was declined should be able to see what would
     * have worked, rather than guessing at phrasings until one lands.
     */
    @GetMapping("/capabilities")
    public ChatCapabilities capabilities() {
        return new ChatCapabilities(
                catalog.labels(),
                catalog.all().stream().map(definition ->
                        definition.id() + " — " + definition.label()).toList(),
                ports.chat().tier(),
                ChatPort.DECLINE_REASON,
                safeDefaultPeriod());
    }

    /**
     * What the chat endpoint can answer.
     *
     * @param metrics       catalog metric ids
     * @param descriptions  id and label pairs, for a picker
     * @param tier          which implementation is answering
     * @param declineReason the exact phrase used when a question cannot be mapped
     * @param defaultPeriod period assumed when a question names none
     */
    public record ChatCapabilities(
            List<String> metrics,
            List<String> descriptions,
            String tier,
            String declineReason,
            String defaultPeriod) {
    }

    private String safeDefaultPeriod() {
        try {
            return pipeline.defaultPeriod();
        } catch (RuntimeException e) {
            // No data loaded yet. The router handles a null period by falling back to whatever the
            // metric itself has, and says so when that is nothing.
            return null;
        }
    }

    private static String describe(ChatPort.Answer answer) {
        if (answer.declined() || answer.resolvedCall() == null) {
            return "declined";
        }
        ChatPort.ResolvedCall call = answer.resolvedCall();
        return call.tool() + "(" + call.metricId() + "," + call.dimension() + ","
                + call.entity() + "," + call.period() + ")";
    }
}
