package com.paf.backend.login;

import com.paf.backend.api.Dtos.LoginResponse;
import com.paf.backend.domain.LoanApplication;
import com.paf.backend.domain.LoanApplicationRepository;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class LoginServiceTest {

    private final LoanApplicationRepository appRepo = mock(LoanApplicationRepository.class);
    private final SessionService sessionService = mock(SessionService.class);
    private final LoginService service = new LoginService(appRepo, sessionService, mock(com.paf.backend.domain.CustomerRepository.class));

    @Test
    void loginMintsTokenForOpenApplication() {
        when(appRepo.findOpenByCustomer(1L)).thenReturn(Optional.of(stubApp(7L)));
        when(sessionService.mint(1L, 7L)).thenReturn("sess_abc");

        LoginResponse resp = service.login(1L);

        assertThat(resp.sessionToken()).isEqualTo("sess_abc");
        assertThat(resp.applicationId()).isEqualTo(7L);
        assertThat(resp.roomId()).isEqualTo("room-app-7");
    }

    @Test
    void loginRaises404WhenNoOpenApplication() {
        when(appRepo.findOpenByCustomer(99L)).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.login(99L))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404");
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
