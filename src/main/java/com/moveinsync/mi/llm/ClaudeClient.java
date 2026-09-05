package com.moveinsync.mi.llm;

import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import com.anthropic.errors.AnthropicServiceException;
import com.anthropic.models.messages.CacheControlEphemeral;
import com.anthropic.models.messages.Message;
import com.anthropic.models.messages.MessageCreateParams;
import com.anthropic.models.messages.StopReason;
import com.anthropic.models.messages.TextBlockParam;
import com.anthropic.models.messages.Usage;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * The single egress point to the Anthropic API, and the single place LLM failure is absorbed.
 *
 * <h2>Graceful degradation is a designed feature, not an accident</h2>
 *
 * <p>This platform's numbers, rankings, attributions and SLA verdicts are all produced by
 * deterministic code. The model layer clusters, explains and phrases — it never decides whether
 * something breached, and it never computes a figure. That separation is what makes it safe for
 * this class to return {@code null} instead of throwing when the API is unreachable, the key is
 * missing, or {@code app.llm.enabled=false}: every caller has a deterministic fallback, so a
 * degraded run produces terser output rather than no output.
 *
 * <p>Concretely, with no {@code ANTHROPIC_API_KEY} set the whole application still boots, ingests,
 * scans, attributes, applies SLA policy, clusters incidents and renders templated narratives. That
 * is a deliberate property: an operations tool that goes dark when a third-party API has a bad
 * afternoon is not an operations tool.
 *
 * <h2>Prompt shape</h2>
 *
 * <p>Every call sends the same byte-identical system prefix (see {@code CachedPrefixBuilder}) with a
 * cache breakpoint on it, and puts all volatile content — the findings, the incident, the persona
 * instruction — in the user turn. Render order is tools, then system, then messages, so a prefix
 * that never changes is a prefix that is read from cache on every call after the first.
 *
 * <h2>Sampling parameters</h2>
 *
 * <p>{@code temperature}, {@code top_p} and {@code top_k} are deliberately never set. They are
 * removed on the model ids in {@link ModelTier} and sending any of them returns a 400.
 */
@Service
public class ClaudeClient implements ModelClient {

    private static final Logger log = LoggerFactory.getLogger(ClaudeClient.class);

    @Override
    public String providerName() {
        return "anthropic";
    }

    /** Environment variable the SDK reads for the API key. */
    public static final String API_KEY_ENV = "ANTHROPIC_API_KEY";

    /** Alternative credential env var, honoured by the SDK's credential chain. */
    public static final String AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN";

    /** Lower bound on {@code max_tokens}; a truncated JSON reply is worse than a slightly larger bill. */
    private static final int MIN_MAX_TOKENS = 256;

    /** Upper bound on {@code max_tokens} for this application's non-streaming calls. */
    private static final int MAX_MAX_TOKENS = 16_000;

    private final UsageRecorder usage;
    private final boolean enabled;
    private final boolean credentialPresent;
    private final String unavailableReason;

    private final Object clientLock = new Object();
    private volatile AnthropicClient client;
    /** Set when client construction failed; stops us retrying a doomed build on every call. */
    private volatile boolean clientUnbuildable;

    /**
     * Spring constructor.
     *
     * <p>Explicitly {@link Autowired} because this class exposes two public constructors. With more
     * than one candidate and no annotation, Spring falls back to a no-arg constructor that does not
     * exist and the context fails to start — so the annotation is load-bearing, not decoration.
     *
     * @param usage   usage recorder that accumulates tokens and cost for the run
     * @param enabled {@code app.llm.enabled}; false forces fully deterministic operation
     */
    @Autowired
    public ClaudeClient(UsageRecorder usage, @Value("${app.llm.enabled:true}") boolean enabled) {
        this(usage, enabled, firstNonBlank(System.getenv(API_KEY_ENV), System.getenv(AUTH_TOKEN_ENV)));
    }

