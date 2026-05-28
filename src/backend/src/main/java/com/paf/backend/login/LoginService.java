package com.paf.backend.login;

import com.paf.backend.api.Dtos.LoginResponse;
import com.paf.backend.domain.CustomerOption;
import com.paf.backend.domain.CustomerRepository;
import com.paf.backend.domain.LoanApplication;
import com.paf.backend.domain.LoanApplicationRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Service
public class LoginService {

    private final LoanApplicationRepository applications;
    private final SessionService sessionService;
    private final CustomerRepository customers;

    public LoginService(LoanApplicationRepository applications,
                        SessionService sessionService,
                        CustomerRepository customers) {
        this.applications = applications;
        this.sessionService = sessionService;
        this.customers = customers;
    }

    /** Customers with an open application, for the mock-login dropdown. */
    public List<CustomerOption> listCustomers() {
        return customers.findOpenApplicationOptions();
    }

    /** Resolve the customer's open application and mint a session token bound to it. */
    public LoginResponse login(Long customerId) {
        LoanApplication app = applications.findOpenByCustomer(customerId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "no open application for customer " + customerId));
        String token = sessionService.mint(customerId, app.getApplicationId());
        String roomId = "room-app-" + app.getApplicationId();
        return new LoginResponse(token, customerId, app.getApplicationId(), roomId);
    }
}
