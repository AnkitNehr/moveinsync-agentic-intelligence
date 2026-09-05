package com.moveinsync.mi.anomaly;

import java.util.Arrays;
import java.util.Collection;

/**
 * Outlier-resistant summary statistics.
 *
 * <p>Mean and standard deviation are unusable on this data. {@code delay_minutes} reaches 10,644 —
 * more than seven days — and a handful of such rows drags the mean and inflates the standard
 * deviation enough that genuine degradation stops looking anomalous. Median and MAD have a 50%
 * breakdown point: half the observations would have to be contaminated before the estimate moves.
 *
 * <p>All methods are static, side-effect free, and never mutate their arguments.
 */
public final class RobustStats {

    /**
     * Reciprocal of the 75th-percentile point of the standard normal, {@code 1 / 1.4826}. Scaling by
     * this makes MAD a consistent estimator of the standard deviation for normally distributed data,
     * so a robust z-score stays comparable to a conventional one.
     */
    public static final double MAD_SCALE = 0.6745;

    /**
     * Scaling that makes the mean absolute deviation a consistent estimator of sigma,
     * {@code sqrt(pi/2)}. Used only as a fallback when MAD collapses to zero.
     */
    private static final double MEAN_AD_SCALE = 1.2533141373155001;

    private static final double EPSILON = 1e-12;

    private RobustStats() {
    }

    /**
     * Median of the supplied values, ignoring nulls and non-finite entries.
     *
     * @param values sample; may be null or empty
     * @return the median, or {@link Double#NaN} when there is nothing finite to summarise
     */
    public static double median(double[] values) {
        double[] clean = finite(values);
        if (clean.length == 0) {
            return Double.NaN;
        }
        Arrays.sort(clean);
        int mid = clean.length / 2;
        if (clean.length % 2 == 1) {
            return clean[mid];
        }
        // Averaged rather than lower-median so the estimate is unbiased on even-length samples.
        return (clean[mid - 1] + clean[mid]) / 2.0;
    }

    /**
     * Median absolute deviation from the median, {@code median(|x - median(x)|)}.
     *
     * <p>Returned unscaled. {@link #robustZ} applies {@link #MAD_SCALE}; keeping the raw value here
     * means callers that want a plain dispersion measure are not silently handed a rescaled one.
     *
     * @param values sample; may be null or empty
     * @return the MAD, or {@link Double#NaN} when there is nothing finite to summarise
     */
    public static double mad(double[] values) {
        double[] clean = finite(values);
        if (clean.length == 0) {
            return Double.NaN;
        }
        double centre = median(clean);
        double[] deviations = new double[clean.length];
        for (int i = 0; i < clean.length; i++) {
            deviations[i] = Math.abs(clean[i] - centre);
        }
        return median(deviations);
    }

    /**
     * Robust z-score, {@code 0.6745 * (x - median) / mad}.
     *
     * <p>Guards the degenerate case. A zero MAD means over half the sample sits on the median — a
     * flat series — and the naive formula would divide by zero and report every departure as
     * infinitely anomalous. There is no meaningful scale to normalise by in that situation, so this
     * returns {@code 0.0}: a flat history is evidence of nothing, not evidence of everything. Callers
     * that need to distinguish "no signal" from "no scale" should use {@link #robustZ(double, double[])},
     * which falls back to the mean absolute deviation before giving up.
     *
     * @param value  the observation to score
     * @param median centre of the reference distribution
     * @param mad    median absolute deviation of the reference distribution
     * @return the robust z-score, or {@code 0.0} when it cannot be computed
     */
    public static double robustZ(double value, double median, double mad) {
        if (!Double.isFinite(value) || !Double.isFinite(median) || !Double.isFinite(mad) || mad <= EPSILON) {
            return 0.0;
        }
        double z = MAD_SCALE * (value - median) / mad;
        return Double.isFinite(z) ? z : 0.0;
    }

    /**
     * Robust z-score of a value against a reference sample, with a dispersion fallback.
     *
     * <p>Small monthly series make an exactly-zero MAD common — with four points, two identical
     * values are enough. Rather than discarding the comparison, this falls back to the scaled mean
     * absolute deviation, which only collapses when every observation is truly identical.
     *
     * @param value  the observation to score
     * @param sample reference distribution
     * @return the robust z-score, or {@code 0.0} when the sample carries no usable scale
     */
    public static double robustZ(double value, double[] sample) {
        double[] clean = finite(sample);
        if (clean.length == 0) {
            return 0.0;
        }
        double centre = median(clean);
        double dispersion = mad(clean);
        if (Double.isFinite(dispersion) && dispersion > EPSILON) {
            return robustZ(value, centre, dispersion);
        }

        double meanAbsoluteDeviation = 0.0;
        for (double v : clean) {
            meanAbsoluteDeviation += Math.abs(v - centre);
        }
        meanAbsoluteDeviation /= clean.length;
        if (meanAbsoluteDeviation <= EPSILON) {
            return 0.0;
        }
        double z = (value - centre) / (MEAN_AD_SCALE * meanAbsoluteDeviation);
        return Double.isFinite(z) ? z : 0.0;
    }

    /**
     * Exponentially weighted moving average, oldest observation first.
     *
     * <p>Complements the z-score: a robust z catches a single sharp break, an EWMA catches slow drift
     * that never produces one large step but ends up far from where it started.
     *
     * @param values sample, oldest first
     * @param alpha  smoothing factor in {@code (0, 1]}; higher tracks recent values more closely
     * @return the EWMA, or {@link Double#NaN} when there is nothing finite to summarise
     */
    public static double ewma(double[] values, double alpha) {
        double[] clean = finite(values);
        if (clean.length == 0) {
            return Double.NaN;
        }
        double a = Math.clamp(alpha, EPSILON, 1.0);
        double ewma = clean[0];
        for (int i = 1; i < clean.length; i++) {
            ewma = a * clean[i] + (1 - a) * ewma;
        }
        return ewma;
    }

    /**
     * Converts a collection of boxed values into a primitive array, dropping nulls.
     *
     * @param values boxed sample; may be null
     * @return a primitive array of the finite values, never null
     */
    public static double[] toArray(Collection<Double> values) {
        if (values == null || values.isEmpty()) {
            return new double[0];
        }
        return values.stream()
                .filter(v -> v != null && Double.isFinite(v))
                .mapToDouble(Double::doubleValue)
                .toArray();
    }

    /**
     * Copies out the finite entries, so callers' arrays are never sorted in place.
     */
    private static double[] finite(double[] values) {
        if (values == null || values.length == 0) {
            return new double[0];
        }
        double[] buffer = new double[values.length];
        int n = 0;
        for (double v : values) {
            if (Double.isFinite(v)) {
                buffer[n++] = v;
            }
        }
        return n == values.length ? buffer : Arrays.copyOf(buffer, n);
    }
}
