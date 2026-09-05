package com.moveinsync.mi.controller;

/**
 * The requested resource does not exist. Mapped to HTTP 404 by {@link GlobalExceptionHandler}.
 *
 * <p>Distinct from {@link IllegalArgumentException}, which the handler maps to 400. The difference is
 * not pedantry: "you asked for metric {@code otta}" is a client typo, while "incident inc-ota-down
 * -2026-06 is not in memory" is a legitimate request for something that is genuinely absent, and a
 * console that cannot tell the two apart will retry the wrong one.
 */
public class NotFoundException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public NotFoundException(String message) {
        super(message);
    }

    /** Builds the standard "unknown id, here is what exists" message. */
    public static NotFoundException of(String what, String id, Object known) {
        return new NotFoundException(
                "Unknown " + what + " '" + id + "'." + (known == null ? "" : " Known: " + known));
    }
}
