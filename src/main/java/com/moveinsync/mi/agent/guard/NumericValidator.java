package com.moveinsync.mi.agent.guard;

import com.moveinsync.mi.model.Contribution;
import com.moveinsync.mi.model.Finding;
import com.moveinsync.mi.model.Industry;
import com.moveinsync.mi.model.MetricObservation;
import com.moveinsync.mi.model.Peer;
import com.moveinsync.mi.model.References;
import com.moveinsync.mi.model.Sla;
import com.moveinsync.mi.model.Trend;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Rejects generated text that cites a number the deterministic layer never computed.
 *
 * <h2>The failure this exists to stop</h2>
 *
 * <p>A language model asked to explain a 2.85-point OTA drop will, given the chance, write "a 12%
 * decline in vendor V-114's on-time performance drove roughly 60% of the gap". Every clause of that
 * is plausible, none of it is checkable by a reader, and if the shift-share decomposition says the
 * mix effect is approximately zero it is also false. Prose is not auditable; numbers are. So every
 * number in generated text is extracted and matched against the observations and contributions that
 * were actually supplied, and text that cites anything else is refused.
 *
 * <p>The agents use the result as a retry-then-fall-back gate: one retry naming the offending
 * figures, then a deterministic template. That ordering matters — the failure mode of a numeric
 * guard is not a bad narrative, it is a missing one, and a template built from real contributions is
 * always available.
 *
 * <h2>What counts as "appears in the data"</h2>
 *
 * <p>Exact string equality would reject almost everything, since a model writing about
 * {@code 0.9246} will naturally write "92.46%". Matching therefore accepts:
 *
 * <ul>
 *   <li>the value itself, and its absolute value — narratives say "fell by 5.17", not "by -5.17";
 *   <li>its percentage form, for values that look like proportions;
 *   <li>any rounding of the above to zero, one, two or three decimal places, so "92.5%" and "93%"
 *       are both legitimate renderings of 92.46;
 *   <li>literal tokens supplied with the context — period labels such as {@code 2026-06} and entity
 *       names that contain digits, e.g. {@code SPOT_2.0} — which are masked out before scanning so
 *       they are never mistaken for claims;
 *   <li>cardinalities of the supplied collections, so "across 4 segments" is checkable rather than
 *       automatically suspect.
 * </ul>
 *
 * <p>Everything else is an offending number. The guard is deliberately biased toward false
 * positives: the cost of one is a slightly plainer template, and the cost of a false negative is a
 * fabricated figure in an operations email.
 */
@Service
public class NumericValidator {

    private static final Logger log = LoggerFactory.getLogger(NumericValidator.class);

    /**
     * Numbers as they appear in prose: optional sign, optional thousands separators, optional
     * fractional part. Currency symbols and a trailing percent sign are handled outside the group so
     * the captured token is always parseable.
     */
    private static final Pattern NUMBER = Pattern.compile("[-+]?\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|[-+]?\\d+(?:\\.\\d+)?");

    /** Period-shaped tokens are labels, not claims: {@code 2026-06}, {@code 2026-06-15}. */
    private static final Pattern PERIOD_LIKE = Pattern.compile("\\d{4}-\\d{2}(?:-\\d{2})?");

    /** Bare calendar years. A year is a label; treating it as an unsupported figure is noise. */
    private static final Pattern YEAR_LIKE = Pattern.compile("\\b(?:19|20)\\d{2}\\b");

    /** Decimal places a narrative may legitimately round a supplied figure to. */
    private static final int[] ROUNDING_PLACES = {0, 1, 2, 3};

    /** Absolute slack for floating-point comparison of two figures meant to be identical. */
    private static final double EPSILON = 1e-6;

    /** Offending numbers reported before the list is truncated, to keep retry prompts short. */
    private static final int MAX_REPORTED = 12;

    /**
     * Outcome of a check.
     *
     * @param ok               true when every number in the text traces to supplied data
     * @param offendingNumbers the unsupported figures, as written in the text, in order of first
     *                         appearance and de-duplicated
     */
    public record ValidationResult(boolean ok, List<String> offendingNumbers) {

        public ValidationResult {
            offendingNumbers = offendingNumbers == null ? List.of() : List.copyOf(offendingNumbers);
        }

        /** A passing result. */
        public static ValidationResult pass() {
            return new ValidationResult(true, List.of());
        }

        /** Comma-separated offenders, for naming them back to the model on the retry. */
        public String offendingList() {
            return String.join(", ", offendingNumbers);
        }
    }

    /**
     * The set of figures and labels a piece of text is allowed to contain.
     *
     * @param allowedValues   every numeric value derivable from the supplied data, pre-expanded to
     *                        include absolute and percentage forms
     * @param allowedLiterals digit-bearing labels (periods, entity names) masked out before scanning
     */
    public record NumericContext(Set<Double> allowedValues, Set<String> allowedLiterals) {