    /**
     * Constructor used by tests, which must be able to assert the degraded path without mutating the
     * process environment.
     *
     * <p>The credential is used only to decide availability. The client itself is always built with
     * {@link AnthropicOkHttpClient#fromEnv()} so the SDK's full credential chain — API key, auth
     * token, OAuth profile, workload identity — applies exactly as documented, rather than being
     * second-guessed here.
     *
     * @param usage      usage recorder
     * @param enabled    feature flag
     * @param credential credential value if one is visible, or null
     */
    public ClaudeClient(UsageRecorder usage, boolean enabled, String credential) {
        this.usage = usage;
        this.enabled = enabled;
        this.credentialPresent = credential != null && !credential.isBlank();

        if (!enabled) {
            this.unavailableReason = "app.llm.enabled=false";
        } else if (!credentialPresent) {
            this.unavailableReason = "no " + API_KEY_ENV + " (or " + AUTH_TOKEN_ENV + ") in the environment";
        } else {
            this.unavailableReason = null;
        }

        if (unavailableReason != null) {
            log.warn("LLM layer DISABLED: {}. The platform will run fully deterministically: ingest, scan, "
                    + "attribution, SLA policy and incident clustering are unaffected; explanations and "
                    + "narratives fall back to templates built from the computed contributions.", unavailableReason);
        } else {
            log.info("LLM layer enabled (tiers: cheap={}, mid={}, strong={})",
                    ModelTier.CHEAP.modelId(), ModelTier.MID.modelId(), ModelTier.STRONG.modelId());
        }
    }

    private static String firstNonBlank(String a, String b) {
        if (a != null && !a.isBlank()) {
            return a;
        }
        return b != null && !b.isBlank() ? b : null;
    }

    /**
     * Whether model calls will be attempted.
     *
     * <p>Callers should branch on this <em>before</em> building an expensive prompt, and must still
     * handle a null return from {@link #complete} — availability is checked up front but the network
     * can fail at any point after that.
     */
    public boolean isAvailable() {
        return enabled && credentialPresent && !clientUnbuildable;
    }

    /** Human-readable reason the LLM layer is off, or null when it is on. For health endpoints. */
    public String unavailableReason() {
        if (clientUnbuildable) {
            return "Anthropic client could not be constructed";
        }
        return unavailableReason;
    }

    /**
     * Sends one non-streaming completion request.
     *
     * @param tier               model tier; selects the model id and the price book
     * @param cachedSystemPrefix byte-identical system prefix, marked with a cache breakpoint
     * @param userContent        the volatile half of the prompt: findings, incident, persona ask
     * @param maxTokens          output ceiling, clamped to [{@value #MIN_MAX_TOKENS}, {@value #MAX_MAX_TOKENS}]
     * @return the concatenated text blocks of the reply, or {@code null} when the LLM layer is
     *         unavailable, the call failed, or the reply was truncated by {@code max_tokens} —
     *         every one of which the caller must treat as "use the deterministic path"
     */
    public String complete(ModelTier tier, String cachedSystemPrefix, String userContent, int maxTokens) {
        ModelTier resolved = tier == null ? ModelTier.MID : tier;

        if (!isAvailable()) {
            return null;
        }
        if (userContent == null || userContent.isBlank()) {
            log.warn("Refusing to call {} with empty user content", resolved.modelId());
            return null;
        }

        AnthropicClient anthropic = client();
        if (anthropic == null) {
            return null;
        }

        int bounded = Math.clamp(maxTokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS);
        long startedAt = System.currentTimeMillis();

        try {
            MessageCreateParams.Builder params = MessageCreateParams.builder()
                    .model(resolved.modelId())
                    .maxTokens((long) bounded)
                    .addUserMessage(userContent);

            if (cachedSystemPrefix != null && !cachedSystemPrefix.isBlank()) {
                // One breakpoint on the last (only) system block. Tools render before system, and we
                // send none, so this caches the entire prefix.
                params.systemOfTextBlockParams(List.of(TextBlockParam.builder()
                        .text(cachedSystemPrefix)
                        .cacheControl(CacheControlEphemeral.builder().build())
                        .build()));
            }

            Message response = anthropic.messages().create(params.build());
            recordUsage(resolved, response.usage());

            StringBuilder text = new StringBuilder();
            response.content().stream()
                    .flatMap(block -> block.text().stream())
                    .forEach(block -> text.append(block.text()));

            boolean truncated = response.stopReason()
                    .map(reason -> reason.equals(StopReason.MAX_TOKENS))
                    .orElse(false);
            if (truncated) {
                // A JSON reply cut off mid-object parses as garbage and would otherwise be "repaired"
                // into something the model never said. Refusing it sends the caller to the template.
                log.warn("{} hit max_tokens ({}) after {} ms; discarding truncated reply and falling back",
                        resolved.modelId(), bounded, System.currentTimeMillis() - startedAt);
                usage.recordFailure(resolved);
                return null;
            }

            if (text.isEmpty()) {
                log.warn("{} returned no text blocks (stop_reason={})", resolved.modelId(),
                        response.stopReason().map(Object::toString).orElse("none"));
                usage.recordFailure(resolved);
                return null;
            }

            log.debug("{} responded in {} ms ({} chars)",
                    resolved.modelId(), System.currentTimeMillis() - startedAt, text.length());
            return text.toString();

        } catch (AnthropicServiceException e) {
            usage.recordFailure(resolved);
            log.warn("{} call failed after {} ms: {} ({}). Falling back to the deterministic path.",
                    resolved.modelId(), System.currentTimeMillis() - startedAt,
                    e.getMessage(), e.errorType().map(Object::toString).orElse("unknown"));
            return null;
        } catch (RuntimeException e) {
            // Transport failures, timeouts, deserialisation problems. The contract of this method is
            // that it never propagates an LLM problem into the deterministic pipeline.
            usage.recordFailure(resolved);
            log.warn("{} call failed after {} ms: {}. Falling back to the deterministic path.",
                    resolved.modelId(), System.currentTimeMillis() - startedAt, e.toString());
            return null;
        }
    }

