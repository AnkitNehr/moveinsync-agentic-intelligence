package com.moveinsync.mi.llm;

import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

/**
 * Picks whichever provider can actually serve this process, and is the only {@link ModelClient} the
 * agents ever see.
 *
 * <p>Selection is by credential, not by preference: whichever provider has a usable key wins, and
 * if both do the order below decides. That makes the provider an environment variable rather than a
 * deployment — the same jar runs on Anthropic in one environment and Gemini in another with no
 * rebuild, which is the property the architecture has been claiming all along. Sarvam is the same
 * swap for an OpenAI-compatible Indic endpoint.
 *
 * <p>If none is available every agentic stage degrades to its deterministic implementation and the
 * pipeline still completes. That is not a failure mode bolted on afterwards; it is the reason the
 * deterministic core computes every number in the first place.
 */
@Service
@Primary
public class ModelClientRouter implements ModelClient {

    private static final Logger log = LoggerFactory.getLogger(ModelClientRouter.class);

    /** A no-op used when nothing is configured, so callers never handle a null client. */
    private static final ModelClient NONE = new ModelClient() {
        @Override
        public boolean isAvailable() {
            return false;
        }

        @Override
        public String unavailableReason() {
            return "no model provider is configured (set ANTHROPIC_API_KEY, GEMINI_API_KEY or SARVAM_API_KEY)";
        }

        @Override
        public String complete(ModelTier tier, String prefix, String user, int maxTokens) {
            return null;
        }

        @Override
        public String providerName() {
            return "none";
        }
    };

    private final List<ModelClient> candidates;

    public ModelClientRouter(ClaudeClient claude, GeminiClient gemini, SarvamClient sarvam) {
        // Anthropic first when more than one provider is funded: the prompts, the cache breakpoint
        // and the tier price table were all written against it. Gemini and Sarvam keep the agentic
        // layer alive when Anthropic is not configured.
        this.candidates = List.of(claude, gemini, sarvam);

        ModelClient active = active();
        if (active == NONE) {
            log.warn("No LLM provider available: {}. Every agentic stage will run deterministically — "
                    + "ingest, metrics, benchmarks, attribution, policy and incidents are unaffected.",
                    NONE.unavailableReason());
        } else {
            log.info("LLM provider: {} (candidates checked: {})",
                    active.providerName(),
                    candidates.stream().map(ModelClient::providerName).toList());
            candidates.stream()
                    .filter(c -> c != active && !c.isAvailable())
                    .forEach(c -> log.info("  {} unavailable: {}", c.providerName(), c.unavailableReason()));
        }
    }

    /** Re-evaluated per call: a provider can disable itself mid-run on a quota or auth failure. */
    private ModelClient active() {
        for (ModelClient candidate : candidates) {
            if (candidate.isAvailable()) {
                return candidate;
            }
        }
        return NONE;
    }

    @Override
    public boolean isAvailable() {
        return active() != NONE;
    }

    @Override
    public String unavailableReason() {
        ModelClient active = active();
        if (active != NONE) {
            return null;
        }
        StringBuilder reason = new StringBuilder();
        for (ModelClient candidate : candidates) {
            if (!reason.isEmpty()) {
                reason.append("; ");
            }
            reason.append(candidate.providerName()).append(": ").append(candidate.unavailableReason());
        }
        return reason.isEmpty() ? NONE.unavailableReason() : reason.toString();
    }

    @Override
    public String providerName() {
        return active().providerName();
    }

    @Override
    public String complete(ModelTier tier, String cachedSystemPrefix, String userContent, int maxTokens) {
        ModelClient chosen = active();
        if (chosen == NONE) {
            return null;
        }
        String out = chosen.complete(tier, cachedSystemPrefix, userContent, maxTokens);
        if (out != null) {
            return out;
        }
        // The chosen provider may have disabled itself on this very call (bad key, exhausted quota).
        // Try the next one that is still standing before giving up on the model layer entirely.
        for (ModelClient candidate : candidates) {
            if (candidate != chosen && candidate.isAvailable()) {
                log.info("{} failed; retrying on {}.", chosen.providerName(), candidate.providerName());
                return candidate.complete(tier, cachedSystemPrefix, userContent, maxTokens);
            }
        }
        return null;
    }
}
