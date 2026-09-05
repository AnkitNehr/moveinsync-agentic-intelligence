package com.moveinsync.mi.llm;

/**
 * The one seam between the agents and whoever is actually generating text.
 *
 * <p>Every agent depends on this interface and nothing else, which is what makes the provider a
 * deployment decision rather than an architectural one. Swapping Anthropic for Gemini — or for a
 * self-hosted model behind an OpenAI-compatible endpoint — is one implementation of four methods;
 * no agent, no prompt and no validator changes.
 *
 * <p>The contract that matters is the return value of {@link #complete}: {@code null} means "use
 * the deterministic path". Implementations must never throw for an operational failure — no
 * credential, no credit, a rate limit, a timeout, a malformed reply. A pipeline that dies because a
 * third-party API had a bad minute is not an agentic system, it is a liability.
 */
public interface ModelClient {

    /** Whether calls can be attempted at all. False disables every agentic stage cleanly. */
    boolean isAvailable();

    /** Human-readable explanation when {@link #isAvailable()} is false; null when it is true. */
    String unavailableReason();

    /**
     * Generates a completion.
     *
     * @param tier               the capability/cost tier; implementations map it to their own models
     * @param cachedSystemPrefix the stable system prefix, cached where the provider supports it
     * @param userContent        the volatile per-call payload
     * @param maxTokens          output ceiling
     * @return the reply text, or {@code null} for any failure — the caller falls back
     */
    String complete(ModelTier tier, String cachedSystemPrefix, String userContent, int maxTokens);

    /** Provider identity for logs, the health endpoint and the run summary. */
    String providerName();
}
