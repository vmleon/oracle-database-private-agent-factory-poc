package com.bank.appbackend.chat;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * The disclosure policy, enforced between the model's sentence and the customer.
 *
 * <p>The policy itself — name the factor, never the number — is written into the
 * Recommendation worker's instructions, where it is a request rather than a rule.
 * This class is the rule: every reply passes through {@link #screen} on its way to
 * the thread and the SSE channel, so a reply that breaks the policy never reaches
 * either.
 *
 * <p>Two tiers, because a blanket ban on digits would also block
 * "takes 1-2 business days", which is a good answer. The always-banned set holds
 * what no reply in this product legitimately contains; the stricter set applies only
 * on a turn where the customer asked for a figure the policy protects.
 *
 * <p>Pure and free of Spring, so the rules are unit-testable on the host.
 */
public final class Disclosure {

    /**
     * Shown in place of a reply that breaks the policy. Names no figure, no code and
     * no factor — and stays accurate whichever rule was broken, since the customer is
     * never told which one it was.
     */
    public static final String BLOCKED =
            "I can't share those details, but a specialist can talk it through with you.";

    /** The customer is asking for a value the policy protects. */
    private static final Pattern VALUE_QUESTION = Pattern.compile(
            "(?i)\\b(dti|pti)\\b"
                    + "|(?i)\\b(debt|payment)[-\\s]to[-\\s]income\\b"
                    + "|(?i)\\bcredit\\s+(score|rating)\\b"
                    + "|(?i)\\bmy\\s+score\\b"
                    + "|(?i)\\bpuntuaci[oó]n|\\bpuntaje\\b"
                    + "|(?i)\\b(threshold|cut[-\\s]?off|floor|cap|ceiling)\\b"
                    + "|(?i)\\bumbral\\b");

    private static final List<Rule> ALWAYS = List.of(
            new Rule(Pattern.compile("(?i)\\b(dti|pti|kyc|aml)\\b"), "an internal acronym"),
            new Rule(Pattern.compile("(?i)\\b(debt|payment)[-\\s]to[-\\s]income\\b"), "a ratio name"),
            new Rule(Pattern.compile("\\b[A-Z]{3,}_[A-Z_]+\\b"), "a reason code"),
            new Rule(Pattern.compile("\\b(APPROVE|REVIEW|DECLINE)\\b"), "a tier name"),
            new Rule(Pattern.compile("%|(?i)\\bper\\s?cent\\b|(?i)\\bpor\\s?ciento\\b"), "a percentage"),
            // A decimal in this product is a ratio: amounts, terms and timescales are
            // whole numbers. `15,000` is a thousands separator and stays; `0,48` and
            // `0.48` are values and do not.
            new Rule(Pattern.compile("\\d\\.\\d|\\d,\\d{1,2}(?!\\d)"), "a ratio"),
            new Rule(Pattern.compile("sess_"), "a session token"),
            new Rule(Pattern.compile("\\[\\[|]]"), "an internal marker"),
            new Rule(Pattern.compile("(?i)</?think>"), "model reasoning")
    );

    /** Only on a turn where the customer asked for a protected figure. */
    private static final Rule NO_DIGITS = new Rule(Pattern.compile("\\d"), "a number");

    private Disclosure() {
    }

    /** True when the customer's own turn asks for a figure the policy protects. */
    public static boolean asksForAValue(String customerMessage) {
        return customerMessage != null && VALUE_QUESTION.matcher(customerMessage).find();
    }

    /**
     * The rules this reply breaks, named so a log line records the rule and never the
     * text that broke it. Empty means the reply is inside the policy.
     */
    public static List<String> violations(String reply, boolean valueWasAsked) {
        String text = reply == null ? "" : reply;
        List<String> broken = new ArrayList<>();
        for (Rule rule : ALWAYS) {
            if (rule.pattern.matcher(text).find()) {
                broken.add(rule.what);
            }
        }
        if (valueWasAsked && NO_DIGITS.pattern.matcher(text).find() && !broken.contains(NO_DIGITS.what)) {
            broken.add(NO_DIGITS.what);
        }
        return broken;
    }

    /**
     * The reply as the customer may read it: unchanged when it holds to the policy,
     * replaced outright when it does not. Replacing rather than redacting is
     * deliberate — a part-redacted sentence can still imply the figure it lost.
     */
    public static String screen(String customerMessage, String reply) {
        if (reply == null || reply.isBlank()) {
            return "";
        }
        return violations(reply, asksForAValue(customerMessage)).isEmpty() ? reply : BLOCKED;
    }

    private record Rule(Pattern pattern, String what) {
    }
}
