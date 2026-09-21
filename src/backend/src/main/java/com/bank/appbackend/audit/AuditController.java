package com.bank.appbackend.audit;

import com.bank.appbackend.api.Dtos.ResearchAudit;
import com.bank.appbackend.api.Dtos.ToolCallAudit;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * Internal collector for the per-tool CHAT_WORKFLOW and RESEARCH_WORKFLOW audit trails.
 * The MCP tool wrappers POST here after each call; the backend (which owns APP) writes
 * the row. Reachable only inside the tier.
 */
@RestController
@RequestMapping("/v1/audit")
public class AuditController {

    private final AuditService service;
    private final ResearchAuditService researchService;

    public AuditController(AuditService service, ResearchAuditService researchService) {
        this.service = service;
        this.researchService = researchService;
    }

    @PostMapping("/tool-call")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void toolCall(@RequestBody ToolCallAudit req) {
        service.record(req);
    }

    @PostMapping("/research")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void research(@RequestBody ResearchAudit req) {
        researchService.record(req);
    }
}
