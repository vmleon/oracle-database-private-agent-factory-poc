package com.bank.appbackend.research;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * The no-lean rule, enforced between the research agent and the reviewer.
 *
 * <p>The rule itself — organise the evidence, name no outcome — is written into
 * the agent's instructions, where it is a request. This class is the rule:
 * every summary passes through {@link #screen} before it is persisted or shown,
 * so one that concludes reaches neither.
 *
 * <p>A summary that endorsed the tier would be a second recommendation beside
 * the deterministic one, composed by a model and grounded in nothing, and it
 * would turn human review into agreement with a machine — the failure mode the
 * human-in-the-loop design exists to prevent.
 *
 * <p>The reviewer is bank staff, so unlike {@link com.bank.appbackend.chat.Disclosure}
 * this bars no vocabulary: tier names, figures, ratios and reason codes all
 * belong in a reviewer's summary. Only a verdict is barred.
 *
 * <p>Pure and free of Spring, so the rules are unit-testable on the host.
 */
public final class ResearchSummary {

    /** Shown when a summary concludes. Names no outcome itself. */
    public static final String BLOCKED =
            "Research could not be completed for this case. The evidence is on this screen; "
            + "the decision is yours to make.";

    private static final List<Rule> VERDICTS = List.of(
            new Rule(Pattern.compile("(?i)\\bI\\s+(recommend|suggest|advise)\\b"), "a recommendation"),
            new Rule(Pattern.compile("(?i)\\bmy\\s+recommendation\\b"), "a recommendation"),
            new Rule(Pattern.compile(
                    "(?i)\\b(should|ought\\s+to)\\s+be\\s+(approved|declined|rejected)\\b"),
                    "a verdict"),
            new Rule(Pattern.compile(
                    "(?i)\\byou\\s+should\\s+(approve|decline|reject)\\b"), "a verdict"),
            new Rule(Pattern.compile("(?i)\\bleans?\\s+towards?\\b"), "a lean"),
            new Rule(Pattern.compile("(?i)\\bon\\s+balance\\b"), "a lean"),
            new Rule(Pattern.compile(
                    "(?i)\\bevidence\\s+(supports|favou?rs|points\\s+to)\\s+"
                            + "(approving|declining|approval|decline|rejection)\\b"),
                    "a lean"),
            new Rule(Pattern.compile(
                    "(?i)\\bpoints\\s+to\\s+(approval|approving|decline|declining)\\b"), "a lean")
    );

    private ResearchSummary() {
    }

    /**
     * The verdict rules this summary breaks, named so a log line records the rule
     * and never the text. Empty means the summary organises without concluding.
     */
    public static List<String> verdicts(String summary) {
        String text = summary == null ? "" : summary;
        List<String> broken = new ArrayList<>();
        for (Rule rule : VERDICTS) {
            if (rule.pattern.matcher(text).find() && !broken.contains(rule.what)) {
                broken.add(rule.what);
            }
        }
        return broken;
    }

    /**
     * The summary as the reviewer may read it: unchanged when it holds to the
     * rule, replaced outright when it does not. Replacing rather than trimming
     * the offending line is deliberate — a summary built toward a conclusion
     * still leans once the conclusion is cut.
     */
    public static String screen(String summary) {
        if (summary == null || summary.isBlank()) {
            return BLOCKED;
        }
        return verdicts(summary).isEmpty() ? summary : BLOCKED;
    }

    private record Rule(Pattern pattern, String what) {
    }
}
