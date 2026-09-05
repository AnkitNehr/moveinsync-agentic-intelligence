package com.moveinsync.mi.controller;

import com.moveinsync.mi.ingest.DuckDbService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.server.ResponseStatusException;

/**
 * Turns every exception the API can throw into a predictable {@code {error, message}} document.
 *
 * <p>Two things matter here. First, the status codes have to be honest: a console distinguishing
 * "your request was wrong" (400) from "that does not exist" (404) from "the fact store is not loaded"
 * (503) can retry the right one, while a blanket 500 forces a human to read logs. Second, the message
 * must be usable — {@link com.moveinsync.mi.metric.MetricCatalog} throws with the list of known metric
 * ids attached, and that list survives all the way to the client rather than being flattened into
 * "Internal Server Error".
 *
 * <p>Stack traces never cross the wire. The 500 handler logs the trace and returns the exception
 * class and message only, which is enough to correlate against the log without exposing internals.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * The error document every failing endpoint returns.
     *
     * @param error     stable machine-readable code, e.g. {@code not_found}
     * @param message   human-readable explanation, safe to display
     * @param path      request path that failed
     * @param timestamp ISO-8601 instant the failure was rendered
     */
    public record ApiError(String error, String message, String path, String timestamp) {

        static ApiError of(String error, String message, HttpServletRequest request) {
            return new ApiError(
                    error,
                    message == null || message.isBlank() ? error : message,
                    request == null ? null : request.getRequestURI(),
                    Instant.now().toString());
        }
    }

    /** A resource that legitimately does not exist. */
    @ExceptionHandler(NotFoundException.class)
    public ResponseEntity<ApiError> notFound(NotFoundException e, HttpServletRequest request) {
        log.debug("404 on {}: {}", request.getRequestURI(), e.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiError.of("not_found", e.getMessage(), request));
    }

    /**
     * A malformed request: an unknown metric id, a period that is not {@code yyyy-MM}, a persona the
     * platform does not render.
     */
    @ExceptionHandler({
            IllegalArgumentException.class,
            MissingServletRequestParameterException.class,
            MethodArgumentTypeMismatchException.class,
            HttpMessageNotReadableException.class})
    public ResponseEntity<ApiError> badRequest(Exception e, HttpServletRequest request) {
        log.debug("400 on {}: {}", request.getRequestURI(), e.getMessage());
        return ResponseEntity.badRequest()
                .body(ApiError.of("bad_request", e.getMessage(), request));
    }

    /**
     * A valid request that conflicts with current state — most often a second pipeline run while one
     * is already executing. 409 rather than 500: nothing is broken, the caller should simply retry.
     */
    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<ApiError> conflict(IllegalStateException e, HttpServletRequest request) {
        log.info("409 on {}: {}", request.getRequestURI(), e.getMessage());
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ApiError.of("conflict", e.getMessage(), request));
    }

    /**
     * The fact store could not answer. 503 rather than 500, because the usual cause is that ingest has
     * not finished and the correct client behaviour is to wait rather than to report a defect.
     */
    @ExceptionHandler(DuckDbService.DuckDbQueryException.class)
    public ResponseEntity<ApiError> factStoreUnavailable(
            DuckDbService.DuckDbQueryException e, HttpServletRequest request) {
        log.error("503 on {}: {}", request.getRequestURI(), e.toString());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ApiError.of("fact_store_unavailable",
                        "The fact store could not answer this query: " + e.getMessage(), request));
    }

    /** Anything a controller raised with an explicit status keeps that status. */
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ApiError> explicitStatus(ResponseStatusException e, HttpServletRequest request) {
        return ResponseEntity.status(e.getStatusCode())
                .body(ApiError.of("error", e.getReason(), request));
    }

    /** The genuine last resort. Logged with a trace; the client gets the class and message only. */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> unexpected(Exception e, HttpServletRequest request) {
        log.error("500 on {}: {}", request.getRequestURI(), e.toString(), e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiError.of("internal_error",
                        e.getClass().getSimpleName() + ": " + e.getMessage(), request));
    }
}