    private void recordUsage(ModelTier tier, Usage apiUsage) {
        if (apiUsage == null) {
            return;
        }
        usage.record(
                tier,
                apiUsage.inputTokens(),
                apiUsage.outputTokens(),
                apiUsage.cacheReadInputTokens().orElse(0L),
                apiUsage.cacheCreationInputTokens().orElse(0L));
    }

    /**
     * Lazily builds the SDK client.
     *
     * <p>Construction is deferred so that an application with no credentials starts cleanly, and it
     * is attempted at most once — a failure sets {@link #clientUnbuildable}, which permanently flips
     * {@link #isAvailable()} to false rather than re-throwing on every finding in the run.
     */
    private AnthropicClient client() {
        AnthropicClient existing = client;
        if (existing != null) {
            return existing;
        }
        synchronized (clientLock) {
            if (client != null) {
                return client;
            }
            if (clientUnbuildable) {
                return null;
            }
            try {
                client = AnthropicOkHttpClient.fromEnv();
                log.info("Anthropic client initialised");
                return client;
            } catch (RuntimeException e) {
                clientUnbuildable = true;
                log.warn("Could not initialise the Anthropic client ({}). The LLM layer is now off for this "
                        + "process; the deterministic pipeline continues unaffected.", e.toString());
                return null;
            }
        }
    }

    // ---- reply parsing helpers ------------------------------------------------------------------

    /**
     * Extracts the first balanced JSON object from a model reply.
     *
     * <p>Every agent in this package asks for strict JSON, and the models comply the overwhelming
     * majority of the time. This exists for the remainder: a fenced block, or a sentence of preamble
     * before the object. Scanning for a balanced brace pair — while respecting string literals and
     * escapes, so a {@code "}"} inside a title does not end the object early — recovers those
     * without a regex that would mis-handle nesting.
     *
     * @param raw model reply, may be null
     * @return the JSON object substring, or null when the reply contains no balanced object
     */
    public static String extractJsonObject(String raw) {
        if (raw == null) {
            return null;
        }
        int start = raw.indexOf('{');
        if (start < 0) {
            return null;
        }

        int depth = 0;
        boolean inString = false;
        boolean escaped = false;

        for (int i = start; i < raw.length(); i++) {
            char c = raw.charAt(i);

            if (inString) {
                if (escaped) {
                    escaped = false;
                } else if (c == '\\') {
                    escaped = true;
                } else if (c == '"') {
                    inString = false;
                }
                continue;
            }

            if (c == '"') {
                inString = true;
            } else if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return raw.substring(start, i + 1);
                }
            }
        }
        return null;
    }

    /** Convenience wrapper so callers can express "no reply" and "no JSON in the reply" identically. */
    public static Optional<String> jsonOf(String raw) {
        return Optional.ofNullable(extractJsonObject(raw));
    }
}
