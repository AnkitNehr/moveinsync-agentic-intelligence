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
 * Google Gemini via the Generative Language REST API.
 *
 * <p>Deliberately written against {@code java.net.http} rather than a vendor SDK. It adds no Maven
 * dependency, the request shape is four fields, and it keeps the demonstration honest: the claim
 * has been that swapping providers is one adapter, and this file is that claim being cashed rather
 * than asserted.
 *
 * <p>Gemini is here because it has a genuinely free tier. That matters more than it sounds: a
 * system whose agentic layer only works on a funded account is a system most teams cannot run.
 *
 * <p>Model ids are configuration, not constants. Google renames and retires these faster than a
 * compiled default can track, so {@code app.llm.gemini.*} in application.yml is the place to fix a
 * 404 rather than this file.
 */
@Service
public class GeminiClient implements ModelClient {

    private static final Logger log = LoggerFactory.getLogger(GeminiClient.class);

    public static final String API_KEY_ENV = "GEMINI_API_KEY";
    public static final String ALT_KEY_ENV = "GOOGLE_API_KEY";

    private static final String ENDPOINT =
            "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent";

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

    public GeminiClient(
            UsageRecorder usage,
            @Value("${app.llm.enabled:true}") boolean enabled,
            @Value("${app.llm.gemini.cheap-model:gemini-2.0-flash}") String cheapModel,
            @Value("${app.llm.gemini.mid-model:gemini-2.0-flash}") String midModel,
            @Value("${app.llm.gemini.strong-model:gemini-2.5-flash}") String strongModel) {
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
            log.info("Gemini configured: cheap={} mid={} strong={}", cheapModel, midModel, strongModel);
        }
    }

    @Override
    public String providerName() {
        return "gemini";
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
            log.warn("Refusing to call Gemini with empty user content");
            return null;
        }

        String model = modelFor(resolved);
        int bounded = Math.clamp(maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS);
        long startedAt = System.currentTimeMillis();

        try {
            ObjectNode body = json.createObjectNode();

            ArrayNode contents = body.putArray("contents");
            ObjectNode turn = contents.addObject();
            turn.put("role", "user");
            turn.putArray("parts").addObject().put("text", userContent);

            if (cachedSystemPrefix != null && !cachedSystemPrefix.isBlank()) {
                body.putObject("systemInstruction")
                        .putArray("parts")
                        .addObject()
                        .put("text", cachedSystemPrefix);
            }

            ObjectNode config = body.putObject("generationConfig");
            config.put("maxOutputTokens", bounded);
            // Every prompt in this system asks for strict JSON or plain markdown and forbids
            // invented figures. Low temperature is the right default for both.
            config.put("temperature", 0.2);

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(ENDPOINT.formatted(model)))
                    .timeout(Duration.ofSeconds(120))
                    .header("Content-Type", "application/json")
                    .header("x-goog-api-key", credential)
                    .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                    .build();

            HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
            long elapsed = System.currentTimeMillis() - startedAt;

            if (response.statusCode() != 200) {
                handleError(resolved, model, response.statusCode(), response.body(), elapsed);
                return null;
            }

            JsonNode root = json.readTree(response.body());
            recordUsage(resolved, root.path("usageMetadata"));

            JsonNode candidate = root.path("candidates").path(0);
            String finishReason = candidate.path("finishReason").asText("");
            if ("MAX_TOKENS".equals(finishReason)) {
                // A truncated reply is unusable: half a JSON object parses to nothing, and half a
                // narrative would ship with a sentence cut mid-number.
                log.warn("Gemini {} hit the output ceiling after {} ms; treating as a failure.",
                        model, elapsed);
                usage.recordFailure(resolved);
                return null;
            }
            if ("SAFETY".equals(finishReason) || "PROHIBITED_CONTENT".equals(finishReason)) {
                log.warn("Gemini {} declined the request ({}); falling back.", model, finishReason);
                usage.recordFailure(resolved);
                return null;
            }

            StringBuilder text = new StringBuilder();
            for (JsonNode part : candidate.path("content").path("parts")) {
                String chunk = part.path("text").asText(null);
                if (chunk != null) {
                    text.append(chunk);
                }
            }

            if (text.isEmpty()) {
                log.warn("Gemini {} returned no text after {} ms; falling back.", model, elapsed);
                usage.recordFailure(resolved);
                return null;
            }

            log.debug("Gemini {} responded in {} ms ({} chars)", model, elapsed, text.length());
            return text.toString();

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            usage.recordFailure(resolved);
            return null;
        } catch (Exception e) {
            log.warn("Gemini {} call failed after {} ms: {}. Falling back to the deterministic path.",
                    model, System.currentTimeMillis() - startedAt, e.toString());
            usage.recordFailure(resolved);
            return null;
        }
    }

    /**
     * Distinguishes a permanently broken configuration from a transient one. A bad key or an
     * exhausted quota will fail identically on every subsequent finding, so the client disables
     * itself rather than making the same doomed call twenty more times in one run.
     */
    private void handleError(ModelTier tier, String model, int status, String body, long elapsed) {
        usage.recordFailure(tier);
        String detail = body == null ? "" : body.replaceAll("\\s+", " ").trim();
        if (detail.length() > 400) {
            detail = detail.substring(0, 400) + "…";
        }

        if (status == 400 && detail.toLowerCase(Locale.ROOT).contains("api key not valid")) {
            disabled = true;
            disabledReason = "Gemini rejected the API key as invalid";
        } else if (status == 401 || status == 403) {
            disabled = true;
            disabledReason = "Gemini denied access (HTTP " + status + ") — check the key and that the "
                    + "Generative Language API is enabled for the project";
        } else if (status == 404) {
            disabled = true;
            disabledReason = "Gemini model '" + model + "' was not found — set app.llm.gemini.* in "
                    + "application.yml to a model your key can reach";
        } else if (status == 429) {
            disabled = true;
            disabledReason = "Gemini free-tier rate limit reached; the run continues deterministically";
        }

        log.warn("Gemini {} failed after {} ms: HTTP {} {}{}",
                model, elapsed, status, detail,
                disabled ? " — LLM layer disabled for this process: " + disabledReason : "");
    }

    /**
     * Records tokens against the tier's Claude price so the run summary keeps one comparable cost
     * figure. Gemini's free tier bills nothing, so treat the number as "what this run would have
     * cost on the paid path" rather than as an invoice.
     */
    private void recordUsage(ModelTier tier, JsonNode usageMetadata) {
        if (usageMetadata == null || usageMetadata.isMissingNode()) {
            return;
        }
        long in = usageMetadata.path("promptTokenCount").asLong(0L);
        long out = usageMetadata.path("candidatesTokenCount").asLong(0L);
        long cached = usageMetadata.path("cachedContentTokenCount").asLong(0L);
        usage.record(tier, Math.max(0L, in - cached), out, cached, 0L);
    }
}
