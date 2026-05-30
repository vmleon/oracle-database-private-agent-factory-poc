package com.paf.backend.login;

import com.paf.backend.api.Dtos.CustomerSummary;
import com.paf.backend.api.Dtos.LoginResponse;
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

    /** All customers for the mock-login dropdown, flagged by whether they have an open application. */
    public List<CustomerSummary> listCustomers() {
        return customers.findCustomerOptions().stream()
                .map(o -> new CustomerSummary(o.getCustomerId(), o.getName(), o.getApplicationId(),
                        o.getProductType(), o.getAmountRequested(), o.getTermMonths(),
                        o.getApplicationId() != null))
                .toList();
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
