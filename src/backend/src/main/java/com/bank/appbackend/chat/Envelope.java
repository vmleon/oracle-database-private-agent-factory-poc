package com.bank.appbackend.chat;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;
import java.util.regex.Pattern;

/** Pure helpers for the PAF in-band session envelope and reply parsing. */
public final class Envelope {

    private static final Pattern SENTINEL = Pattern.compile("\\[\\[SESSION[^\\]]*\\]\\]");
    // Every remaining square bracket. The envelope is in-band and the flow splits it
    // on the LAST `[[SESSION ` and `]]` it finds, so any bracket the customer types
    // competes with the server's own delimiter. Single characters, not pairs:
    // removing pairs alone would turn `][[]` into `]]`.
    private static final Pattern BRACKETS = Pattern.compile("[\\[\\]]");
    // One [[MARKER ...]] the agent emits alongside its sentence, matched wherever it
    // sits. The body may hold a JSON array — `[[DECISION tier=APPROVE
    // reasons=["DTI_TOO_HIGH"]]]` — so a single `]` or `[` is part of it and the
    // close is the `]]` not followed by another `]`. Lazy and barred from crossing a
    // second `[[`, so text between two markers is text rather than marker body.
    private static final Pattern MARKERS =
            Pattern.compile("\\[\\[(?:[^\\[]|\\[(?!\\[))*?\\]\\](?!\\])");
    // Reasoning ("thinking") models emit a <think>…</think> monologue before the real
    // answer, and the chain-of-thought never reaches the customer. A properly paired
    // block is removed where it sits, so an answer either side of it survives.
    // The marker the Recommendation worker emits once a task is filed. Case and inner
    // whitespace are tolerated the way `gate.DECISION_MARKER` tolerates them, so the
    // backend and the flow agree on what announces a decision.
    private static final Pattern DECISION = Pattern.compile("(?i)\\[\\[\\s*DECISION\\b");
    private static final Pattern THINK_BLOCK = Pattern.compile("(?s)<think>.*?</think>\\s*");
    // The same models also emit the monologue with no opening tag at all. With no
    // pair to bound it, everything up to the LAST </think> goes: dropping too much is
    // the safe direction when the alternative is leaking the reasoning.
    private static final Pattern THINK_TAIL = Pattern.compile("(?s)^.*</think>\\s*");
    private static final List<String> REPLY_FIELDS = List.of("message", "content", "reply", "output", "text");

    private Envelope() {
    }

    /**
     * Clean an agent's raw reply into the customer-facing text: drop any
     * &lt;think&gt;…&lt;/think&gt; reasoning, then remove every [[MARKER ...]] the
     * agent emits around its sentence.
     *
     * <p>Markers are removed one at a time rather than as a leading run, so a reply
     * whose first line carries two of them keeps the words between.
     */
    public static String stripMarkers(String text) {
        if (text == null) {
            return "";
        }
        String cleaned = THINK_BLOCK.matcher(text).replaceAll("");
        if (cleaned.contains("</think>")) {
            cleaned = THINK_TAIL.matcher(cleaned).replaceFirst("");
        }
        return MARKERS.matcher(cleaned).replaceAll("").strip();
    }

    /** True when the raw reply carries the {@code [[DECISION ...]]} marker. */
    public static boolean announcesDecision(String rawReply) {
        return rawReply != null && DECISION.matcher(rawReply).find();
    }

    /**
     * Remove anything bracket-shaped from a customer message. MANDATORY before enveloping.
     *
     * <p>Well-formed sentinels go first so the whole construct disappears rather than
     * leaving its words behind; whatever brackets remain are then dropped outright. The
     * result is that {@link #build} always yields exactly one {@code [[} and one
     * {@code ]]} — the server's own — so which match the flow's extractors return stops
     * being something this class has to know.
     */
    public static String sanitize(String message) {
        if (message == null) {
            return "";
        }
        String withoutSentinels = SENTINEL.matcher(message).replaceAll("");
        return BRACKETS.matcher(withoutSentinels).replaceAll("");
    }

    /**
     * Wrap the server-issued token + sanitized message in the envelope the flow's
     * RegexExtractor splits. The message is sanitized here rather than by the caller,
     * so there is no path that builds an envelope around unsanitized text.
     */
    public static String build(String token, String message) {
        return "[[SESSION " + token + "]]\n" + sanitize(message);
    }

    /**
     * Extract the agent's reply text from a PAF run response tree. Live PAF returns
     * {"message": "<text>", "roomId": "..."}; we also accept data-as-string and the
     * other common reply fields. Throws if none match, so an unexpected shape fails
     * loudly (caller maps it to 502) instead of leaking a raw JSON blob into the chat.
     */
    public static String extractReply(JsonNode root) {
        return stripMarkers(extractRawReply(root));
    }

    /** The agent's reply as PAF returned it, markers and all. */
    public static String extractRawReply(JsonNode root) {
        JsonNode data = root.has("data") ? root.get("data") : root;
        if (data.isTextual()) {
            return data.asText();
        }
        for (String field : REPLY_FIELDS) {
            if (data.hasNonNull(field) && data.get(field).isTextual()) {
                return data.get(field).asText();
            }
        }
        throw new IllegalStateException(
                "PAF reply shape not recognized; expected a string or one of "
                        + REPLY_FIELDS + " but got: " + root);
    }
}
