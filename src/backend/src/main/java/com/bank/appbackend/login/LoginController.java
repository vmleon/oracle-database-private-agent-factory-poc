package com.bank.appbackend.login;

import com.bank.appbackend.api.Dtos.CustomerSummary;
import com.bank.appbackend.api.Dtos.LoginRequest;
import com.bank.appbackend.api.Dtos.LoginResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
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

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(
            @RequestHeader(value = "X-Session-Token", required = false) String token) {
        loginService.logout(token);
        return ResponseEntity.noContent().build();
    }
}