        public NumericContext {
            allowedValues = allowedValues == null ? Set.of() : Set.copyOf(allowedValues);
            allowedLiterals = allowedLiterals == null ? Set.of() : Set.copyOf(allowedLiterals);
        }

        /** True when there is nothing to validate against, in which case any figure is unsupported. */
        public boolean isEmpty() {
            return allowedValues.isEmpty();
        }
    }

    // ---- public API -----------------------------------------------------------------------------

    /**
     * Validates text against observations and contributions.
     *
     * @param text          generated prose; null or blank passes trivially
     * @param observations  observations supplied to the agent, may be null
     * @param contributions contributions supplied to the agent, may be null
     * @return the validation result; never null
     */
    public ValidationResult validate(
            String text,
            Collection<MetricObservation> observations,
            Collection<Contribution> contributions) {
        return validate(text, context(observations, contributions));
    }

    /**
     * Validates text against findings, which is what the agents actually hold.
     *
     * <p>A finding carries its current and prior values, its delta, its sample size, its robust
     * z-score, its full {@link MetricObservation} with every reference frame, and its contributions —
     * so this derives a much richer allowed set than observations alone, and the period label and
     * entity name become masked literals rather than suspect figures.
     */
    public ValidationResult validateAgainstFindings(String text, Collection<Finding> findings) {
        return validate(text, contextOf(findings));
    }

    /**
     * Core check.
     *
     * @param text    generated prose
     * @param context allowed figures and labels
     * @return the validation result; never null
     */
    public ValidationResult validate(String text, NumericContext context) {
        if (text == null || text.isBlank()) {
            return ValidationResult.pass();
        }
        NumericContext resolved = context == null ? new NumericContext(Set.of(), Set.of()) : context;

        String masked = mask(text, resolved.allowedLiterals());

        Set<String> offenders = new LinkedHashSet<>();
        Matcher matcher = NUMBER.matcher(masked);
        while (matcher.find()) {
            String token = matcher.group();
            Double parsed = parse(token);
            if (parsed == null) {
                continue;
            }
            if (!isSupported(parsed, resolved.allowedValues())) {
                offenders.add(token);
                if (offenders.size() >= MAX_REPORTED) {
                    break;
                }
            }
        }

        if (offenders.isEmpty()) {
            return ValidationResult.pass();
        }
        log.debug("Numeric guard rejected {} figure(s): {}", offenders.size(), offenders);
        return new ValidationResult(false, new ArrayList<>(offenders));
    }

    // ---- context construction -------------------------------------------------------------------

    /** Builds an allowed set from observations and contributions. */
    public NumericContext context(
            Collection<MetricObservation> observations, Collection<Contribution> contributions) {
        Set<Double> values = new TreeSet<>();
        Set<String> literals = new LinkedHashSet<>();

        if (observations != null) {
            for (MetricObservation observation : observations) {
                addObservation(observation, values, literals);
            }
            addValue(values, observations.size());
        }
        if (contributions != null) {
            for (Contribution contribution : contributions) {
                addContribution(contribution, values, literals);
            }
            addValue(values, contributions.size());
        }
        return new NumericContext(values, literals);
    }

    /** Builds an allowed set from findings, including their observations and contributions. */
    public NumericContext contextOf(Collection<Finding> findings) {
        Set<Double> values = new TreeSet<>();
        Set<String> literals = new LinkedHashSet<>();

        if (findings != null) {
            Set<String> entities = new LinkedHashSet<>();
            for (Finding finding : findings) {
                if (finding == null) {
                    continue;
                }
                addValue(values, finding.current());
                addValue(values, finding.prior());
                addValue(values, finding.deltaPts());
                addValue(values, finding.sampleSize());
                addValue(values, finding.robustZ());
                addValue(values, finding.score());

                addLiteral(literals, finding.entity());
                addLiteral(literals, finding.period());
                addLiteral(literals, finding.priorPeriod());
                addLiteral(literals, finding.dimension());
                addLiteral(literals, finding.metricId());
                addLiteral(literals, finding.id());

                if (finding.entity() != null) {
                    entities.add(finding.entity());
                }
                addObservation(finding.observation(), values, literals);
                for (Contribution contribution : finding.contributions()) {
                    addContribution(contribution, values, literals);
                }
            }
            // Cardinalities: "four segments", "three vendors" are checkable claims, so allow them.
            addValue(values, findings.size());
            addValue(values, entities.size());
        }
        return new NumericContext(values, literals);
    }

    private void addObservation(MetricObservation observation, Set<Double> values, Set<String> literals) {
        if (observation == null) {
            return;
        }
        addValue(values, observation.value());
        addValue(values, observation.sampleSize());
        addValue(values, observation.severity());
        addLiteral(literals, observation.entity());
        addLiteral(literals, observation.period());
        addLiteral(literals, observation.metricId());

        if (observation.quality() != null) {
            addValue(values, observation.quality().coverage());
            addValue(values, observation.quality().caveats().size());
        }
        addReferences(observation.references(), values);
    }

