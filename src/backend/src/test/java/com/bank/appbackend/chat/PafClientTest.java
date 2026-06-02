package com.bank.appbackend.chat;

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
import org.springframework.http.HttpStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
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
        client = new PafClient(builder.build(), "admin@example.com", "secret");
    }

    private void expectAgentsList(String agentId) {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agents"))
                .andExpect(method(GET))
                .andRespond(withSuccess(
                        "{\"data\":{\"items\":[{\"name\":\"CHAT_WORKFLOW\",\"agentId\":\"" + agentId + "\"}]}}",
                        MediaType.APPLICATION_JSON));
    }

    @Test
    void runLogsInThenPostsEnvelopeAndReturnsReply() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andExpect(method(GET))
                .andRespond(withSuccess()
                        .header(HttpHeaders.SET_COOKIE, "ahffi_session=abc; Path=/; HttpOnly"));
        expectAgentsList("agent-123");
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andExpect(method(POST))
                .andExpect(header(HttpHeaders.COOKIE, "ahffi_session=abc"))
                .andRespond(withSuccess("{\"data\":\"hello from agent\",\"roomId\":\"r1\",\"errorMessages\":[]}",
                        MediaType.APPLICATION_JSON));

        PafClient.Result result = client.run("[[SESSION sess_x]]\nhi");

        assertThat(result.reply()).isEqualTo("hello from agent");
        assertThat(result.pafRoomId()).isEqualTo("r1");
        server.verify();
    }

    @Test
    void runRaises502OnErrorMessages() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=abc"));
        expectAgentsList("agent-123");
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andRespond(withSuccess("{\"data\":null,\"errorMessages\":[\"boom\"]}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.run("[[SESSION sess_x]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("502");
    }

    @Test
    void runDiscoversAgentIdByName() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=abc"));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agents"))
                .andExpect(method(GET))
                .andRespond(withSuccess(
                        "{\"data\":{\"items\":[{\"name\":\"CHAT_WORKFLOW\",\"agentId\":\"found-9\"}]}}",
                        MediaType.APPLICATION_JSON));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/found-9"))
                .andExpect(method(POST))
                .andRespond(withSuccess("{\"data\":\"discovered reply\"}", MediaType.APPLICATION_JSON));

        assertThat(client.run("[[SESSION s]]\nhi").reply()).isEqualTo("discovered reply");
        server.verify();
    }

    @Test
    void runRelogsInAndRetriesOn401() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=stale"));
        expectAgentsList("agent-123");
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=fresh"));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andExpect(header(HttpHeaders.COOKIE, "ahffi_session=fresh"))
                .andRespond(withSuccess("{\"data\":\"after relogin\"}", MediaType.APPLICATION_JSON));

        assertThat(client.run("[[SESSION s]]\nhi").reply()).isEqualTo("after relogin");
        server.verify();
    }

    @Test
    void runRelogsInWhenExpiredSessionReturnsHtmlInsteadOfJson() {
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=stale"));
        expectAgentsList("agent-123");
        // Expired cookie: PAF 303s the run, and the followed chain lands on the /agentFactory/
        // HTML dashboard (a 200, NOT a 401 and NOT the login page). Any non-JSON body = expiry.
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andRespond(withSuccess(
                        "<!doctype html><html><body>Oracle Agent Factory</body></html>", MediaType.TEXT_HTML));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/loginValidation"))
                .andRespond(withSuccess().header(HttpHeaders.SET_COOKIE, "ahffi_session=fresh"));
        server.expect(requestTo("https://paf:8080/agentFactory/v1/agentBuilder/run/agent-123"))
                .andExpect(header(HttpHeaders.COOKIE, "ahffi_session=fresh"))
                .andRespond(withSuccess("{\"data\":\"recovered\"}", MediaType.APPLICATION_JSON));

        assertThat(client.run("[[SESSION s]]\nhi").reply()).isEqualTo("recovered");
        server.verify();
    }
}
