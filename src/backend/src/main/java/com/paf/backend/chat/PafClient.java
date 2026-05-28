package com.paf.backend.chat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

import static org.springframework.http.HttpStatus.BAD_GATEWAY;

@Component
public class PafClient {

    private static final String LOGIN_PATH = "/agentFactory/v1/loginValidation";
    private static final String AGENTS_PATH = "/agentFactory/v1/agents";
    private static final String RUN_PATH = "/agentFactory/v1/agentBuilder/run/";

    private final RestClient http;
    private final String adminUser;
    private final String adminPass;
    private final ObjectMapper mapper = new ObjectMapper();

    private volatile String cookie;
    private volatile String agentId;

    public PafClient(RestClient pafRestClient,
                     @Value("${paf.admin-user}") String adminUser,
                     @Value("${paf.admin-pass}") String adminPass,
                     @Value("${paf.agent-id:}") String configuredAgentId) {
        this.http = pafRestClient;
        this.adminUser = adminUser;
        this.adminPass = adminPass;
        this.agentId = (configuredAgentId == null || configuredAgentId.isBlank()) ? null : configuredAgentId;
    }

    /** Run CHAT_WORKFLOW with an already-enveloped message; returns the agent reply text. */
    public String run(String envelopedMessage) {
        ensureCookie();
        String id = ensureAgentId();
        String body;
        try {
            body = postRun(id, envelopedMessage);
        } catch (org.springframework.web.client.RestClientResponseException e) {
            if (e.getStatusCode().value() == 401) {
                // Cached cookie likely expired — drop it, re-login, and retry once.
                this.cookie = null;
                ensureCookie();
                try {
                    body = postRun(id, envelopedMessage);
                } catch (org.springframework.web.client.RestClientException retry) {
                    throw new ResponseStatusException(BAD_GATEWAY, "PAF run failed after re-login", retry);
                }
            } else {
                throw new ResponseStatusException(BAD_GATEWAY, "PAF run returned HTTP error", e);
            }
        } catch (org.springframework.web.client.RestClientException e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF run failed", e);
        }
        JsonNode root = readTree(body);
        JsonNode errs = root.path("errorMessages");
        if (errs.isArray() && !errs.isEmpty()) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF returned errors: " + errs);
        }
        return Envelope.extractReply(root);
    }

    private String postRun(String id, String envelopedMessage) {
        return http.post()
                .uri(RUN_PATH + id)
                .header(HttpHeaders.COOKIE, cookie)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("message", envelopedMessage))
                .retrieve()
                .body(String.class);
    }

    private void ensureCookie() {
        if (cookie != null) {
            return;
        }
        login();
    }

    private synchronized void login() {
        if (cookie != null) {
            return;
        }
        HttpHeaders headers = http.get()
                .uri(LOGIN_PATH)
                .headers(h -> h.setBasicAuth(adminUser, adminPass))
                .retrieve()
                .toBodilessEntity()
                .getHeaders();
        List<String> setCookies = headers.get(HttpHeaders.SET_COOKIE);
        if (setCookies == null || setCookies.isEmpty()) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF login returned no Set-Cookie");
        }
        this.cookie = setCookies.get(0).split(";", 2)[0];
    }

    private String ensureAgentId() {
        if (agentId != null) {
            return agentId;
        }
        return discoverAgentId();
    }

    private synchronized String discoverAgentId() {
        if (agentId != null) {
            return agentId;
        }
        String body = http.get()
                .uri(AGENTS_PATH)
                .header(HttpHeaders.COOKIE, cookie)
                .retrieve()
                .body(String.class);
        JsonNode root = readTree(body);
        JsonNode data = root.has("data") ? root.get("data") : root;
        JsonNode items = data.has("items") ? data.get("items") : data;
        if (items.isArray()) {
            for (JsonNode agent : items) {
                if ("CHAT_WORKFLOW".equals(agent.path("name").asText())) {
                    String id = agent.hasNonNull("agentId") ? agent.get("agentId").asText()
                            : agent.path("agent_id").asText(null);
                    if (id != null && !id.isBlank()) {
                        this.agentId = id;
                        return id;
                    }
                }
            }
        }
        throw new ResponseStatusException(BAD_GATEWAY,
                "CHAT_WORKFLOW not found in PAF agent list; set CHAT_WORKFLOW_AGENT_ID");
    }

    private JsonNode readTree(String body) {
        try {
            return mapper.readTree(body);
        } catch (Exception e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF response not JSON", e);
        }
    }
}
