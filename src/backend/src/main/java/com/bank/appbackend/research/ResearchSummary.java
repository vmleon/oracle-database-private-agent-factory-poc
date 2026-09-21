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

    /**
     * The words a verdict names. A summary that suggests gathering more evidence
     * names none of them, which is what separates it from one that concludes.
     */
    private static final String OUTCOME =
            "(?:approv\\w*|declin\\w*|reject\\w*|den(?:y|ies|ied|ial))";

    /** Same-sentence proximity: newlines and periods are excluded so a subject on
     *  one line cannot bind to a verb on the next, or across a sentence boundary. */
    private static final String NEAR = "[^.\\n]{0,40}";

    /** Proximity that stops at a gerund, so "recommend requesting a payslip before
     *  approval" reads as recommending the payslip rather than the approval. */
    private static final String NEAR_NO_ACTION = "(?:(?!\\b\\w+ing\\b)[^.\\n]){0,40}";

    /** Proximity that stops at a negation, so "does not point to approval" is not
     *  read as pointing to it. A denial of a lean is not a lean. */
    private static final String NEAR_NO_NEGATION =
            "(?:(?!\\b(?:not|never|no|nor|cannot|n't)\\b)[^.\\n]){0,40}";

    private static final List<Rule> VERDICTS = List.of(
            // "I would recommend approving", "We recommend declining",
            // "My recommendation is to decline".
            new Rule(Pattern.compile(
                    "(?i)\\b(?:i|we|my|our)\\b" + NEAR
                            + "\\b(?:recommend\\w*|suggest\\w*|advis\\w*)\\b" + NEAR_NO_ACTION
                            + "\\b" + OUTCOME), "a recommendation"),
            new Rule(Pattern.compile(
                    "(?i)\\b(?:should|ought\\s+to|must)\\s+be\\s+" + OUTCOME), "a verdict"),
            new Rule(Pattern.compile(
                    "(?i)\\byou\\s+should\\s+" + OUTCOME), "a verdict"),
            // A summary that leans has concluded, whatever it leans toward.
            new Rule(Pattern.compile("(?i)\\bleans?\\s+towards?\\b"), "a lean"),
            // A balance sheet is a document, not a conclusion.
            new Rule(Pattern.compile("(?i)\\bon\\s+balance\\b(?!\\s+sheet)"), "a lean"),
            // "The comparable cases favour approval", "the data supports decline".
            new Rule(Pattern.compile(
                    "(?i)\\b(?:evidence|data|record|cases?|facts?|analysis|profile|history)\\b"
                            + NEAR_NO_NEGATION + "\\b(?:supports?|favou?rs?|points?\\s+to|argues?\\s+for)\\b"
                            + NEAR_NO_NEGATION + "\\b" + OUTCOME), "a lean"),
            // A labelled conclusion line: "Recommendation: DECLINE", "Verdict - approve".
            new Rule(Pattern.compile(
                    "(?im)^\\s*(?:recommendation|verdict|conclusion|decision|outcome)"
                            + "\\s*[:\\-—]\\s*\\S"), "a verdict"),
            // A line that is nothing but the verdict.
            new Rule(Pattern.compile(
                    "(?im)^\\s*" + OUTCOME + "\\b\\s*[.!]?\\s*$"), "a verdict"),
            // "Decline this application", "approve the loan".
            new Rule(Pattern.compile(
                    "(?i)\\b" + OUTCOME + "\\s+th(?:is|e)\\s+"
                            + "(?:application|case|loan|request)\\b"), "a verdict"),
            new Rule(Pattern.compile("(?i)\\bwarrants?\\s+" + OUTCOME), "a verdict"),
            new Rule(Pattern.compile(
                    "(?i)\\bstrong\\s+case\\s+for\\s+" + OUTCOME), "a verdict")
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
