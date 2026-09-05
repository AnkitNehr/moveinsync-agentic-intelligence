# Backend image: Spring Boot + in-process DuckDB.
# The CSV extracts are not baked in — mount them at runtime (see docker-compose.yml).

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/raw /data/state \
    && chown -R app:app /data/state

COPY --from=build --chown=app:app /src/target/mobility-intelligence-1.0.0.jar /app/app.jar
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod 755 /app/docker-entrypoint.sh

# Starts as root only long enough to chown the bind-mounted state dir, then gosu to app.
EXPOSE 8080

ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75.0" \
    APP_DATA_RAW_PATH=/data/raw \
    APP_STATE_DIR=/data/state

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=8 \
    CMD curl -fsS http://127.0.0.1:8080/api/health >/dev/null || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
