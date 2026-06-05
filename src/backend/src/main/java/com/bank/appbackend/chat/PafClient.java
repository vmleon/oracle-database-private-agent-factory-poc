package com.bank.appbackend.chat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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

    private static final Logger log = LoggerFactory.getLogger(PafClient.class);
    private static final String LOGIN_PATH = "/agentFactory/v1/loginValidation";
    private static final String AGENTS_PATH = "/agentFactory/v1/agents";
    private static final String RUN_PATH = "/agentFactory/v1/agentBuilder/run/";

    private final RestClient http;
    private final String adminUser;
    private final String adminPass;
    private final String baseUrl;
    private final ObjectMapper mapper = new ObjectMapper();

    private volatile String cookie;
    private volatile String agentId;

    public PafClient(RestClient pafRestClient,
                     @Value("${paf.admin-user}") String adminUser,
                     @Value("${paf.admin-pass}") String adminPass,
                     @Value("${paf.base-url}") String baseUrl) {
        this.http = pafRestClient;
        this.adminUser = adminUser;
        this.adminPass = adminPass;
        this.baseUrl = baseUrl;
    }

    /** Agent reply text plus PAF's own roomId (its conversation thread id); roomId may be null. */
    public record Result(String reply, String pafRoomId) {
    }

    /** Run CHAT_WORKFLOW with an already-enveloped message; returns the reply text and PAF roomId. */
    public Result run(String envelopedMessage) {
        ensureCookie();
        String id = ensureAgentId();
        String body = postRunWithSessionRetry(id, envelopedMessage);
        JsonNode root = readTree(body);
        JsonNode errs = root.path("errorMessages");
        if (errs.isArray() && !errs.isEmpty()) {
            log.warn("PAF returned errorMessages (agentId={}): {}", id, errs);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF returned errors: " + errs);
        }
        String reply;
        try {
            reply = Envelope.extractReply(root);
        } catch (IllegalStateException e) {
            log.warn("PAF reply shape not recognized (agentId={}): {}", id, body, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF reply shape not recognized", e);
        }
        return new Result(reply, root.path("roomId").asText(null));
    }

    /**
     * POST the run, transparently re-authenticating once if the cached cookie has expired.
     * PAF signals expiry two ways: a 401, or a 303 redirect to /agentFactory/login whose
     * (auto-followed) body is the HTML login page rather than JSON. Both are handled here so
     * a long-lived backend doesn't 502 every turn once its session ages out (~30 min).
     */
    private String postRunWithSessionRetry(String id, String envelopedMessage) {
        String body;
        try {
            body = postRun(id, envelopedMessage);
        } catch (org.springframework.web.client.RestClientResponseException e) {
            if (e.getStatusCode().value() != 401) {
                log.warn("PAF run returned HTTP {} (agentId={}): {}",
                        e.getStatusCode().value(), id, e.getResponseBodyAsString(), e);
                throw new ResponseStatusException(BAD_GATEWAY, "PAF run returned HTTP error", e);
            }
            body = null; // 401 -> session expired; fall through to re-login + retry
        } catch (org.springframework.web.client.RestClientException e) {
            log.warn("PAF run failed (agentId={})", id, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF run failed", e);
        }
        if (body == null || !looksLikeJson(body)) {
            // Cached cookie expired — drop it, re-login, and retry once.
            this.cookie = null;
            ensureCookie();
            try {
                return postRun(id, envelopedMessage);
            } catch (org.springframework.web.client.RestClientException retry) {
                log.warn("PAF run failed after re-login (agentId={})", id, retry);
                throw new ResponseStatusException(BAD_GATEWAY, "PAF run failed after re-login", retry);
            }
        }
        return body;
    }

    /**
     * A valid run response is a JSON object. When the session cookie has expired PAF instead
     * 303-redirects the run to its login/home pages and the followed body is HTML — so any
     * non-JSON body means "re-authenticate", regardless of which page the redirect landed on.
     */
    private static boolean looksLikeJson(String body) {
        return body != null && body.stripLeading().startsWith("{");
    }

    private String postRun(String id, String envelopedMessage) {
        return http.post()
                .uri(RUN_PATH + id)
                .header(HttpHeaders.COOKIE, cookie)
                // PAF 26.4 enforces a same-origin CSRF check on state-changing routes
                // (auth.py: CSRF_ORIGIN_REQUIRED). Programmatic callers must send an
                // Origin matching PAF's own host, else the run is 403'd.
                .header(HttpHeaders.ORIGIN, baseUrl)
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
                "CHAT_WORKFLOW not found in PAF agent list; build and publish it per paf/flows/CHAT_WORKFLOW.md");
    }

    private JsonNode readTree(String body) {
        try {
            return mapper.readTree(body);
        } catch (Exception e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF response not JSON", e);
        }
    }
}
