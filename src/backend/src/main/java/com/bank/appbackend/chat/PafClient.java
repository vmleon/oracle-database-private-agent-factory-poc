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
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.springframework.http.HttpStatus.BAD_GATEWAY;

@Component
public class PafClient {

    private static final Logger log = LoggerFactory.getLogger(PafClient.class);
    private static final String RUN_PATH_PREFIX = "/agentFactory/v1/integrations/agents/";
    private static final String RUN_PATH_SUFFIX = "/run";

    private final RestClient http;
    private final String apiKey;
    private final String agentId;
    private final ObjectMapper mapper = new ObjectMapper();

    public PafClient(RestClient pafRestClient,
                     @Value("${paf.api-key}") String apiKey,
                     @Value("${paf.agent-id}") String agentId) {
        this.http = pafRestClient;
        this.apiKey = apiKey;
        this.agentId = agentId;
    }

    /** Agent reply text plus PAF's own roomId (its conversation thread id); roomId may be null. */
    public record Result(String reply, String pafRoomId) {
    }

    /** Run CHAT_WORKFLOW with an already-enveloped message; returns the reply text and PAF roomId. */
    public Result run(String envelopedMessage) {
        String body = postRun(envelopedMessage);
        JsonNode root = readTree(body);
        JsonNode errs = root.path("errorMessages");
        if (errs.isArray() && !errs.isEmpty()) {
            log.warn("PAF returned errorMessages (agentId={}): {}", agentId, errs);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF returned errors: " + errs);
        }
        String reply;
        try {
            reply = Envelope.extractReply(root);
        } catch (IllegalStateException e) {
            log.warn("PAF reply shape not recognized (agentId={}): {}", agentId, body, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF reply shape not recognized", e);
        }
        return new Result(reply, root.path("roomId").asText(null));
    }

    private String postRun(String envelopedMessage) {
        try {
            return http.post()
                    .uri(RUN_PATH_PREFIX + agentId + RUN_PATH_SUFFIX)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("message", envelopedMessage))
                    .retrieve()
                    .body(String.class);
        } catch (RestClientResponseException e) {
            throw new ResponseStatusException(BAD_GATEWAY, describeFailure(e), e);
        } catch (RestClientException e) {
            log.warn("PAF run failed (agentId={})", agentId, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF run failed", e);
        }
    }

    /**
     * PAF answers a rejected integration call with {"error":{"code","message"}} and a real
     * status code, so each failure maps to an operator-actionable sentence rather than a
     * raw body. An unrecognized code still surfaces as a 502.
     */
    private String describeFailure(RestClientResponseException e) {
        String responseBody = e.getResponseBodyAsString();
        String code = "";
        try {
            code = mapper.readTree(responseBody).path("error").path("code").asText("");
        } catch (Exception ignored) {
            // Not the typed envelope; fall through to the generic message.
        }
        String message = switch (code) {
            case "INTEGRATION_KEY_EXPIRED" ->
                    "PAF integration key has expired; mint a new one with `manage.py paf api-key`";
            case "INTEGRATION_KEY_INVALID", "INTEGRATION_KEY_INACTIVE" ->
                    "PAF rejected the integration key; check PAF_API_KEY";
            case "INTEGRATION_KEY_NOT_AUTHORIZED_FOR_TARGET" ->
                    "PAF integration key is not authorized for agent " + agentId;
            case "INTEGRATION_AGENT_NOT_PUBLISHED" ->
                    "CHAT_WORKFLOW is not published; publish it in Agent Builder";
            default -> "PAF run returned HTTP " + e.getStatusCode().value();
        };
        log.warn("{} (agentId={}, body={})", message, agentId, responseBody);
        return message;
    }

    private JsonNode readTree(String body) {
        try {
            return mapper.readTree(body);
        } catch (Exception e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF response not JSON", e);
        }
    }
}