    private void addReferences(References references, Set<Double> values) {
        if (references == null) {
            return;
        }
        Trend trend = references.trend();
        if (trend != null) {
            addValue(values, trend.prior());
            addValue(values, trend.delta());
            addValue(values, trend.robustZ());
        }
        Sla sla = references.sla();
        if (sla != null) {
            addValue(values, sla.target());
            addValue(values, sla.delta());
        }
        Peer peer = references.peer();
        if (peer != null) {
            addValue(values, peer.cohortMedian());
            addValue(values, peer.percentile());
        }
        Industry industry = references.industry();
        if (industry != null) {
            addValue(values, industry.benchmark());
        }
    }

    private void addContribution(Contribution contribution, Set<Double> values, Set<String> literals) {
        if (contribution == null) {
            return;
        }
        addValue(values, contribution.rateEffect());
        addValue(values, contribution.mixEffect());
        addValue(values, contribution.total());
        addValue(values, contribution.shareBefore());
        addValue(values, contribution.shareAfter());
        addLiteral(literals, contribution.entity());
    }

    /**
     * Adds a value and every form a narrative might legitimately render it in.
     *
     * <p>Absolute value, because prose says "fell by 5.17" for a delta of -5.17. Percentage form for
     * anything that looks like a proportion, because 0.9246 and 92.46% are the same fact. Rounding is
     * handled at comparison time rather than by enumerating rounded variants here, so the allowed set
     * stays small.
     */
    private static void addValue(Set<Double> values, Double value) {
        if (value == null || !Double.isFinite(value)) {
            return;
        }
        double v = value;
        values.add(v);
        values.add(Math.abs(v));
        if (Math.abs(v) <= 1.0) {
            values.add(v * 100.0);
            values.add(Math.abs(v) * 100.0);
        }
    }

    private static void addValue(Set<Double> values, double value) {
        addValue(values, Double.valueOf(value));
    }

    private static void addValue(Set<Double> values, long value) {
        addValue(values, Double.valueOf(value));
    }

    /** Registers a digit-bearing label so it is masked rather than scanned. */
    private static void addLiteral(Set<String> literals, String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        String trimmed = token.trim();
        for (int i = 0; i < trimmed.length(); i++) {
            if (Character.isDigit(trimmed.charAt(i))) {
                literals.add(trimmed);
                return;
            }
        }
    }

    // ---- matching -------------------------------------------------------------------------------

    private static boolean isSupported(double cited, Set<Double> allowed) {
        for (Double candidate : allowed) {
            if (candidate == null) {
                continue;
            }
            double value = candidate;
            if (Math.abs(cited - value) <= EPSILON + EPSILON * Math.abs(value)) {
                return true;
            }
            for (int places : ROUNDING_PLACES) {
                if (Math.abs(round(value, places) - cited) <= EPSILON) {
                    return true;
                }
            }
        }
        return false;
    }

    private static double round(double value, int places) {
        double factor = Math.pow(10.0, places);
        return Math.round(value * factor) / factor;
    }

    private static Double parse(String token) {
        try {
            return Double.valueOf(token.replace(",", "").replace("+", ""));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * Blanks out label-shaped text before number extraction.
     *
     * <p>Replacement preserves length so the scan still reports sensible positions, and longer
     * literals are masked first so {@code SPOT_2.0} is consumed whole rather than leaving a stray
     * {@code 2.0} behind.
     */
    private static String mask(String text, Set<String> literals) {
        String masked = text;

        List<String> ordered = new ArrayList<>(literals);
        ordered.sort((a, b) -> Integer.compare(b.length(), a.length()));
        for (String literal : ordered) {
            masked = replaceAllLiteral(masked, literal);
        }
        masked = PERIOD_LIKE.matcher(masked).replaceAll(NumericValidator::blanks);
        masked = YEAR_LIKE.matcher(masked).replaceAll(NumericValidator::blanks);
        return masked;
    }

    private static String blanks(java.util.regex.MatchResult match) {
        return " ".repeat(match.group().length());
    }

    private static String replaceAllLiteral(String text, String literal) {
        if (literal.isEmpty()) {
            return text;
        }
        // Case-insensitive search, but only when lower-casing is length-preserving. A few Unicode
        // characters expand when lower-cased, which would shift every index and blank the wrong span.
        String haystack = text.toLowerCase(Locale.ROOT);
        String needle = literal.toLowerCase(Locale.ROOT);
        if (haystack.length() != text.length() || needle.length() != literal.length()) {
            haystack = text;
            needle = literal;
        }

        StringBuilder out = null;
        int from = 0;
        int at;
        while ((at = haystack.indexOf(needle, from)) >= 0) {
            if (out == null) {
                out = new StringBuilder(text);
            }
            for (int i = at; i < at + needle.length(); i++) {
                out.setCharAt(i, ' ');
            }
            from = at + needle.length();
        }
        return out == null ? text : out.toString();
    }
}
