package com.moveinsync.mi.pipeline.spi;

import org.springframework.beans.factory.ObjectProvider;

/**
 * Deterministic selection between an optional LLM-backed port and its guaranteed fallback.
 *
 * <p>Both implementations are Spring beans of the same interface type, so
 * {@code ObjectProvider.getIfAvailable()} would throw on ambiguity and {@code @ConditionalOnMissingBean}
 * on component-scanned classes is evaluated in an order Spring does not guarantee. Selecting by
 * identity avoids both problems: iterate the candidates, skip the known fallback, take the first
 * thing that is left. The result is the same on every boot, which matters because "which stage ran
 * deterministically" is recorded in the audit trail.
 */
public final class Ports {

    private Ports() {
    }

    /**
     * Picks the LLM-backed implementation when one is registered, otherwise the fallback.
     *
     * @param provider all beans implementing the port, including {@code fallback}
     * @param fallback the deterministic implementation, always present
     * @param <T>      port type
     * @return the selected implementation; never null
     */
    public static <T> T select(ObjectProvider<T> provider, T fallback) {
        if (provider == null) {
            return fallback;
        }
        return provider.orderedStream()
                .filter(candidate -> candidate != fallback)
                .findFirst()
                .orElse(fallback);
    }

    /**
     * Whether a non-fallback implementation is registered.
     *
     * @param provider all beans implementing the port
     * @param fallback the deterministic implementation
     * @param <T>      port type
     * @return true when an LLM-backed implementation would be selected
     */
    public static <T> boolean hasOverride(ObjectProvider<T> provider, T fallback) {
        return select(provider, fallback) != fallback;
    }
}
