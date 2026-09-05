package com.moveinsync.mi.llm;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.metric.MetricDefinition;
import com.moveinsync.mi.policy.SlaPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.TreeSet;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Builds the byte-identical system prefix shared by every agent call.
 *
 * <h2>Why byte-identical is the whole point</h2>
 *
 * <p>Prompt caching is a prefix match: one changed byte anywhere invalidates the cache from that
 * position onward. The three agents in this package all send the same metric catalog, the same
 * persona style guides and the same SLA configuration, so putting that content in one shared,
 * frozen prefix means it is written to cache once per run and read back at roughly a tenth of the
 * input price on every subsequent call — across triage, every reasoning call and every narrative.
 *
 * <p>Everything in here is therefore constructed to be reproducible byte for byte:
 *
 * <ul>
 *   <li><strong>No timestamps.</strong> A "generated at" line would move the cache hit rate to zero
 *       and be invisible while doing it — the calls still succeed, they just cost 10x more.
 *   <li><strong>No UUIDs or run ids.</strong> Run-scoped identifiers belong in the user turn.
 *   <li><strong>No unordered iteration.</strong> Metrics are emitted in catalog id order, SLA rules
 *       in rule-id order, grains and dimension mappings through sorted maps. A {@code HashMap}
 *       iteration order that happens to be stable within one JVM but differs across restarts would
 *       silently halve the cache hit rate after every deploy.
 *   <li><strong>Fixed locale and fixed decimal places.</strong> {@code Locale.ROOT} throughout, so a
 *       machine with a comma decimal separator produces the same bytes as one without.
 * </ul>
 *
 * <p>{@link #fingerprint()} exposes a SHA-256 of the prefix so this property is testable and so a
 * cache-hit regression can be traced to the exact deploy that changed the catalog.
 *
 * <h2>Why the data-quality contract is in here</h2>
 *
 * <p>The section on comma-formatted ids, the {@code 'OverHead'} literal in the billing extract, the
 * zero-distance fixed-rate contracts and the placeholder {@code stwid=0} is not decoration. Those
 * are the traps that produce confident, wrong narratives — a model that does not know 42% of bill
 * rows carry zero kilometres by design will happily explain a "collapse in cost per km". Stating the
 * contract once, in the cached half of the prompt, costs almost nothing per call.
 */
@Service
public class CachedPrefixBuilder {

    private static final Logger log = LoggerFactory.getLogger(CachedPrefixBuilder.class);

    /** Bump when the prefix content changes; makes a cache-invalidating edit explicit in the diff. */
    public static final int PREFIX_VERSION = 1;

    /** Persona key for the operations owner who runs the vendor and route relationships. */
    public static final String PERSONA_TRANSPORT_MANAGER = "transport_manager";

    /** Persona key for the site leader who reads one email and never opens the dashboard. */
    public static final String PERSONA_FACILITIES_HEAD = "facilities_head";

    /** Persona key for the people manager who only cares about their own team's commute. */
    public static final String PERSONA_LINE_MANAGER = "line_manager";

    private static final List<String> PERSONAS =
            List.of(PERSONA_TRANSPORT_MANAGER, PERSONA_FACILITIES_HEAD, PERSONA_LINE_MANAGER);

    private final MetricCatalog catalog;
    private final SlaPolicy slaPolicy;

    private final Object lock = new Object();
    private volatile String prefix;
    private volatile String fingerprint;

    public CachedPrefixBuilder(MetricCatalog catalog, SlaPolicy slaPolicy) {
        this.catalog = catalog;
        this.slaPolicy = slaPolicy;
    }

    /**
     * The cached system prefix. Built once on first use and returned unchanged thereafter.
     *
     * <p>The double-checked lock is not premature optimisation: three agents may call this
     * concurrently on the first incident of a run, and building it twice would be harmless but
     * pointless work under a lock that is otherwise never contended.
     */
    public String prefix() {
        String existing = prefix;
        if (existing != null) {
            return existing;
        }
        synchronized (lock) {
            if (prefix == null) {
                prefix = build();
                fingerprint = sha256(prefix);
                log.info("Cached system prefix built: {} chars, ~{} tokens, sha256={}",
                        prefix.length(), approximateTokens(prefix), fingerprint);
                if (approximateTokens(prefix) < 1024) {
                    log.warn("Cached prefix is only ~{} tokens. The minimum cacheable prefix is 512 tokens on "
                            + "{} and 1024 on {}, so short prefixes silently fail to cache.",
                            approximateTokens(prefix), ModelTier.STRONG.modelId(), ModelTier.MID.modelId());
                }
            }
            return prefix;
        }
    }

    /** SHA-256 of the prefix, hex encoded. Stable across restarts iff the prefix truly is. */
    public String fingerprint() {
        prefix();
        return fingerprint;
    }

    /** Persona keys this prefix documents, in a fixed order. */
    public List<String> personas() {
        return PERSONAS;
    }

    /** Whether a persona key is one the prefix describes. Matching is case-insensitive. */
    public boolean isKnownPersona(String persona) {
        return persona != null && PERSONAS.contains(persona.trim().toLowerCase(Locale.ROOT));
    }

    /**
     * Canonicalises a persona key, defaulting to {@link #PERSONA_TRANSPORT_MANAGER}.
     *
     * <p>An unrecognised persona must not silently produce a voiceless narrative, and it must not
     * throw either — a typo in an API request should degrade to the default operational voice.
     */
    public String canonicalPersona(String persona) {
        if (persona == null || persona.isBlank()) {
            return PERSONA_TRANSPORT_MANAGER;
        }
        String needle = persona.trim().toLowerCase(Locale.ROOT).replace('-', '_').replace(' ', '_');
        return PERSONAS.contains(needle) ? needle : PERSONA_TRANSPORT_MANAGER;
    }

    /** Rough token estimate, used only for the cacheability warning. Four characters per token. */
    private static int approximateTokens(String text) {
        return text.length() / 4;
    }

    // ---- construction ---------------------------------------------------------------------------

    private String build() {
        StringBuilder out = new StringBuilder(8192);

        appendRole(out);
        appendMetricCatalog(out);
        appendSlaConfiguration(out);
        appendDataQualityContract(out);
        appendPersonaGuides(out);
        appendOutputRules(out);

        return out.toString();
    }

    private void appendRole(StringBuilder out) {
        out.append("=== MOBILITY INTELLIGENCE PLATFORM — SYSTEM CONTEXT v").append(PREFIX_VERSION).append(" ===\n\n");
        out.append("""
                You are the reasoning layer of an autonomous mobility intelligence platform operating over \
                employee transport data (rides, billing, alerts, employee legs, feedback) for a set of \
                corporate campuses.

                Division of responsibility — this is not negotiable:
                  * Deterministic code computes every number. Metric values, period deltas, robust z-scores, \
                shift-share contributions, SLA breach verdicts and severity bands are all computed before you \
                are called, and are supplied to you in the user turn.
                  * You cluster, explain and phrase. You never compute, re-derive, extrapolate or estimate a \
                figure, and you never decide whether something breached an SLA.

                Hard rules:
                  1. Use ONLY numbers present in the supplied payload. Every figure you write is checked \
                against the payload by a numeric validator; an invented or recomputed number causes your \
                output to be rejected and replaced by a template.
                  2. Do not compute derived figures. If the payload gives you a current value and a prior \
                value but no percentage change, do not calculate one.
                  3. Attribute only where the data attributes. If the shift-share decomposition shows a \
                near-zero mix effect, do not describe the movement as a shift of volume between entities.
                  4. Correlation is not cause. State the strongest hypothesis the evidence supports and say \
                what would confirm it, rather than asserting a mechanism the data cannot show.
                  5. Absence of evidence is not evidence of absence. Low coverage or a suppressed small \
                segment means unknown, not fine.
                  6. Never recommend an action targeting a person, a demographic attribute, or an individual \
                employee. Actions target vendors, offices, routes, contracts and processes.

                """);
    }

    private void appendMetricCatalog(StringBuilder out) {
        out.append("--- METRIC CATALOG (versioned; the only definitions that exist) ---\n");

        List<MetricDefinition> metrics = new ArrayList<>(catalog.all());
        metrics.sort(Comparator.comparing(MetricDefinition::id));

        if (metrics.isEmpty()) {
            out.append("(catalog empty — no metrics are defined)\n\n");
            return;
        }

        for (MetricDefinition metric : metrics) {
            out.append('\n');
            out.append(metric.id()).append(" — ").append(metric.label())
                    .append(" (v").append(metric.version()).append(")\n");
            if (metric.description() != null && !metric.description().isBlank()) {
                out.append("  meaning: ").append(oneLine(metric.description())).append('\n');
            }
            out.append("  unit: ").append(metric.unit())
                    .append(" | direction: ").append(metric.direction())
                    .append(" | rate metric: ").append(metric.rateMetric())
                    .append(" | min sample: ").append(metric.minSample()).append('\n');

            out.append("  grains: ").append(String.join(", ", new TreeSet<>(metric.grains()))).append('\n');

            Map<String, String> dimensions = new TreeMap<>(metric.resolvedDimensions());
            if (!dimensions.isEmpty()) {
                List<String> mappings = new ArrayList<>(dimensions.size());
                dimensions.forEach((grain, column) -> {
                    if (!grain.equals(column)) {
                        mappings.add(grain + "->" + column);
                    }
                });
                if (!mappings.isEmpty()) {
                    out.append("  column mapping: ").append(String.join(", ", mappings)).append('\n');
                }
            }

            if (metric.segmentBy() != null) {
                out.append("  DEFINED ONLY WHERE ").append(metric.segmentBy()).append(" IN (")
                        .append(String.join(", ", new TreeSet<>(metric.validSegments())))
                        .append("). Outside those segments the metric does not exist; it is not zero and not "
                                + "missing data.\n");
            }
            if (metric.slaKey() != null) {
                out.append("  governed by SLA key: ").append(metric.slaPropertyKey())
                        .append(metric.slaAdvisory() ? " (advisory only — reported, not scored)" : "")
                        .append('\n');
            }
            if (metric.industryKey() != null) {
                out.append("  industry benchmark key: ").append(metric.industryPropertyKey()).append('\n');
            }
            for (String caveat : metric.caveats()) {
                out.append("  caveat: ").append(oneLine(caveat)).append('\n');
            }
        }
        out.append('\n');
    }

    private void appendSlaConfiguration(StringBuilder out) {
        out.append("--- SLA CONFIGURATION (targets are contractual; breach is decided by rules, not by you) ---\n");

        // Keyed by rule id so the output order is stable regardless of how many catalog metrics alias
        // onto the same rule.
        Map<String, SlaPolicy.SlaRule> rules = new TreeMap<>();
        for (MetricDefinition metric : catalog.all()) {
            slaPolicy.ruleFor(metric.id()).ifPresent(rule -> rules.putIfAbsent(rule.ruleId(), rule));
        }

        if (rules.isEmpty()) {
            out.append("(no SLA rules apply to the current catalog)\n");
        } else {
            for (Map.Entry<String, SlaPolicy.SlaRule> entry : rules.entrySet()) {
                SlaPolicy.SlaRule rule = entry.getValue();
                out.append("  ").append(entry.getKey())
                        .append(" | metric=").append(rule.metricId())
                        .append(" | ").append(rule.direction())
                        .append(" | unit=").append(rule.unit())
                        .append(" | target=").append(format(rule.target()))
                        .append('\n');
            }
        }

        out.append("\n  Severity bands are computed from the RELATIVE gap (gap / |target|), so they are\n")
                .append("  comparable across a rate metric and a currency metric:\n")
                .append("    < ").append(format(SlaPolicy.MAJOR_THRESHOLD)).append(" -> ")
                .append(SlaPolicy.BAND_MINOR).append('\n')
                .append("    < ").append(format(SlaPolicy.CRITICAL_THRESHOLD)).append(" -> ")
                .append(SlaPolicy.BAND_MAJOR).append('\n')
                .append("    >= ").append(format(SlaPolicy.CRITICAL_THRESHOLD)).append(" -> ")
                .append(SlaPolicy.BAND_CRITICAL).append('\n')
                .append("  Escalation requires ").append(SlaPolicy.ESCALATION_MIN_CONSECUTIVE_PERIODS)
                .append(" consecutive breached periods. You may report an escalation decision; you may never\n")
                .append("  make one.\n\n");
    }

    private void appendDataQualityContract(StringBuilder out) {
        out.append("--- DATA QUALITY CONTRACT (known properties of the source extracts) ---\n");
        out.append("""
                These are established facts about the data, already handled by the ingest layer. They are here
                so you never mistake a modelling artefact for an operational event:

                  * Nulls are meaningful, not defects. An unacknowledged alert, a non-boarding employee and an
                    incomplete leg are real states. No row is ever dropped; coverage is reported instead.
                  * Billing rows for fixed-rate contracts carry total_trip_km = 0 by design (roughly 42% of
                    rows). Cost per km is UNDEFINED there, not zero and not missing. Only distance-based
                    contracts have a cost per km at all.
                  * Roughly a fifth of billing rows have no slab name. That is a contract shape, not a gap.
                  * Employee-leg distances can be negative in the source. Those rows are flagged, not silently
                    corrected, and any metric computed over them carries a caveat.
                  * Delay minutes contain extreme outliers (past seven days). They are retained and flagged
                    rather than winsorised, so a p90 quoted to you already accounts for them.
                  * A placeholder employee id of 0 is not a person and is excluded from per-rider metrics.
                  * The alert severity column contains a stray non-severity literal alongside the real bands,
                    plus a large block of nulls. Severity counts are therefore lower bounds.
                  * Small segments are volume-gated before they reach you. A segment you are not shown may
                    have moved violently; it was suppressed because its sample was too small to distinguish
                    from noise, which is a decision about confidence, not about importance.
                  * Trip nodality is null for non-nodal home trips; that is reported as 'NA' and is expected.

                """);
    }

    private void appendPersonaGuides(StringBuilder out) {
        out.append("--- PERSONA STYLE GUIDES (the narrative agent is told which one to use) ---\n");
        for (Map.Entry<String, String> entry : personaGuides().entrySet()) {
            out.append('\n').append(entry.getKey()).append(":\n").append(entry.getValue());
        }
        out.append('\n');
    }

    /**
     * The three voices, in a fixed insertion order.
     *
     * <p>These are genuinely different jobs, not tone presets. The transport manager can act on a
     * vendor; the facilities head is deciding whether to care at all and will never click through to
     * a dashboard, which is why their brief demands a self-contained, conclusion-first note with the
     * data-quality caveats stated inline rather than linked; the line manager only wants to know what
     * their own team should expect tomorrow morning.
     */
    private static Map<String, String> personaGuides() {
        Map<String, String> guides = new LinkedHashMap<>();

        guides.put(PERSONA_TRANSPORT_MANAGER, """
                  Audience: the operations owner who runs vendor relationships and route planning daily.
                  They live in this data and will act on your note this week.
                  Voice: direct, operational, peer-to-peer. Assume fluency in OTA, no-show, nodal routing,
                  escort compliance and vendor contracts. Do not define terms.
                  Structure: what moved and where it concentrates, the shift-share split between rate and
                  mix effects, then the single most useful next step.
                  Length: short. Six sentences is generous.
                  Include: the specific segments (direction, product type, route source, office, vendor)
                  carrying the movement, with their figures.
                  Avoid: background, reassurance, and any recap of what the metric means.
                """);

        guides.put(PERSONA_FACILITIES_HEAD, """
                  Audience: the site leader accountable for the campus. They will read this note once, on a
                  phone, and will not open a dashboard or ask a follow-up question.
                  Voice: plain business English. Expand any term of art on first use.
                  Structure: CONCLUSION FIRST. Sentence one states the impact and whether it needs a
                  decision. Only then the supporting detail.
                  SELF-CONTAINED — this is a hard requirement: the note must stand alone with no dashboard,
                  no attachment, no prior context and no follow-up. Every figure referenced must appear in
                  the note itself, along with the period it covers and what it is being compared against.
                  DISCLOSE DATA QUALITY INLINE — also a hard requirement: if coverage is partial, a
                  segment was suppressed for small sample, or a caveat applies, say so in the body, in
                  plain words, at the point the affected figure is used. Never relegate it to a footnote
                  and never omit it because it weakens the story. If a limitation means the conclusion
                  could be wrong, say that explicitly.
                  Length: one short paragraph, then at most three supporting sentences.
                  Avoid: operational jargon, vendor ids without a description, and any instruction to
                  "see the dashboard".
                """);

        guides.put(PERSONA_LINE_MANAGER, """
                  Audience: a people manager whose team commutes on these routes. They have no operational
                  levers and no interest in fleet mechanics.
                  Voice: brief, concrete, human. Talk about people's commutes, not about metrics.
                  Structure: what their team experienced, whether it is getting better or worse, and what
                  is being done about it.
                  Length: three or four sentences.
                  Include: the practical consequence — later arrivals, longer waits, more no-shows.
                  Avoid: vendor names, contract terms, SLA rule ids, and any ask of the reader beyond
                  awareness. Never single out an individual employee.
                """);

        return guides;
    }

    private void appendOutputRules(StringBuilder out) {
        out.append("--- OUTPUT RULES ---\n");
        out.append("""
                Every agent in this system requests a specific JSON object. When JSON is requested:
                  * Return the JSON object and nothing else. No prose before it, no code fence around it,
                    no trailing commentary.
                  * Use exactly the keys requested. Do not add keys, and do not omit requested keys — use
                    null or an empty array when you have nothing to put in one.
                  * Quote figures exactly as they appear in the payload, including their decimal places.
                    Do not round, rescale between fractions and percentages, or reformat them.
                  * If the payload does not support a claim, leave it out. An empty evidence array is a
                    valid, honest answer; a fabricated one is not.
                """);
    }

    // ---- formatting -----------------------------------------------------------------------------

    /** Fixed-locale, fixed-precision number formatting, with trailing zeros trimmed deterministically. */
    private static String format(double value) {
        if (!Double.isFinite(value)) {
            return "n/a";
        }
        String rendered = String.format(Locale.ROOT, "%.4f", value);
        if (rendered.contains(".")) {
            rendered = rendered.replaceAll("0+$", "");
            rendered = rendered.endsWith(".") ? rendered.substring(0, rendered.length() - 1) : rendered;
        }
        return rendered;
    }

    /** Collapses whitespace so a multi-line YAML description does not break the prefix layout. */
    private static String oneLine(String text) {
        return text.replaceAll("\\s+", " ").trim();
    }

    private static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            // SHA-256 is mandated by the platform spec; this cannot happen on a conforming JVM.
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }

    /** Exposed for diagnostics: the persona guide text, or empty for an unknown persona. */
    public Optional<String> personaGuide(String persona) {
        return Optional.ofNullable(personaGuides().get(canonicalPersona(persona)));
    }
}
