package com.moveinsync.mi.pipeline.fallback;

import com.moveinsync.mi.model.Action;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Incident;
import com.moveinsync.mi.model.PolicyDecision;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.spi.NarrativePort;
import java.util.List;
import java.util.Locale;

/**
 * Renders an incident and a period brief from computed fields alone, with no model in the loop.
 *
 * <p>This is the floor the platform stands on when the LLM layer is switched off, an API key is
 * absent, or a call fails mid-run. It is deliberately <em>not</em> a stub: every section a narrated
 * incident is supposed to carry — what moved, why it matters now, the evidence behind each claim,
 * the actions policy will and will not permit, and the data-quality envelope — is emitted here from
 * fields the deterministic core already computed. The difference against the LLM tier is fluency and
 * cross-metric synthesis, not completeness.
 *
 * <p>Persona is a lens, not a fork. The same numbers are framed for a different reader by changing
 * the opening orientation and the ordering emphasis; the facts, the evidence bindings and the action
 * ladder are byte-identical across personas. That is what makes two renderings of one incident
 * comparable in an audit, and it is why persona is a parameter rather than four code paths.
 *
 * <p>Not a Spring bean. It is constructed directly by {@code PortRegistry} so that it can never
 * compete for injection with a real {@link NarrativePort} implementation — the selection between
 * them stays explicit and identical on every boot.
 */
public final class BuiltInNarrator implements NarrativePort {

    /** Tier label recorded in the audit trail. */
    public static final String TIER = "deterministic";

    /** Incidents listed in full in a period brief before the tail is summarised. */
    private static final int BRIEF_DETAIL_LIMIT = 5;

    /** Evidence bullets rendered per incident. Beyond this the list stops informing and starts padding. */
    private static final int EVIDENCE_LIMIT = 8;

    private final MetricFormat format;

    public BuiltInNarrator(MetricFormat format) {
        this.format = format;
    }

    @Override
    public Narrative narrate(Incident incident, List<Finding> findings, String persona) {
        if (incident == null) {
            return new Narrative("No incident", "Nothing to narrate.", "");
        }
        String reader = canonicalPersona(persona);
        List<Finding> members = findings == null ? List.of() : findings;

        StringBuilder body = new StringBuilder(1024);
        body.append("## ").append(nullSafe(incident.title(), "Untitled incident")).append("\n\n");
        body.append("_").append(orientation(reader)).append("_\n\n");

        appendWhyNow(body, incident);
        appendMovement(body, members);
        appendExplanation(body, incident);
        appendEvidence(body, incident);
        appendActions(body, incident, reader);
        appendPolicy(body, incident);
        appendQuality(body, incident);

        return new Narrative(
                nullSafe(incident.title(), "Untitled incident"),
                nullSafe(incident.whyNow(), "Raised in the current period."),
                body.toString().trim());
    }

