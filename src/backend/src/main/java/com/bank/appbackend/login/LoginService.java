package com.bank.appbackend.login;

import com.bank.appbackend.api.Dtos.CustomerSummary;
import com.bank.appbackend.api.Dtos.LoginResponse;
import com.bank.appbackend.chat.ChatEventPublisher;
import com.bank.appbackend.domain.CustomerRepository;
import com.bank.appbackend.domain.LoanApplication;
import com.bank.appbackend.domain.LoanApplicationRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class LoginService {

    private final LoanApplicationRepository applications;
    private final SessionService sessionService;
    private final CustomerRepository customers;
    private final ChatEventPublisher events;

    public LoginService(LoanApplicationRepository applications,
                        SessionService sessionService,
                        CustomerRepository customers,
                        ChatEventPublisher events) {
        this.applications = applications;
        this.sessionService = sessionService;
        this.customers = customers;
        this.events = events;
    }

    /** All customers for the mock-login dropdown, flagged by whether they have an open application. */
    public List<CustomerSummary> listCustomers() {
        return customers.findCustomerOptions().stream()
                .map(o -> new CustomerSummary(o.getCustomerId(), o.getName(), o.getApplicationId(),
                        o.getProductType(), o.getAmountRequested(), o.getTermMonths(),
                        o.getApplicationId() != null))
                .toList();
    }

    /** Mint a session bound to the customer. The open application (if any) is cached on the
     *  session; a customer with none enters intake. Room is keyed by customer so the thread is
     *  stable across the pre-application -> application transition. */
    public LoginResponse login(Long customerId) {
        Long applicationId = applications.findOpenByCustomer(customerId)
                .map(LoanApplication::getApplicationId)
                .orElse(null);
        String token = sessionService.mint(customerId, applicationId);
        String roomId = "room-cust-" + customerId;
        return new LoginResponse(token, customerId, applicationId, roomId);
    }

    /** Revoke the session and drop its SSE channel. Idempotent / best-effort. */
    public void logout(String token) {
        sessionService.invalidate(token);
        events.remove(token);
    }
}
