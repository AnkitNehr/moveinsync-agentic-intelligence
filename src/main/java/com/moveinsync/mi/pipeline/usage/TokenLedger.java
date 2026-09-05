package com.moveinsync.mi.pipeline.usage;

import com.moveinsync.mi.pipeline.spi.UsageLedger;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

/**
 * The single in-process token ledger. Every LLM call in the platform reports here.
 *
 * <p>Marked {@link Primary} deliberately: {@code RunSummary.promptTokens} must come from one
 * authoritative counter. If a second {@code UsageLedger} bean ever appears, injection stays
 * unambiguous and this remains the one the pipeline reads — a run summary assembled from two
 * partial ledgers would under-report spend without any error to notice.
 *
 * <h2>Pricing</h2>
 *
 * Rates are USD per million tokens and are configurable, because published prices change and a
 * hard-coded constant would quietly drift into being wrong. Defaults are the list rates for the
 * models named in {@code app.llm}: Opus 5 at $5 / $25, Sonnet 5 at $3 / $15, Haiku 4.5 at $1 / $5.
 * An unrecognised model falls back to the configured default rate rather than pricing at zero —
 * a run whose cost silently reads $0.00 because of a model-id typo is worse than one that is
 * approximately right.
 */
@Service
@Primary
public class TokenLedger implements UsageLedger {

    private static final Logger log = LoggerFactory.getLogger(TokenLedger.class);

    private static final double MILLION = 1_000_000.0;

    private final Object lock = new Object();
    private final Map<String, Usage> byStage = new LinkedHashMap<>();
    private final Map<String, double[]> rates;
    private final double[] defaultRate;

    /**
     * @param opusInput     USD per million prompt tokens on the reasoning / narrative tier
     * @param opusOutput    USD per million completion tokens on the reasoning / narrative tier
     * @param sonnetInput   USD per million prompt tokens on the triage tier
     * @param sonnetOutput  USD per million completion tokens on the triage tier
     * @param haikuInput    USD per million prompt tokens on the chat tier
     * @param haikuOutput   USD per million completion tokens on the chat tier
     * @param defaultInput  fallback prompt rate for an unrecognised model id
     * @param defaultOutput fallback completion rate for an unrecognised model id
     */
    public TokenLedger(
            @Value("${app.llm.pricing.opus.input-per-mtok:5.00}") double opusInput,
            @Value("${app.llm.pricing.opus.output-per-mtok:25.00}") double opusOutput,
            @Value("${app.llm.pricing.sonnet.input-per-mtok:3.00}") double sonnetInput,
            @Value("${app.llm.pricing.sonnet.output-per-mtok:15.00}") double sonnetOutput,
            @Value("${app.llm.pricing.haiku.input-per-mtok:1.00}") double haikuInput,
            @Value("${app.llm.pricing.haiku.output-per-mtok:5.00}") double haikuOutput,
            @Value("${app.llm.pricing.default.input-per-mtok:3.00}") double defaultInput,
            @Value("${app.llm.pricing.default.output-per-mtok:15.00}") double defaultOutput) {

        Map<String, double[]> table = new LinkedHashMap<>();
        table.put("opus", new double[] {opusInput, opusOutput});
        table.put("sonnet", new double[] {sonnetInput, sonnetOutput});
        table.put("haiku", new double[] {haikuInput, haikuOutput});
        this.rates = Map.copyOf(table);
        this.defaultRate = new double[] {defaultInput, defaultOutput};
    }

    @Override
    public void record(String stage, String model, long promptTokens, long completionTokens) {
        long prompt = Math.max(0L, promptTokens);
        long completion = Math.max(0L, completionTokens);
        if (prompt == 0L && completion == 0L) {
            // A zero-token call is either a deterministic stage or a bookkeeping error. Either way
            // there is nothing to price, and recording it would inflate the call count.
            return;
        }

        double cost = price(model, prompt, completion);
        String key = stage == null || stage.isBlank() ? "UNATTRIBUTED" : stage;

        synchronized (lock) {
            byStage.merge(key, new Usage(prompt, completion, 1L, cost), Usage::plus);
        }
        log.debug("Usage {} on {}: {} prompt + {} completion tokens (${})",
                key, model, prompt, completion, String.format(Locale.ROOT, "%.4f", cost));
    }

    @Override
    public Usage total() {
        synchronized (lock) {
            return byStage.values().stream().reduce(Usage.ZERO, Usage::plus);
        }
    }

    @Override
    public Usage forStage(String stage) {
        synchronized (lock) {
            return byStage.getOrDefault(stage, Usage.ZERO);
        }
    }

    @Override
    public Map<String, Usage> byStage() {
        synchronized (lock) {
            return Map.copyOf(byStage);
        }
    }

    @Override
    public void reset() {
        synchronized (lock) {
            byStage.clear();
        }
    }

    /**
     * Prices one call.
     *
     * <p>Matching is on the model <em>family</em> rather than the exact id, so
     * {@code claude-opus-5} and any future dated variant of it both resolve without a config change.
     *
     * @param model            model id; null or unrecognised uses the default rate
     * @param promptTokens     prompt tokens
     * @param completionTokens completion tokens
     * @return spend in USD
     */
    double price(String model, long promptTokens, long completionTokens) {
        double[] rate = rateFor(model);
        return (promptTokens / MILLION) * rate[0] + (completionTokens / MILLION) * rate[1];
    }

    private double[] rateFor(String model) {
        if (model == null || model.isBlank()) {
            return defaultRate;
        }
        String lower = model.toLowerCase(Locale.ROOT);
        for (Map.Entry<String, double[]> entry : rates.entrySet()) {
            if (lower.contains(entry.getKey())) {
                return entry.getValue();
            }
        }
        log.debug("No price configured for model '{}'; using the default rate", model);
        return defaultRate;
    }
}