    @Override
    public String brief(String period, String persona, List<Incident> incidents, List<String> headline) {
        String reader = canonicalPersona(persona);
        List<Incident> open = incidents == null ? List.of() : incidents;

        StringBuilder brief = new StringBuilder(2048);
        brief.append("# Period brief — ").append(nullSafe(period, "current period")).append("\n\n");
        brief.append("_").append(orientation(reader)).append("_\n\n");

        brief.append("## Headline metrics\n\n");
        if (headline == null || headline.isEmpty()) {
            brief.append("No metric cleared its volume gate for this period, so no headline figure is "
                    + "reported. That is a coverage statement, not a clean bill of health.\n\n");
        } else {
            headline.forEach(line -> brief.append("- ").append(line).append('\n'));
            brief.append('\n');
        }

        brief.append("## Open incidents (").append(open.size()).append(")\n\n");
        if (open.isEmpty()) {
            brief.append("No movement in this period cleared both the significance and the volume gate. "
                    + "Nothing is being escalated.\n\n");
        } else {
            int shown = 0;
            for (Incident incident : open) {
                if (shown++ >= BRIEF_DETAIL_LIMIT) {
                    break;
                }
                brief.append("### ").append(shown).append(". ")
                        .append(nullSafe(incident.title(), "Untitled incident")).append('\n');
                brief.append("- **Priority** ").append(incident.priority())
                        .append(" · **Severity** ").append(nullSafe(incident.severity(), "NONE"))
                        .append(" · **Status** ").append(nullSafe(incident.status(), "OPEN")).append('\n');
                if (incident.whyNow() != null && !incident.whyNow().isBlank()) {
                    brief.append("- **Why now** ").append(incident.whyNow()).append('\n');
                }
                String permitted = permittedSummary(incident);
                if (!permitted.isBlank()) {
                    brief.append("- **Permitted now** ").append(permitted).append('\n');
                }
                if (incident.followUpAt() != null && !incident.followUpAt().isBlank()) {
                    brief.append("- **Re-checked on** ").append(format.humanDate(incident.followUpAt())).append('\n');
                }
                brief.append('\n');
            }
            if (open.size() > BRIEF_DETAIL_LIMIT) {
                brief.append("_").append(open.size() - BRIEF_DETAIL_LIMIT)
                        .append(" further incident(s) are open; the console lists them in full._\n\n");
            }
        }

        brief.append("## How to read this\n\n")
                .append("Every figure above is computed by the metric layer from the versioned catalog "
                        + "definition, not authored here. Where a segment fell below its minimum sample it "
                        + "is reported as unmeasured rather than as zero, because a suppressed slice is "
                        + "not a recovered one.\n");

        return brief.toString().trim();
    }

    @Override
    public String tier() {
        return TIER;
    }

    // ---- sections ---------------------------------------------------------------------------------

    private void appendWhyNow(StringBuilder body, Incident incident) {
        if (incident.whyNow() == null || incident.whyNow().isBlank()) {
            return;
        }
        body.append("**Why now.** ").append(incident.whyNow()).append("\n\n");
    }

    private void appendMovement(StringBuilder body, List<Finding> findings) {
        if (findings.isEmpty()) {
            return;
        }
        body.append("**The numbers.**\n\n");
        for (Finding finding : findings) {
            if (finding == null) {
                continue;
            }
            body.append("- **").append(format.label(finding.metricId())).append("** for ")
                    .append(format.entityPhrase(finding.dimension(), finding.entity())).append(": ")
                    .append(format.value(finding.metricId(), finding.prior()))
                    .append(" in ").append(finding.priorPeriod()).append(" to ")
                    .append(format.value(finding.metricId(), finding.current()))
                    .append(" in ").append(finding.period())
                    .append(" (").append(format.delta(finding.metricId(), finding.deltaPts()))
                    .append(String.format(Locale.ROOT, ", %,d trips", finding.sampleSize()))
                    .append(")\n");
        }
        body.append('\n');
    }

    private void appendExplanation(StringBuilder body, Incident incident) {
        if (incident.explanation() == null || incident.explanation().isBlank()) {
            return;
        }
        // No heading of its own. The explanation now arrives already sectioned — what moved, root
        // cause, what we ruled out, how far to trust it — so wrapping it in one more heading nested
        // those inside it and printed "What moved" twice, once as this file's raw-figures list and
        // again as the reasoner's opening sentence.
        body.append(incident.explanation()).append("\n\n");
    }

    private void appendEvidence(StringBuilder body, Incident incident) {
        List<Evidence> evidence = incident.evidence();
        if (evidence == null || evidence.isEmpty()) {
            return;
        }
        body.append("**Evidence.** Each claim is bound to the metric and entity it was derived from, "
                + "so it can be re-derived rather than trusted.\n\n");
        evidence.stream().filter(item -> item != null && item.claim() != null).limit(EVIDENCE_LIMIT)
                .forEach(item -> body.append("- ").append(item.claim())
                        .append("  \n  `metric=").append(nullSafe(item.metricId(), "n/a"))
                        .append("` `entity=").append(nullSafe(item.entity(), "ALL")).append("`\n"));
        if (evidence.size() > EVIDENCE_LIMIT) {
            body.append("- _").append(evidence.size() - EVIDENCE_LIMIT)
                    .append(" further evidence bindings retained in the audit trail._\n");
        }
        body.append('\n');
    }

