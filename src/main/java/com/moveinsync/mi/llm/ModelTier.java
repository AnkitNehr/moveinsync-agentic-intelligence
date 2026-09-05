package com.moveinsync.mi.llm;

import java.util.Locale;

/**
 * The three model tiers this platform is allowed to spend money on, and what each costs.
 *
 * <p>Tiering is a cost-control decision, not a stylistic one. The agentic layer runs over at most
 * {@code app.ranking.top-n} findings per night, and the three stages have genuinely different
 * difficulty profiles:
 *
 * <ul>
 *   <li>{@link #CHEAP} — conversational lookups over an already-computed metric. The numbers are
 *       supplied; the model only has to phrase them.
 *   <li>{@link #MID} — triage. One batched call that clusters and dedupes an already-ranked list.
 *       Structural work over structured input, where a frontier model buys nothing.
 *   <li>{@link #STRONG} — causal reasoning and stakeholder narrative. These are the two stages a
 *       reader will actually judge the system on, and the only two worth Opus-tier money.
 * </ul>
 *
 * <p>Prices are USD per million tokens, as published for these model ids. They live on the enum
 * rather than in configuration on purpose: a run's estimated cost is an audit artefact, and it must
 * not silently change because someone edited a YAML file. When Anthropic changes list prices this
 * enum is the single place to update, and the diff is reviewable.
 *
 * <h2>Cache accounting</h2>
 *
 * <p>Cached prompt tokens are not billed at the base input rate. A cache <em>read</em> is charged at
 * roughly a tenth of the base rate and a cache <em>write</em> at roughly 1.25x, which is why the
 * whole design pushes the metric catalog, the persona guides and the SLA configuration into a
 * byte-identical prefix (see {@code CachedPrefixBuilder}). {@link UsageRecorder} applies these
 * multipliers so the reported spend reflects what caching actually saved rather than pretending
 * every prompt token cost full price.
 */
public enum ModelTier {

    /** Haiku 4.5 — conversational Q&A over numbers the deterministic layer already computed. */
    CHEAP("claude-haiku-4-5", 1.00, 5.00),

    /** Sonnet 5 — one batched triage call: cluster, dedupe, suppress. */
    MID("claude-sonnet-5", 3.00, 15.00),

    /** Opus 5 — causal explanation and stakeholder narrative, one call per promoted incident. */
    STRONG("claude-opus-5", 5.00, 25.00);

    /** Cache reads bill at roughly a tenth of the base input rate. */
    public static final double CACHE_READ_MULTIPLIER = 0.10;

    /** Cache writes bill at roughly 1.25x the base input rate (5-minute TTL). */
    public static final double CACHE_WRITE_MULTIPLIER = 1.25;

    /** Tokens per pricing unit. */
    private static final double TOKENS_PER_MILLION = 1_000_000.0;

    private final String modelId;
    private final double inputUsdPerMTok;
    private final double outputUsdPerMTok;

    ModelTier(String modelId, double inputUsdPerMTok, double outputUsdPerMTok) {
        this.modelId = modelId;
        this.inputUsdPerMTok = inputUsdPerMTok;
        this.outputUsdPerMTok = outputUsdPerMTok;
    }

    /** Exact model id sent on the wire. Never construct these strings by hand elsewhere. */
    public String modelId() {
        return modelId;
    }

    /** List price per million input tokens, USD. */
    public double inputUsdPerMTok() {
        return inputUsdPerMTok;
    }

    /** List price per million output tokens, USD. */
    public double outputUsdPerMTok() {
        return outputUsdPerMTok;
    }

    /**
     * Estimated USD cost of one call, with cache-aware input pricing.
     *
     * @param inputTokens         uncached prompt tokens billed at the base rate
     * @param outputTokens        completion tokens
     * @param cacheReadTokens     prompt tokens served from cache
     * @param cacheCreationTokens prompt tokens written to cache on this call
     * @return estimated spend in USD; negative counts are clamped to zero
     */
    public double costUsd(long inputTokens, long outputTokens, long cacheReadTokens, long cacheCreationTokens) {
        double input = Math.max(0L, inputTokens) * inputUsdPerMTok;
        double cacheRead = Math.max(0L, cacheReadTokens) * inputUsdPerMTok * CACHE_READ_MULTIPLIER;
        double cacheWrite = Math.max(0L, cacheCreationTokens) * inputUsdPerMTok * CACHE_WRITE_MULTIPLIER;
        double output = Math.max(0L, outputTokens) * outputUsdPerMTok;
        return (input + cacheRead + cacheWrite + output) / TOKENS_PER_MILLION;
    }

    /**
     * Resolves a tier from a model id or a tier name.
     *
     * <p>Accepts both {@code "claude-opus-5"} and {@code "STRONG"} so a configured model name and a
     * tier constant resolve identically. Unknown values fall back to {@link #MID} rather than
     * throwing — an unrecognised model id in configuration should degrade the tier, not take the
     * whole run down.
     *
     * @param value model id or tier name, may be null
     * @return the matching tier, or {@link #MID} when unresolvable
     */
    public static ModelTier resolve(String value) {
        if (value == null || value.isBlank()) {
            return MID;
        }
        String needle = value.trim().toLowerCase(Locale.ROOT);
        for (ModelTier tier : values()) {
            if (tier.modelId.equals(needle) || tier.name().toLowerCase(Locale.ROOT).equals(needle)) {
                return tier;
            }
        }
        return MID;
    }
}
