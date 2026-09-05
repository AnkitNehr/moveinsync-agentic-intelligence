package com.moveinsync.mi.model;

/**
 * One entity's share of an aggregate movement, split into rate and mix effects.
 *
 * <p>Standard shift-share decomposition. The rate effect is how much the aggregate moved because
 * this entity's own performance changed; the mix effect is how much it moved because the entity's
 * share of volume changed while its performance held. Both matter, and conflating them produces
 * wrong conclusions — in the June OTA drop the vendor mix barely moves (max share shift 0.79 pts,
 * mix effect approximately zero), so the entire movement is rate-driven and any narrative blaming
 * a shift of volume between vendors would be fabricated.
 *
 * @param entity      dimension member, e.g. a vendor id, an office, a product type
 * @param rateEffect  points of aggregate movement attributable to this entity's own rate change
 * @param mixEffect   points attributable to this entity's change in volume share
 * @param total       rateEffect + mixEffect; the entity's full contribution
 * @param shareBefore entity's share of total volume in the prior period, 0.0 to 1.0
 * @param shareAfter  entity's share of total volume in the current period, 0.0 to 1.0
 */
public record Contribution(
        String entity,
        double rateEffect,
        double mixEffect,
        double total,
        double shareBefore,
        double shareAfter) {
}
