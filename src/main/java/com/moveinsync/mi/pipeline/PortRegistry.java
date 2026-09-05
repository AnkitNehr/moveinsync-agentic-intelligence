package com.moveinsync.mi.pipeline;

import com.moveinsync.mi.attribution.AttributionService;
import com.moveinsync.mi.benchmark.BenchmarkService;
import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricQueryService;
import com.moveinsync.mi.pipeline.fallback.BuiltInChatRouter;
import com.moveinsync.mi.pipeline.fallback.BuiltInNarrator;
import com.moveinsync.mi.pipeline.fallback.DeterministicReasoner;
import com.moveinsync.mi.pipeline.fallback.DeterministicTriage;
import com.moveinsync.mi.pipeline.spi.ChatPort;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import com.moveinsync.mi.pipeline.spi.ReasoningPort;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

/**
 * Resolves, once at startup, which implementation of each agentic port the platform will use.
 *
 * <h2>Why this exists</h2>
 *
 * <p>Each of the four agentic stages has two possible implementations: an LLM-backed one and a
 * deterministic one. Letting Spring choose between them by type is not safe — two beans of the same
 * interface make {@code getIfAvailable()} throw, and {@code @ConditionalOnMissingBean} on
 * component-scanned classes is evaluated in an order Spring does not guarantee. Selecting here, by an
 * explicit rule, means the answer to "did triage run on a model or on templates?" is the same on
 * every boot and is recorded in the audit trail rather than inferred from behaviour.
 *
 * <h2>The rule</h2>
 *
 * <p>Among the registered beans for a port, prefer one whose {@code tier()} is not
 * {@value #DETERMINISTIC_TIER}; failing that take any registered bean; failing that use the built-in
 * fallback. The tier string is the ports' own self-description, so this needs no marker interface and
 * no bean naming convention, and a newly added LLM implementation is picked up with no change here.
 *
 * <p>The narrative and chat fallbacks are constructed rather than injected. They are plain objects,
 * not beans, precisely so they can never compete for injection with a real implementation — which
 * would reintroduce the ambiguity this class exists to remove.
 */
@Component
public class PortRegistry {

    private static final Logger log = LoggerFactory.getLogger(PortRegistry.class);

    /** Tier label every deterministic implementation reports. */
    public static final String DETERMINISTIC_TIER = "deterministic";

    private final TriagePort triage;
    private final ReasoningPort reasoning;
    private final NarrativePort narrative;
    private final ChatPort chat;

    public PortRegistry(
            ObjectProvider<TriagePort> triageProvider,
            ObjectProvider<ReasoningPort> reasoningProvider,
            ObjectProvider<NarrativePort> narrativeProvider,
            ObjectProvider<ChatPort> chatProvider,
            DeterministicTriage deterministicTriage,
            DeterministicReasoner deterministicReasoner,
            MetricCatalog catalog,
            MetricQueryService metrics,
            BenchmarkService benchmarks,
            AttributionService attribution,
            MetricFormat format) {

        this.triage = select("triage", triageProvider, TriagePort::tier, deterministicTriage);
        this.reasoning = select("reason", reasoningProvider, ReasoningPort::tier, deterministicReasoner);
        this.narrative = select("narrate", narrativeProvider, NarrativePort::tier,
                new BuiltInNarrator(format));
        this.chat = select("chat", chatProvider, ChatPort::tier,
                new BuiltInChatRouter(catalog, metrics, benchmarks, attribution, format));

        log.info("Agentic ports resolved: triage={} reason={} narrate={} chat={}",
                triage.tier(), reasoning.tier(), narrative.tier(), chat.tier());
    }

    /** The clustering stage. */
    public TriagePort triage() {
        return triage;
    }

    /** The causal explanation stage. */
    public ReasoningPort reasoning() {
        return reasoning;
    }

    /** The stakeholder rendering stage. */
    public NarrativePort narrative() {
        return narrative;
    }

    /** The natural-language routing surface. */
    public ChatPort chat() {
        return chat;
    }

    /** Port name to selected tier, for the health endpoint and the run summary. */
    public Map<String, String> tiers() {
        Map<String, String> tiers = new LinkedHashMap<>(4);
        tiers.put("triage", triage.tier());
        tiers.put("reason", reasoning.tier());
        tiers.put("narrate", narrative.tier());
        tiers.put("chat", chat.tier());
        return Map.copyOf(tiers);
    }

    /** Whether every stage is running deterministically — i.e. no model is in the loop at all. */
    public boolean fullyDeterministic() {
        return tiers().values().stream().allMatch(PortRegistry::isDeterministic);
    }

    /**
     * Applies the selection rule for one port.
     *
     * @param stage    stage name, for the log line
     * @param provider every bean registered for the port type
     * @param tier     accessor for the port's self-reported tier
     * @param fallback the built-in implementation, used only when nothing is registered
     */
    private static <T> T select(
            String stage, ObjectProvider<T> provider, Function<T, String> tier, T fallback) {

        List<T> candidates = provider == null
                ? List.of()
                : provider.orderedStream().filter(candidate -> candidate != fallback).toList();

        if (candidates.isEmpty()) {
            log.info("No {} port registered; using the built-in deterministic implementation", stage);
            return fallback;
        }
        return candidates.stream()
                .filter(candidate -> !isDeterministic(safeTier(tier, candidate)))
                .findFirst()
                .orElseGet(candidates::getFirst);
    }

    private static <T> String safeTier(Function<T, String> tier, T candidate) {
        try {
            return tier.apply(candidate);
        } catch (RuntimeException e) {
            // A port that cannot describe itself is treated as deterministic: the conservative
            // reading, since the alternative is claiming a model ran when nothing is known.
            log.warn("Port {} threw from tier(): {}", candidate.getClass().getSimpleName(), e.toString());
            return DETERMINISTIC_TIER;
        }
    }

    private static boolean isDeterministic(String tier) {
        return tier == null || tier.isBlank()
                || DETERMINISTIC_TIER.equalsIgnoreCase(tier.trim().toLowerCase(Locale.ROOT));
    }
}
