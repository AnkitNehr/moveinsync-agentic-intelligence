package com.moveinsync.mi.model;

import java.util.List;

/**
 * A statistically significant, volume-gated movement in one metric on one dimension.
 *
 * <p>Findings are the candidate pool the incident builder draws from. They are produced by scanning
 * <em>every</em> metric across <em>every</em> dimension and ranking by score — never by assuming
 * where the problem lives. In the June OTA drop the movement concentrates in trip_direction
 * (LOGIN -5.17 vs LOGOUT -0.77), product_type (BUS -6.25 vs CAB -2.20) and route_source
 * (MANUAL -6.22 vs AUTO -2.20), while vendor barely moves at all — a scanner hard-wired to look at
 * vendors would have found nothing and reported a false all-clear.
 *
 * @param id            stable finding identifier
 * @param metricId      metric that moved
 * @param dimension     dimension the movement was detected on, e.g. {@code trip_direction}
 * @param entity        dimension member, e.g. {@code LOGIN}
 * @param period        current period label
 * @param priorPeriod   comparison period label
 * @param current       metric value in the current period
 * @param prior         metric value in the prior period
 * @param deltaPts      current minus prior, in points for rate metrics
 * @param sampleSize    rows behind the current period value; must clear {@code app.scanner.min-sample}
 * @param robustZ       median/MAD z-score of the delta against the series history
 * @param score         composite ranking score used to select the top-N findings
 * @param observation   the full metric observation with all reference frames
 * @param contributions shift-share decomposition of the movement across child entities
 */
public record Finding(
        String id,
        String metricId,
        String dimension,
        String entity,
        String period,
        String priorPeriod,
        double current,
        double prior,
        double deltaPts,
        long sampleSize,
        double robustZ,
        double score,
        MetricObservation observation,
        List<Contribution> contributions) {

    public Finding {
        contributions = contributions == null ? List.of() : List.copyOf(contributions);
    }
}
