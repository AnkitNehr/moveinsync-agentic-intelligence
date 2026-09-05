package com.moveinsync.mi.delivery;

import org.springframework.stereotype.Service;

/**
 * Ships the message to the operator console. No email leaves the building.
 *
 * <p>That is the deployability seam: a production {@code NotificationSink} would POST to Slack or
 * SMTP. This one records {@link Communication#SENT} against the console channel so the demo can show
 * an act without pretending to have a mail server.
 */
@Service
public class ConsoleNotificationSink implements NotificationSink {

    @Override
    public Communication deliver(Communication message) {
        if (message == null) {
            return null;
        }
        if (Communication.BLOCKED.equals(message.status())) {
            return message;
        }
        return message.withStatus(Communication.SENT, message.blockedReason());
    }

    @Override
    public String channel() {
        return Communication.CHANNEL_CONSOLE;
    }
}
