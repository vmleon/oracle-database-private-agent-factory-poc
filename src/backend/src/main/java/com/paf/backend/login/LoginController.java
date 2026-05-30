package com.paf.backend.login;

import com.paf.backend.api.Dtos.CustomerSummary;
import com.paf.backend.api.Dtos.LoginRequest;
import com.paf.backend.api.Dtos.LoginResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/v1")
public class LoginController {

    private final LoginService loginService;

    public LoginController(LoginService loginService) {
        this.loginService = loginService;
    }

    @GetMapping("/customers")
    public List<CustomerSummary> customers() {
        return loginService.listCustomers();
    }

    @PostMapping("/login")
    public LoginResponse login(@RequestBody LoginRequest request) {
        return loginService.login(request.customerId());
    }
}
