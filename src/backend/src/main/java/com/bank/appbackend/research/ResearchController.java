package com.bank.appbackend.research;

import com.bank.appbackend.api.Dtos.ResearchRequest;
import com.bank.appbackend.api.Dtos.ResearchView;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** The reviewer's research surface. Backoffice only — the customer path holds no key for it. */
@RestController
@RequestMapping("/v1/research")
public class ResearchController {

    private final ResearchService service;

    public ResearchController(ResearchService service) {
        this.service = service;
    }

    @PostMapping("/tasks/{taskId}/run")
    public ResearchView run(@PathVariable Long taskId, @RequestBody ResearchRequest request) {
        return service.run(taskId, request.reviewer());
    }

    /** The stored summary, so reopening a case does not re-run the agent. 204 when none. */
    @GetMapping("/tasks/{taskId}")
    public ResponseEntity<ResearchView> latest(@PathVariable Long taskId) {
        ResearchView view = service.latest(taskId);
        return view == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(view);
    }
}
