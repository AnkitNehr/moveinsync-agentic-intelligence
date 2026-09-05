package com.moveinsync.mi;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Entry point for the MoveInSync Mobility Intelligence platform.
 *
 * <p>The application ingests the raw ride / bill / alert / employee / feedback CSV extracts into an
 * in-process DuckDB instance, scans every metric-by-dimension series for statistically meaningful
 * movement, attributes those movements to contributing entities, and promotes the survivors into
 * governed incidents with LLM-authored narratives.
 */
@SpringBootApplication
@EnableScheduling
@ConfigurationPropertiesScan("com.moveinsync.mi.config")
public class MobilityIntelligenceApplication {

    public static void main(String[] args) {
        SpringApplication.run(MobilityIntelligenceApplication.class, args);
    }
}
