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
    // Greedy `.*` (single-line) so a marker whose body contains `]` — e.g.
    // `[[DECISION tier=APPROVE reasons=["DTI_TOO_HIGH"]]]` — is matched up to its
    // final `]]`, not truncated at the first inner `]`.
    private static final Pattern LEADING_MARKERS = Pattern.compile("^(?:\\s*\\[\\[.*\\]\\]\\s*)+");
    // Reasoning ("thinking") models emit a <think>…</think> monologue before the
    // real answer. Drop everything up to and including the LAST </think> so the
    // chain-of-thought never reaches the customer. Anchored at start, DOTALL,
    // greedy — a no-op when the model doesn't think.
    private static final Pattern THINKING = Pattern.compile("(?s)^.*</think>\\s*");
    private static final List<String> REPLY_FIELDS = List.of("message", "content", "reply", "output", "text");

    private Envelope() {
    }

    /**
     * Clean an agent's raw reply into the customer-facing text: drop any
     * &lt;think&gt;…&lt;/think&gt; reasoning, then remove the leading [[MARKER ...]]
     * block(s) the agent emits before the customer sentence.
     */
    public static String stripMarkers(String text) {
        if (text == null) {
            return "";
        }
        String withoutThinking = THINKING.matcher(text).replaceFirst("");
        return LEADING_MARKERS.matcher(withoutThinking).replaceFirst("").strip();
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
        JsonNode data = root.has("data") ? root.get("data") : root;
        if (data.isTextual()) {
            return stripMarkers(data.asText());
        }
        for (String field : REPLY_FIELDS) {
            if (data.hasNonNull(field) && data.get(field).isTextual()) {
                return stripMarkers(data.get(field).asText());
            }
        }
        throw new IllegalStateException(
                "PAF reply shape not recognized; expected a string or one of "
                        + REPLY_FIELDS + " but got: " + root);
    }
}
