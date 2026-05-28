package com.paf.backend.login;

import com.paf.backend.domain.AuthSession;
import com.paf.backend.domain.AuthSessionRepository;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SessionServiceTest {

    private final AuthSessionRepository repo = mock(AuthSessionRepository.class);
    private final SessionService service = new SessionService(repo, 8);

    @Test
    void resolveRejectsUnknownToken() {
        when(repo.findById("nope")).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.resolve("nope"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("401");
    }

    @Test
    void resolveRejectsNullToken() {
        assertThatThrownBy(() -> service.resolve(null))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("401");
    }

    @Test
    void resolveRejectsExpiredToken() {
        AuthSession expired = new AuthSession();
        expired.setSessionToken("old");
        expired.setExpiresAt(Instant.now().minusSeconds(60));
        when(repo.findById("old")).thenReturn(Optional.of(expired));
        assertThatThrownBy(() -> service.resolve("old"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("401");
    }

    @Test
    void resolveReturnsValidSession() {
        AuthSession ok = new AuthSession();
        ok.setSessionToken("good");
        ok.setCustomerId(1L);
        ok.setApplicationId(1L);
        ok.setExpiresAt(Instant.now().plusSeconds(3600));
        when(repo.findById("good")).thenReturn(Optional.of(ok));
        assertThat(service.resolve("good").getApplicationId()).isEqualTo(1L);
    }

    @Test
    void mintPersistsTokenAndReturnsIt() {
        when(repo.save(any(AuthSession.class))).thenAnswer(i -> i.getArgument(0));
        String token = service.mint(5L, 9L);
        assertThat(token).startsWith("sess_");
    }
}
