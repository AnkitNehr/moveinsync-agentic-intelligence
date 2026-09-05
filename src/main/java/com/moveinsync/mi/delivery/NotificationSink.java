package com.moveinsync.mi.delivery;

/**
 * Where a drafted communication actually goes.
 *
 * <p>The assessment ships a console sink: it writes to the outbox and never opens SMTP. A tenant
 * deployment swaps this for Slack, email or ServiceNow without touching ActionGuard or the pipeline.
 */
public interface NotificationSink {

    /**
     * Accepts a composed message. Implementations must not throw on a delivery failure that is
     * merely operational — they record the outcome on the returned {@link Communication}.
     */
    Communication deliver(Communication message);

    /** Channel id recorded on every message this sink handles, e.g. {@code console}. */
    String channel();
}
