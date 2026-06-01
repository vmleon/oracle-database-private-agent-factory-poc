package com.bank.appbackend.login;

import com.bank.appbackend.api.Dtos.CustomerSummary;
import com.bank.appbackend.api.Dtos.LoginResponse;
import com.bank.appbackend.domain.CustomerOption;
import com.bank.appbackend.domain.CustomerRepository;
import com.bank.appbackend.domain.LoanApplication;
import com.bank.appbackend.domain.LoanApplicationRepository;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class LoginServiceTest {

    private final LoanApplicationRepository appRepo = mock(LoanApplicationRepository.class);
    private final SessionService sessionService = mock(SessionService.class);
    private final CustomerRepository customers = mock(CustomerRepository.class);
    private final LoginService service = new LoginService(appRepo, sessionService, customers);

    @Test
    void loginMintsTokenForOpenApplication() {
        when(appRepo.findOpenByCustomer(1L)).thenReturn(Optional.of(stubApp(7L)));
        when(sessionService.mint(1L, 7L)).thenReturn("sess_abc");

        LoginResponse resp = service.login(1L);

        assertThat(resp.sessionToken()).isEqualTo("sess_abc");
        assertThat(resp.applicationId()).isEqualTo(7L);
        assertThat(resp.roomId()).isEqualTo("room-cust-1");
    }

    @Test
    void loginMintsTokenForCustomerWithNoApplication() {
        when(appRepo.findOpenByCustomer(21L)).thenReturn(Optional.empty());
        when(sessionService.mint(21L, null)).thenReturn("sess_xyz");

        LoginResponse resp = service.login(21L);

        assertThat(resp.sessionToken()).isEqualTo("sess_xyz");
        assertThat(resp.applicationId()).isNull();
        assertThat(resp.roomId()).isEqualTo("room-cust-21");
    }

    @Test
    void listCustomersMarksWhetherAnApplicationIsOpen() {
        when(customers.findCustomerOptions()).thenReturn(List.of(
                option(1L, "Alice", 7L), option(21L, "Liam", null)));

        List<CustomerSummary> result = service.listCustomers();

        assertThat(result).hasSize(2);
        assertThat(result.get(0).hasOpenApplication()).isTrue();
        assertThat(result.get(0).applicationId()).isEqualTo(7L);
        assertThat(result.get(1).name()).isEqualTo("Liam");
        assertThat(result.get(1).hasOpenApplication()).isFalse();
        assertThat(result.get(1).applicationId()).isNull();
    }

    private CustomerOption option(Long custId, String name, Long appId) {
        return new CustomerOption() {
            public Long getCustomerId() { return custId; }
            public String getName() { return name; }
            public Long getApplicationId() { return appId; }
            public String getProductType() { return appId == null ? null : "PERSONAL_LOAN"; }
            public java.math.BigDecimal getAmountRequested() { return appId == null ? null : new java.math.BigDecimal("10000"); }
            public Integer getTermMonths() { return appId == null ? null : 24; }
        };
    }

    // LoanApplication has no public setters (read-only entity); build a stub via an anonymous subclass.
    private LoanApplication stubApp(long id) {
        return new LoanApplication() {
            @Override
            public Long getApplicationId() {
                return id;
            }
        };
    }
}
