package com.bank.appbackend.research;

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
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.springframework.http.HttpStatus.BAD_GATEWAY;

/**
 * Runs RESEARCH_WORKFLOW. Separate from {@link com.bank.appbackend.chat.PafClient}
 * because it is bound to a different agent id and a different integration key —
 * which is what makes the routing separation real: a key authorised for the chat
 * agent cannot run the research agent, so the customer path cannot reach it.
 *
 * <p>It shares the {@code pafRestClient} bean, so PAF's certificate is verified
 * on this hop exactly as it is on the chat hop.
 *
 * <p>The response contract differs too: research returns prose, with no markers
 * to strip and no decision to detect.
 */
@Component
public class ResearchPafClient {

    private static final Logger log = LoggerFactory.getLogger(ResearchPafClient.class);
    private static final String RUN_PATH_PREFIX = "/agentFactory/v1/integrations/agents/";
    private static final String RUN_PATH_SUFFIX = "/run";

    private final RestClient http;
    private final String apiKey;
    private final String agentId;
    private final ObjectMapper mapper = new ObjectMapper();

    public ResearchPafClient(RestClient pafRestClient,
                             @Value("${paf.research.api-key:}") String apiKey,
                             @Value("${paf.research.agent-id:}") String agentId) {
        this.http = pafRestClient;
        this.apiKey = apiKey;
        this.agentId = agentId;
    }

    /** The agent's summary text. Throws 502 when PAF cannot be reached or answers with errors. */
    public String run(String envelopedMessage) {
        if (apiKey.isBlank() || agentId.isBlank()) {
            throw new ResponseStatusException(BAD_GATEWAY,
                    "RESEARCH_WORKFLOW is not configured; run `manage.py paf api-key`");
        }
        String body;
        try {
            body = http.post()
                    .uri(RUN_PATH_PREFIX + agentId + RUN_PATH_SUFFIX)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("message", envelopedMessage))
                    .retrieve()
                    .body(String.class);
        } catch (RestClientException e) {
            log.warn("PAF research run failed (agentId={})", agentId, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF research run failed", e);
        }
        JsonNode root;
        try {
            root = mapper.readTree(body);
        } catch (Exception e) {
            throw new ResponseStatusException(BAD_GATEWAY, "PAF response not JSON", e);
        }
        JsonNode errs = root.path("errorMessages");
        if (errs.isArray() && !errs.isEmpty()) {
            log.warn("PAF returned errorMessages (agentId={}): {}", agentId, errs);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF returned errors: " + errs);
        }
        try {
            return com.bank.appbackend.chat.Envelope.extractRawReply(root);
        } catch (IllegalStateException e) {
            log.warn("PAF research reply shape not recognized (agentId={}): {}", agentId, body, e);
            throw new ResponseStatusException(BAD_GATEWAY, "PAF reply shape not recognized", e);
        }
    }
}