    private void appendActions(StringBuilder body, Incident incident, String persona) {
        List<Action> actions = incident.recommendedActions();
        if (actions == null || actions.isEmpty()) {
            return;
        }
        body.append("**Recommended actions.** Refusals are listed alongside approvals on purpose: a "
                + "blocked action that silently disappeared would be indistinguishable from one nobody "
                + "considered.\n\n");
        for (Action action : actions) {
            if (action == null) {
                continue;
            }
            body.append(action.permitted() ? "- **You can now** " : "- _Not yet available_ — ")
                    .append(format.actionPhrase(action.type(), action.target()))
                    .append("  \n  ").append(nullSafe(action.reason(), "")).append('\n');
        }
        body.append('\n');
        if (NarrativePort.LINE_MANAGER.equals(persona)) {
            body.append("Nothing here is executed automatically. The platform recommends; the owning "
                    + "team decides.\n\n");
        }
    }

    private void appendPolicy(StringBuilder body, Incident incident) {
        PolicyDecision policy = incident.policy();
        if (policy == null) {
            return;
        }
        body.append("**Policy.** Rule `").append(nullSafe(policy.ruleId(), "SLA-NONE-000")).append("` · ")
                .append(policy.breached() ? "breached" : "not breached")
                .append(" · breach depth ").append(policy.consecutivePeriods()).append(" period(s) · band ")
                .append(nullSafe(policy.severityBand(), "NONE"))
                .append(" · escalation ")
                .append(policy.escalationPermitted() ? "authorised" : "not yet authorised")
                .append(".\n\n");
    }

    private void appendQuality(StringBuilder body, Incident incident) {
        Quality quality = incident.quality();
        if (quality == null) {
            return;
        }
        body.append(String.format(Locale.ROOT, "**Data quality.** Confidence %s on %.1f%% coverage.",
                nullSafe(quality.confidence(), "UNKNOWN"), quality.coverage() * 100.0));
        if (quality.caveats() != null && !quality.caveats().isEmpty()) {
            body.append('\n');
            quality.caveats().forEach(caveat -> body.append("- ").append(caveat).append('\n'));
        }
        body.append('\n');
    }

    // ---- persona ----------------------------------------------------------------------------------

    /** Unknown personas fall back to the transport manager, as the port contract requires. */
    private static String canonicalPersona(String persona) {
        if (persona == null || persona.isBlank()) {
            return NarrativePort.TRANSPORT_MANAGER;
        }
        String normalised = persona.trim().toLowerCase(Locale.ROOT).replace('-', '_');
        return NarrativePort.PERSONAS.contains(normalised) ? normalised : NarrativePort.TRANSPORT_MANAGER;
    }

    private static String orientation(String persona) {
        return switch (persona) {
            case NarrativePort.FACILITIES_HEAD -> "Written for the facilities head: the site, the "
                    + "service level its people experienced, and the cost exposure behind it.";
            case NarrativePort.LINE_MANAGER -> "Written for a line manager: what happened to the trips "
                    + "your own team was on, and who owns the fix.";
            case NarrativePort.EXECUTIVE -> "Written for the executive reader: the exposure, whether it "
                    + "is worsening, and what the platform is permitted to do about it.";
            default -> "Written for the transport manager: the operating lever, the vendor or route "
                    + "that carries the movement, and what policy permits today.";
        };
    }

    /** Permitted actions as instructions, not as the guard's internal constants. */
    private String permittedSummary(Incident incident) {
        if (incident.recommendedActions() == null) {
            return "";
        }
        return incident.recommendedActions().stream()
                .filter(action -> action != null && action.permitted())
                .map(action -> format.actionPhrase(action.type(), action.target()))
                .reduce((a, b) -> a + "; " + b)
                .orElse("");
    }

    private static String nullSafe(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}
