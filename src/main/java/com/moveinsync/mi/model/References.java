package com.moveinsync.mi.model;

/**
 * The four reference frames that turn a bare number into an interpretable observation.
 *
 * <p>A metric value on its own says nothing. 92.46% OTA is a crisis against a 95% SLA, unremarkable
 * against a 93% industry benchmark, and alarming only once you know the prior month was 95.31%.
 * Every frame is independently nullable so a metric can carry whichever comparisons actually apply.
 *
 * @param trend    period-over-period movement
 * @param sla      contractual target comparison
 * @param peer     cohort comparison against sibling entities
 * @param industry external benchmark comparison
 */
public record References(Trend trend, Sla sla, Peer peer, Industry industry) {

    public static References empty() {
        return new References(Trend.none(), Sla.notApplicable(), Peer.none(), Industry.none());
    }
}
