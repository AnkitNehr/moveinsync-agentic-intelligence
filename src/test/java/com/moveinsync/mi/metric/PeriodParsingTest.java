package com.moveinsync.mi.metric;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.time.YearMonth;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Period labels are the platform's primary API input and are compared against
 * {@code strftime(..., '%Y-%m')} in SQL. Two properties matter and are asserted here: the dated form
 * the documentation uses is accepted, and whatever is accepted is normalised to {@code yyyy-MM}
 * before it can reach a query. An un-normalised label matches no rows, which would surface an empty
 * month as a healthy one rather than as an error.
 */
@DisplayName("Period label parsing")
class PeriodParsingTest {

    @Nested
    @DisplayName("accepted forms")
    class AcceptedForms {

        @Test
        @DisplayName("the canonical yyyy-MM label parses")
        void canonicalLabel() {
            assertEquals(YearMonth.of(2026, 6), MetricQueryService.parsePeriod("2026-06"));
        }

        @Test
        @DisplayName("the dated yyyy-MM-dd form used across the docs and demo parses to its month")
        void datedForm() {
            assertEquals(YearMonth.of(2026, 6), MetricQueryService.parsePeriod("2026-06-01"));
        }

        @Test
        @DisplayName("a mid-month date truncates to the containing month")
        void midMonthDate() {
            assertEquals(YearMonth.of(2026, 7), MetricQueryService.parsePeriod("2026-07-23"));
        }

        @Test
        @DisplayName("surrounding whitespace is tolerated in both forms")
        void whitespace() {
            assertEquals(YearMonth.of(2026, 5), MetricQueryService.parsePeriod("  2026-05  "));
            assertEquals(YearMonth.of(2026, 5), MetricQueryService.parsePeriod("  2026-05-01  "));
        }
    }

    @Nested
    @DisplayName("normalisation to the canonical label")
    class Normalisation {

        @Test
        @DisplayName("the dated form is rewritten to yyyy-MM, so it can never reach SQL as a date")
        void datedFormIsCanonicalised() {
            assertEquals("2026-06", MetricQueryService.canonicalPeriod("2026-06-01"));
        }

        @Test
        @DisplayName("an already-canonical label is returned unchanged")
        void canonicalIsIdempotent() {
            assertEquals("2026-06", MetricQueryService.canonicalPeriod("2026-06"));
            assertEquals("2026-06", MetricQueryService.canonicalPeriod(
                    MetricQueryService.canonicalPeriod("2026-06-01")));
        }

        @Test
        @DisplayName("both spellings of the same month converge on one label")
        void bothFormsAgree() {
            assertEquals(
                    MetricQueryService.canonicalPeriod("2026-06"),
                    MetricQueryService.canonicalPeriod("2026-06-01"));
        }

        @Test
        @DisplayName("the prior period of a dated label is the previous month")
        void priorPeriodAcceptsDatedForm() {
            assertEquals("2026-05", MetricQueryService.previousPeriod("2026-06-01"));
            assertEquals("2025-12", MetricQueryService.previousPeriod("2026-01-01"));
        }
    }

    @Nested
    @DisplayName("rejected input still returns null rather than throwing")
    class Rejected {

        @ParameterizedTest
        @ValueSource(strings = {"June 2026", "2026/06", "2026-13", "2026-06-32", "not-a-period", "26-06"})
        @DisplayName("malformed labels parse to null")
        void malformed(String label) {
            assertNull(MetricQueryService.parsePeriod(label));
            assertNull(MetricQueryService.canonicalPeriod(label));
        }

        @Test
        @DisplayName("absent labels parse to null")
        void absent() {
            assertNull(MetricQueryService.parsePeriod(null));
            assertNull(MetricQueryService.parsePeriod("   "));
            assertNull(MetricQueryService.canonicalPeriod(null));
        }
    }
}
