package com.moveinsync.mi.glossary;

import static org.assertj.core.api.Assertions.assertThat;

import com.moveinsync.mi.metric.MetricCatalog;
import com.moveinsync.mi.model.Evidence;
import com.moveinsync.mi.model.Incident;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class OperatorCopyTest {

    private final OperatorCopy copy = new OperatorCopy(new MetricCatalog(), new ColumnDictionary());

    @Test
    @DisplayName("escort_compliance is Night Escort Coverage, not a column name")
    void escortIdBecomesCatalogLabel() {
        assertThat(copy.metricLabel("escort_compliance")).isEqualTo("Night Escort Coverage");
        assertThat(copy.rewrite("escort_compliance fell on business_unit = orbit-Slc"))
                .contains("Night Escort Coverage")
                .contains("business unit")
                .doesNotContain("escort_compliance")
                .doesNotContain("business_unit");
        assertThat(copy.rewrite("escort compliance dropped from 52%"))
                .contains("Night Escort Coverage")
                .doesNotContain("escort compliance");
        assertThat(copy.rewrite("Three separate escort-compliance findings declined"))
                .contains("Night Escort Coverage")
                .doesNotContain("escort-compliance");
    }

    @Test
    @DisplayName("hyphenated incident ids are not rewritten")
    void incidentIdsKeepHyphens() {
        String id = "inc-escort-compliance-business-unit-2026-07";
        assertThat(copy.rewrite(id)).isEqualTo(id);
    }

    @Test
    @DisplayName("dictionary meaning of actual_escort is attached to the metric")
    void escortSourcesCiteTheTripDictionary() {
        assertThat(copy.sources("escort_compliance"))
                .extracting(column -> column.id())
                .containsExactly("actual_escort", "shift_type");
        assertThat(copy.sources("escort_compliance"))
                .anyMatch(column -> "actual_escort".equals(column.id())
                        && column.meaning().toLowerCase().contains("escort was actually present"));
    }

    @Test
    @DisplayName("incident prose is rewritten on the way out, ids stay for audit")
    void incidentRewriteKeepsMetricIdOnEvidence() {
        Incident raw = new Incident(
                "inc-1",
                "escort_compliance drop",
                "escort_compliance fell",
                1,
                "CRITICAL",
                List.of("f1"),
                "See escort_compliance on shift_type.",
                List.of(new Evidence("escort_compliance moved", "escort_compliance", "LOGIN")),
                List.of(),
                null,
                null,
                "t",
                null,
                "OPEN");

        Incident shown = copy.incident(raw);
        assertThat(shown.title()).isEqualTo("Night Escort Coverage drop");
        assertThat(shown.explanation()).contains("Night Escort Coverage").contains("shift");
        assertThat(shown.evidence().getFirst().metricId()).isEqualTo("escort_compliance");
        assertThat(shown.evidence().getFirst().claim()).contains("Night Escort Coverage");
    }
}
