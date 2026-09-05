package com.moveinsync.mi.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Sarvam via the OpenAI-compatible Chat Completions REST API.
 *
 * <p>Same adapter pattern as {@link GeminiClient}: {@code java.net.http}, no vendor SDK, failures
 * return {@code null} so the pipeline falls back to the deterministic path. The wire format is
 * {@code POST https://api.sarvam.ai/v1/chat/completions} with a Bearer token — the same shape as
 * Sarvam's documented chat-completions call.
 *
 * <p>Model ids are configuration. Sarvam currently serves {@code sarvam-105b} (and a conversational
 * variant) on this endpoint; a 404 is fixed in {@code app.llm.sarvam.*} rather than here.
 */
@Service
public class SarvamClient implements ModelClient {

    private static final Logger log = LoggerFactory.getLogger(SarvamClient.class);

    public static final String API_KEY_ENV = "SARVAM_API_KEY";
    public static final String ALT_KEY_ENV = "SARVAM_SUBSCRIPTION_KEY";

    private static final String ENDPOINT = "https://api.sarvam.ai/v1/chat/completions";

    private static final int MIN_MAX_TOKENS = 256;
    private static final int MAX_MAX_TOKENS = 8192;

    private final UsageRecorder usage;
    private final ObjectMapper json = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private final String credential;
    private final boolean enabled;
    private final String cheapModel;
    private final String midModel;
    private final String strongModel;

    /** Set permanently on an auth or quota failure, so one bad key does not retry per finding. */
    private volatile boolean disabled;
    private volatile String disabledReason;

    public SarvamClient(
            UsageRecorder usage,
            @Value("${app.llm.enabled:true}") boolean enabled,
            @Value("${app.llm.sarvam.cheap-model:sarvam-105b}") String cheapModel,
            @Value("${app.llm.sarvam.mid-model:sarvam-105b}") String midModel,
            @Value("${app.llm.sarvam.strong-model:sarvam-105b}") String strongModel) {
        this.usage = usage;
        this.enabled = enabled;
        this.cheapModel = cheapModel;
        this.midModel = midModel;
        this.strongModel = strongModel;

        String key = System.getenv(API_KEY_ENV);
        if (key == null || key.isBlank()) {
            key = System.getenv(ALT_KEY_ENV);
        }
        this.credential = key == null || key.isBlank() ? null : key.trim();

        if (this.credential != null && enabled) {
            log.info("Sarvam configured: cheap={} mid={} strong={}", cheapModel, midModel, strongModel);
        }
    }

    @Override
    public String providerName() {
        return "sarvam";
    }

    @Override
    public boolean isAvailable() {
        return enabled && credential != null && !disabled;
    }

    @Override
    public String unavailableReason() {
        if (!enabled) {
            return "app.llm.enabled is false";
        }
        if (credential == null) {
            return "no " + API_KEY_ENV + " (or " + ALT_KEY_ENV + ") in the environment";
        }
        return disabled ? disabledReason : null;
    }

    private String modelFor(ModelTier tier) {
        return switch (tier == null ? ModelTier.MID : tier) {
            case CHEAP -> cheapModel;
            case MID -> midModel;
            case STRONG -> strongModel;
        };
    }

    @Override
    public String complete(ModelTier tier, String cachedSystemPrefix, String userContent, int maxTokens) {
        ModelTier resolved = tier == null ? ModelTier.MID : tier;
        if (!isAvailable()) {
            return null;
        }
        if (userContent == null || userContent.isBlank()) {
            log.warn("Refusing to call Sarvam with empty user content");
            return null;
        }

        String model = modelFor(resolved);
        int bounded = Math.clamp(maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS);
        long startedAt = System.currentTimeMillis();

        try {
            ObjectNode body = json.createObjectNode();
            body.put("model", model);

            ArrayNode messages = body.putArray("messages");
            if (cachedSystemPrefix != null && !cachedSystemPrefix.isBlank()) {
                ObjectNode system = messages.addObject();
                system.put("role", "system");
                system.put("content", cachedSystemPrefix);
            }
            ObjectNode user = messages.addObject();
            user.put("role", "user");
            user.put("content", userContent);

            body.put("max_tokens", bounded);
            body.put("temperature", 0.2);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(ENDPOINT))
                    .timeout(Duration.ofSeconds(120))
                    .header("Authorization", "Bearer " + credential)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                    .build();

            HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
            long elapsed = System.currentTimeMillis() - startedAt;

            if (response.statusCode() != 200) {
                handleError(resolved, model, response.statusCode(), response.body(), elapsed);
                return null;
            }

            JsonNode root = json.readTree(response.body());
            recordUsage(resolved, root.path("usage"));

            JsonNode choice = root.path("choices").path(0);
            String finishReason = choice.path("finish_reason").asText("");
            if ("length".equals(finishReason)) {
                log.warn("Sarvam {} hit the output ceiling after {} ms; treating as a failure.",
                        model, elapsed);
                usage.recordFailure(resolved);
                return null;
            }
            if ("content_filter".equals(finishReason)) {
                log.warn("Sarvam {} declined the request ({}); falling back.", model, finishReason);
                usage.recordFailure(resolved);
                return null;
            }

            String text = extractText(choice.path("message").path("content"));
            if (text == null || text.isBlank()) {
                log.warn("Sarvam {} returned no text after {} ms; falling back.", model, elapsed);
                usage.recordFailure(resolved);
                return null;
            }

            log.debug("Sarvam {} responded in {} ms ({} chars)", model, elapsed, text.length());
            return text;

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            usage.recordFailure(resolved);
            return null;
        } catch (Exception e) {
            log.warn("Sarvam {} call failed after {} ms: {}. Falling back to the deterministic path.",
                    model, System.currentTimeMillis() - startedAt, e.toString());
            usage.recordFailure(resolved);
            return null;
        }
    }

    private static String extractText(JsonNode content) {
        if (content == null || content.isMissingNode() || content.isNull()) {
            return null;
        }
        if (content.isTextual()) {
            return content.asText();
        }
        if (content.isArray()) {
            StringBuilder text = new StringBuilder();
            for (JsonNode part : content) {
                if (part.isTextual()) {
                    text.append(part.asText());
                } else {
                    String chunk = part.path("text").asText(null);
                    if (chunk != null) {
                        text.append(chunk);
                    }
                }
            }
            return text.isEmpty() ? null : text.toString();
        }
        String nested = content.path("text").asText(null);
        return nested;
    }

    private void handleError(ModelTier tier, String model, int status, String body, long elapsed) {
        usage.recordFailure(tier);
        String detail = body == null ? "" : body.replaceAll("\\s+", " ").trim();
        if (detail.length() > 400) {
            detail = detail.substring(0, 400) + "…";
        }

        String lower = detail.toLowerCase(Locale.ROOT);
        if (status == 401 || status == 403
                || (status == 400 && lower.contains("api key"))) {
            disabled = true;
            disabledReason = "Sarvam denied access (HTTP " + status + ") — check SARVAM_API_KEY";
        } else if (status == 404) {
            disabled = true;
            disabledReason = "Sarvam model '" + model + "' was not found — set app.llm.sarvam.* in "
                    + "application.yml to a model your key can reach";
        } else if (status == 429) {
            disabled = true;
            disabledReason = "Sarvam rate limit reached; the run continues deterministically";
        }

        log.warn("Sarvam {} failed after {} ms: HTTP {} {}{}",
                model, elapsed, status, detail,
                disabled ? " — LLM layer disabled for this process: " + disabledReason : "");
    }

    private void recordUsage(ModelTier tier, JsonNode usageNode) {
        if (usageNode == null || usageNode.isMissingNode()) {
            return;
        }
        long in = usageNode.path("prompt_tokens").asLong(0L);
        long out = usageNode.path("completion_tokens").asLong(0L);
        usage.record(tier, Math.max(0L, in), out, 0L, 0L);
    }
}
