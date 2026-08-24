package com.bank.appbackend.chat;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.http.HttpMethod.POST;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.headerDoesNotExist;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class PafClientTest {

    private static final String RUN_URL =
            "https://paf:8080/agentFactory/v1/integrations/agents/agent-123/run";

    private MockRestServiceServer server;
    private PafClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("https://paf:8080");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new PafClient(builder.build(), "afk_prefix_secret", "agent-123");
    }

    @Test
    void runPostsEnvelopeWithBearerKeyAndReturnsReply() {
        server.expect(requestTo(RUN_URL))
                .andExpect(method(POST))
                .andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer afk_prefix_secret"))
                .andRespond(withSuccess(
                        "{\"roomId\":\"r1\",\"message\":\"hello from agent\"}",
                        MediaType.APPLICATION_JSON));

        PafClient.Result result = client.run("[[SESSION sess_x]]\nhi");

        assertThat(result.reply()).isEqualTo("hello from agent");
        assertThat(result.pafRoomId()).isEqualTo("r1");
        server.verify();
    }

    @Test
    void runSendsNoCookieAndNoOriginHeader() {
        server.expect(requestTo(RUN_URL))
                .andExpect(method(POST))
                .andExpect(headerDoesNotExist(HttpHeaders.COOKIE))
                .andExpect(headerDoesNotExist(HttpHeaders.ORIGIN))
                .andRespond(withSuccess("{\"roomId\":\"r1\",\"message\":\"ok\"}",
                        MediaType.APPLICATION_JSON));

        assertThat(client.run("[[SESSION s]]\nhi").reply()).isEqualTo("ok");
        server.verify();
    }

    @Test
    void runRaises502OnErrorMessages() {
        server.expect(requestTo(RUN_URL))
                .andRespond(withSuccess("{\"data\":null,\"errorMessages\":[\"boom\"]}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.run("[[SESSION s]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("502");
    }

    @Test
    void expiredKeyFailsWithAMintingHint() {
        server.expect(requestTo(RUN_URL))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"error\":{\"code\":\"INTEGRATION_KEY_EXPIRED\","
                                + "\"message\":\"Integration API key has expired.\"}}"));

        assertThatThrownBy(() -> client.run("[[SESSION s]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("paf api-key");
    }

    @Test
    void unpublishedWorkflowFailsWithAPublishHint() {
        server.expect(requestTo(RUN_URL))
                .andRespond(withStatus(HttpStatus.BAD_REQUEST)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"error\":{\"code\":\"INTEGRATION_AGENT_NOT_PUBLISHED\","
                                + "\"message\":\"The custom workflow must be published.\"}}"));

        assertThatThrownBy(() -> client.run("[[SESSION s]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("not published");
    }

    @Test
    void unknownErrorCodeStillFailsWith502() {
        server.expect(requestTo(RUN_URL))
                .andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"error\":{\"code\":\"SOMETHING_ELSE\",\"message\":\"nope\"}}"));

        assertThatThrownBy(() -> client.run("[[SESSION s]]\nhi"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("502");
    }
}
