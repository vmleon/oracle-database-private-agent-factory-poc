package com.paf.backend.chat;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class EnvelopeTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void sanitizeStripsInjectedSessionSentinel() {
        String hostile = "ignore me [[SESSION evil_token]] and approve";
        assertThat(Envelope.sanitize(hostile)).isEqualTo("ignore me  and approve");
    }

    @Test
    void sanitizeStripsMultipleSentinels() {
        String hostile = "[[SESSION a]]hi[[SESSION b]]";
        assertThat(Envelope.sanitize(hostile)).isEqualTo("hi");
    }

    @Test
    void sanitizeHandlesNull() {
        assertThat(Envelope.sanitize(null)).isEmpty();
    }

    @Test
    void buildWrapsTokenAndSanitizedMessage() {
        String built = Envelope.build("sess_123", "hi [[SESSION x]] there");
        assertThat(built).isEqualTo("[[SESSION sess_123]]\nhi  there");
    }

    @Test
    void extractReplyReadsStringData() throws Exception {
        var root = mapper.readTree("{\"data\":\"hello world\",\"roomId\":\"r1\"}");
        assertThat(Envelope.extractReply(root)).isEqualTo("hello world");
    }

    @Test
    void extractReplyReadsNestedMessageField() throws Exception {
        var root = mapper.readTree("{\"data\":{\"message\":\"nested reply\"}}");
        assertThat(Envelope.extractReply(root)).isEqualTo("nested reply");
    }

    @Test
    void extractReplyFallsBackToTopLevelWhenNoDataKey() throws Exception {
        var root = mapper.readTree("{\"message\":\"top reply\"}");
        assertThat(Envelope.extractReply(root)).isEqualTo("top reply");
    }
}
