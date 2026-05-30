package com.paf.backend.chat;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;
import java.util.regex.Pattern;

/** Pure helpers for the PAF in-band session envelope and reply parsing. */
public final class Envelope {

    private static final Pattern SENTINEL = Pattern.compile("\\[\\[SESSION[^\\]]*\\]\\]");
    private static final Pattern LEADING_MARKERS = Pattern.compile("^(?:\\s*\\[\\[[^\\]]*\\]\\]\\s*)+");
    private static final List<String> REPLY_FIELDS = List.of("message", "content", "reply", "output", "text");

    private Envelope() {
    }

    /** Remove leading [[MARKER ...]] block(s) an agent emits before the customer-facing text. */
    public static String stripMarkers(String text) {
        if (text == null) {
            return "";
        }
        return LEADING_MARKERS.matcher(text).replaceFirst("").strip();
    }

    /** Strip any [[SESSION ...]] sentinel a customer might inject. MANDATORY before enveloping. */
    public static String sanitize(String message) {
        if (message == null) {
            return "";
        }
        return SENTINEL.matcher(message).replaceAll("");
    }

    /** Wrap the server-issued token + sanitized message in the envelope the flow's RegexExtractor splits. */
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
