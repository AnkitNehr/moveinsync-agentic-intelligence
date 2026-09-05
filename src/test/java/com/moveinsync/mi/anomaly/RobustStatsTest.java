package com.moveinsync.mi.anomaly;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * The statistics have to survive this dataset, not a textbook one. {@code delay_minutes} reaches
 * 10,644 and {@code planned_km} goes negative, so the tests here are mostly about what happens when
 * the input is hostile.
 */
class RobustStatsTest {

    private static final double TOLERANCE = 1e-9;

    @Test
    @DisplayName("median handles odd, even, unsorted and empty samples")
    void median() {
        assertThat(RobustStats.median(new double[]{3, 1, 2})).isEqualTo(2.0);
        assertThat(RobustStats.median(new double[]{4, 1, 3, 2})).isCloseTo(2.5, within(TOLERANCE));
        assertThat(RobustStats.median(new double[]{7})).isEqualTo(7.0);
        assertThat(RobustStats.median(new double[0])).isNaN();
        assertThat(RobustStats.median(null)).isNaN();
    }

    @Test
    @DisplayName("median does not mutate the caller's array")
    void medianIsNonDestructive() {
        double[] values = {5, 1, 3};
        RobustStats.median(values);
        assertThat(values).containsExactly(5, 1, 3);
    }

    @Test
    @DisplayName("mad measures spread around the median")
    void mad() {
        // deviations from median 3 are {2,1,0,1,2}, whose median is 1.
        assertThat(RobustStats.mad(new double[]{1, 2, 3, 4, 5})).isCloseTo(1.0, within(TOLERANCE));
        assertThat(RobustStats.mad(new double[]{4, 4, 4, 4})).isEqualTo(0.0);
        assertThat(RobustStats.mad(new double[0])).isNaN();
    }

    @Test
    @DisplayName("a single extreme outlier moves the median and MAD barely at all")
    void resistsOutliers() {
        double[] clean = {30, 31, 32, 33, 34};
        // One delay_minutes row at 10,644 - the real maximum in this data.
        double[] contaminated = {30, 31, 32, 33, 10_644};

        assertThat(RobustStats.median(contaminated)).isEqualTo(32.0);
        assertThat(RobustStats.median(clean)).isEqualTo(32.0);
        // For contrast: the mean jumps from 32 to over 2,000.
        double contaminatedMean = (30 + 31 + 32 + 33 + 10_644) / 5.0;
        assertThat(contaminatedMean).isGreaterThan(2_000.0);
    }

    @Test
    @DisplayName("robustZ scales by MAD and returns zero when there is no scale")
    void robustZ() {
        assertThat(RobustStats.robustZ(5.0, 3.0, 1.0)).isCloseTo(RobustStats.MAD_SCALE * 2.0, within(TOLERANCE));
        assertThat(RobustStats.robustZ(3.0, 3.0, 1.0)).isEqualTo(0.0);

        // A flat series has no dispersion. Dividing by zero would report every departure as
        // infinitely anomalous; a flat history is evidence of nothing, so this must be zero.
        assertThat(RobustStats.robustZ(99.0, 3.0, 0.0)).isEqualTo(0.0);
        assertThat(RobustStats.robustZ(Double.NaN, 3.0, 1.0)).isEqualTo(0.0);
        assertThat(RobustStats.robustZ(5.0, Double.NaN, 1.0)).isEqualTo(0.0);
    }

    @Test
    @DisplayName("robustZ against a sample falls back to mean absolute deviation when MAD collapses")
    void robustZFallsBackWhenMadIsZero() {
        // Four of five points identical, so MAD is exactly zero, but the sample plainly has spread.
        // Short monthly series make this common, and returning zero here would blind the scanner.
        double[] sample = {0.95, 0.95, 0.95, 0.95, 0.80};

        assertThat(RobustStats.mad(sample)).isEqualTo(0.0);
        assertThat(Math.abs(RobustStats.robustZ(0.80, sample))).isGreaterThan(2.0);
    }

    @Test
    @DisplayName("robustZ against a truly constant sample is zero, not infinite")
    void robustZOnConstantSample() {
        assertThat(RobustStats.robustZ(0.5, new double[]{0.9, 0.9, 0.9, 0.9})).isEqualTo(0.0);
        assertThat(RobustStats.robustZ(0.5, new double[0])).isEqualTo(0.0);
    }

    @Test
    @DisplayName("non-finite entries are ignored rather than poisoning the statistic")
    void ignoresNonFinite() {
        double[] values = {1, 2, Double.NaN, 3, Double.POSITIVE_INFINITY, 4, 5};
        assertThat(RobustStats.median(values)).isEqualTo(3.0);
        assertThat(RobustStats.mad(values)).isCloseTo(1.0, within(TOLERANCE));
    }

    @Test
    @DisplayName("ewma weights recent observations more heavily")
    void ewma() {
        double[] rising = {0.90, 0.92, 0.94, 0.96};
        assertThat(RobustStats.ewma(rising, 0.9)).isGreaterThan(0.95);
        assertThat(RobustStats.ewma(rising, 0.1)).isLessThan(0.93);
        assertThat(RobustStats.ewma(new double[]{0.5}, 0.5)).isEqualTo(0.5);
        assertThat(RobustStats.ewma(new double[0], 0.5)).isNaN();
    }

    @Test
    @DisplayName("toArray drops nulls from boxed histories")
    void toArray() {
        assertThat(RobustStats.toArray(java.util.Arrays.asList(1.0, null, 3.0)))
                .containsExactly(1.0, 3.0);
        assertThat(RobustStats.toArray(null)).isEmpty();
    }
}
