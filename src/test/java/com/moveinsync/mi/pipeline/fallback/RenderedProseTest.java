package com.moveinsync.mi.pipeline.fallback;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.Quality;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import com.moveinsync.mi.pipeline.MetricFormat;
import com.moveinsync.mi.pipeline.spi.TriagePort;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * Asserts on the strings users actually read.
 *
 * <p>Every test here exists because something shipped. The package had no coverage of any kind, and
 * the gap has a shape: the code assembles prose correctly-looking enough to pass review, and nothing
 * evaluates the result. Three separate faults reached rendered output this way — a literal
 * {@code %s}, a pronoun with no antecedent, and a ranking that returned the opposite entity — and
 * all three are invisible unless a test reads the finished sentence.
 *
 * <p>So these assert on rendered text rather than on interactions. A mock verifying that
 * {@code format.delta} was called would have passed during every one of those failures.
 */
class RenderedProseTest {

    private final MetricCatalog catalog = new MetricCatalog();
    private final MetricFormat format = new MetricFormat(catalog);
    private final DeterministicTriage triage = new DeterministicTriage(format, 5, 6);

    // ---- fixtures --------------------------------------------------------------------------------

    /** A finding with no SLA reference, so whyNow's z-clause has to lead the paragraph. */
    private static Finding withoutSla(String metricId, double deltaPts, double robustZ) {
        return finding(metricId, deltaPts, robustZ, null);
    }

    /** A finding whose SLA is breached, so the z-clause follows a sentence. */
    private static Finding withBreachedSla(String metricId, double deltaPts, double robustZ) {
        return finding(metricId, deltaPts, robustZ, new Sla(0.95, -0.02, true));
    }

    private static Finding finding(String metricId, double deltaPts, double robustZ, Sla sla) {
        MetricObservation observation = new MetricObservation(
                metricId, "office", "Crestwood Campus", "2026-07", 0.89, 40_574L,
                new References(new Trend(0.93, -0.04, robustZ),
                        sla == null ? Sla.notApplicable() : sla, Peer.none(), Industry.none()),
                0.8, new Quality(1.0, "HIGH", List.of()));
        return new Finding(
                metricId + ":office:crestwood_campus:2026_07",
                metricId, "office", "Crestwood Campus", "2026-07", "2026-06",
                0.89, 0.93, deltaPts, 40_574L, robustZ, Math.abs(robustZ),
                observation, List.of());
    }

    private String whyNowFor(Finding lead) {
        List<TriagePort.IncidentDraft> drafts = triage.triage(List.of(lead), "2026-07");
        assertThat(drafts).isNotEmpty();
        return drafts.getFirst().whyNow();
    }

    // ---- the fault class that keeps escaping -----------------------------------------------------

    @Nested
    @DisplayName("no unrendered format specifier reaches the reader")
    class FormatSpecifiers {

        /**
         * The regression that shipped twice.
         *
         * <p>{@code "a" + "b %s".formatted(x)} binds the method call tighter than the concatenation,
         * so {@code formatted} applies to the final fragment alone and every earlier {@code %s} is
         * emitted verbatim. It compiles, because surplus arguments are legal. Only the finished
         * string shows it.
         */
        @Test
        void whyNowNeverContainsALiteralSpecifier() {
            for (Finding lead : List.of(
                    withoutSla("cost_per_trip", 50.74, 2.9),
                    withBreachedSla("ota", -3.02, -2.9),
                    withoutSla("occupancy", -4.68, -2.6),
                    withoutSla("delay_p90", 51.50, 14.6),
                    withoutSla("noshow_rate", -2.26, -0.4))) {
                assertThat(whyNowFor(lead))
                        .as("whyNow for %s", lead.metricId())
                        .doesNotContain("%s")
                        .doesNotContain("%d")
                        .doesNotContain("%.1f")
                        .doesNotContain("%,");
            }
        }

        @Test
        void titleNeverContainsALiteralSpecifier() {
            List<TriagePort.IncidentDraft> drafts =
                    triage.triage(List.of(withoutSla("cost_per_trip", 50.74, 2.9)), "2026-07");
            assertThat(drafts.getFirst().title()).doesNotContain("%s").doesNotContain("%.");
        }
    }

    // ---- sentences must stand on their own -------------------------------------------------------

    @Nested
    @DisplayName("prose reads as a sentence wherever it starts")
    class Antecedents {

        /**
         * The z-clause is second when an SLA is breached and first when none exists. Opening it with
         * "That" therefore left three of five live incidents starting with a pronoun referring to
         * nothing — which reads as a truncation bug, not as a style problem.
         */
        @Test
        void whyNowDoesNotOpenWithADanglingPronoun() {
            String noSla = whyNowFor(withoutSla("cost_per_trip", 50.74, 2.9));
            assertThat(noSla)
                    .as("no SLA clause precedes it, so it must not refer backwards")
                    .doesNotStartWith("That ")
                    .doesNotStartWith("This ")
                    .doesNotStartWith("It ");
        }

        @Test
        void whyNowStillReadsWhenTheSlaClauseLeads() {
            assertThat(whyNowFor(withBreachedSla("ota", -3.02, -2.9)))
                    .startsWith("Now at")
                    .contains("bigger swing");
        }
    }

    // ---- jargon stays out of what a manager reads ------------------------------------------------

    @Nested
    @DisplayName("no internal vocabulary in persona-facing text")
    class Vocabulary {

        @Test
        void whyNowNamesNoStatisticAndNoPayloadKey() {
            for (Finding lead : List.of(
                    withBreachedSla("ota", -3.02, -2.9),
                    withoutSla("cost_per_trip", 50.74, 2.9),
                    withoutSla("delay_p90", 51.50, 14.6))) {
                assertThat(whyNowFor(lead))
                        .as("whyNow for %s", lead.metricId())
                        .doesNotContain("robust z")
                        .doesNotContain("robust_z")
                        .doesNotContain("rate_effect")
                        .doesNotContain("mix_effect")
                        .doesNotContain("z-score");
            }
        }

        /**
         * A movement below {@link DeterministicTriage} NOTABLE_Z is admitted by the scanner's
         * material-delta route. It must not be described as unusual: the earlier two-band wording
         * asserted "larger than usual" for every finite score, which was a claim the data did not
         * support and which the literal z it replaced had at least stated accurately.
         */
        @Test
        void anOrdinaryMovementIsNotCalledUnusual() {
            assertThat(whyNowFor(withoutSla("noshow_rate", -0.30, -0.4)))
                    .doesNotContain("bigger swing")
                    .doesNotContain("break in the pattern");
        }
    }
}
