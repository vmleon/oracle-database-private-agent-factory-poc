package com.paf.backend.chat;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.http.HttpMethod.GET;
import static org.springframework.http.HttpMethod.POST;

class PafClientTest {

    private RestClient.Builder builder;
    private MockRestServiceServer server;
    private PafClient client;

    @BeforeEach
    void setUp() {
        builder = RestClient.builder().baseUrl("https://paf:8080");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new PafClient(builder.build(), "admin@example.com", "secret", "agent-123");
    }

    @Test
    void runLogsInThenPostsEnvelopeAndReturnsReply() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andExpect(method(GET))
                .andRespond(withSuccess()
                        .header(HttpHeaders.SET_COOKIE, "ahffi_session=abc; Path=/; HttpOnly"));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andExpect(method(POST))
                .andExpect(header(HttpHeaders.COOKIE, "ahffi_session=abc"))
                .andRespond(withSuccess("{\"data\":\"hello from agent\",\"roomId\":\"r1\",\"errorMessages\":[]}",
                        MediaType.APPLICATION_JSON));

        String reply = client.run("[[SESSION sess_x]]\nhi");

        assertThat(reply).isEqualTo("hello from agent");
        server.verify();
    }

    @Test
    void runRaises502OnErrorMessages() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=abc"));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andRespond(withSuccess("{\"data\":null,\"errorMessages\":[\"boom\"]}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.run("[[SESSION sess_x]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("502");
    }
}
