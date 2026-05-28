package com.paf.backend.chat;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;
import java.util.regex.Pattern;

/** Pure helpers for the PAF in-band session envelope and reply parsing. */
public final class Envelope {

    private static final Pattern SENTINEL = Pattern.compile("\\[\\[SESSION[^\\]]*\\]\\]");
    private static final List<String> REPLY_FIELDS = List.of("message", "content", "reply", "output", "text");

    private Envelope() {
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
     * Extract the agent's reply text from a PAF run response tree. Tries data-as-string,
     * then common nested fields, then the top level, then the data node serialized.
     */
    public static String extractReply(JsonNode root) {
        JsonNode data = root.has("data") ? root.get("data") : root;
        if (data.isTextual()) {
            return data.asText();
        }
        for (String field : REPLY_FIELDS) {
            if (data.hasNonNull(field) && data.get(field).isTextual()) {
                return data.get(field).asText();
            }
        }
        return data.toString();
    }
}
