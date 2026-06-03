package com.bank.appbackend.hitl;

import com.bank.appbackend.api.Dtos.DecisionListItem;
import com.bank.appbackend.api.Dtos.DecisionRequest;
import com.bank.appbackend.api.Dtos.DecisionResponse;
import com.bank.appbackend.api.Dtos.DecisionView;
import com.bank.appbackend.api.Dtos.HitlQueueItem;
import com.bank.appbackend.api.Dtos.HitlTaskView;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/v1/hitl")
public class HitlController {

    private final HitlService service;

    public HitlController(HitlService service) {
        this.service = service;
    }

    @GetMapping("/tasks")
    public List<HitlQueueItem> tasks(@RequestParam(defaultValue = "OPEN") String state) {
        return service.listOpen();
    }

    @GetMapping("/tasks/{taskId}")
    public HitlTaskView task(@PathVariable Long taskId) {
        return service.getDetail(taskId);
    }

    @PostMapping("/tasks/{taskId}/decision")
    public DecisionResponse decide(@PathVariable Long taskId, @RequestBody DecisionRequest request) {
        return service.decide(taskId, request);
    }

    @GetMapping("/decisions")
    public List<DecisionListItem> decisions(@RequestParam(required = false) Long customerId,
                                            @RequestParam(required = false) Long applicationId) {
        return service.listDecisions(customerId, applicationId);
    }

    @GetMapping("/decisions/{decisionId}")
    public DecisionView decision(@PathVariable Long decisionId) {
        return service.getDecision(decisionId);
    }
}
