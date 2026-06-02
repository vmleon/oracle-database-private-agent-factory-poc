package com.bank.appbackend.login;

import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.AuthSessionRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HexFormat;

@Service
public class SessionService {

    private final AuthSessionRepository repo;
    private final int ttlHours;
    private final SecureRandom random = new SecureRandom();

    public SessionService(AuthSessionRepository repo, @Value("${session.ttl-hours}") int ttlHours) {
        this.repo = repo;
        this.ttlHours = ttlHours;
    }

    /** Mint an opaque session token bound to (customerId, applicationId). */
    public String mint(Long customerId, Long applicationId) {
        byte[] bytes = new byte[16];
        random.nextBytes(bytes);
        String token = "sess_" + HexFormat.of().formatHex(bytes);

        AuthSession session = new AuthSession();
        session.setSessionToken(token);
        session.setCustomerId(customerId);
        session.setApplicationId(applicationId);
        session.setScenarioLabel("backend-login");
        session.setExpiresAt(Instant.now().plus(ttlHours, ChronoUnit.HOURS));
        repo.save(session);
        return token;
    }

    /** Resolve a token to its session, or 401 if missing / unknown / expired. Fail-secure. */
    public AuthSession resolve(String token) {
        if (token == null || token.isBlank()) {
            throw unauthorized();
        }
        AuthSession session = repo.findById(token).orElseThrow(this::unauthorized);
        if (session.getExpiresAt() != null && session.getExpiresAt().isBefore(Instant.now())) {
            throw unauthorized();
        }
        return session;
    }

    /** Revoke a session so its token can no longer be used. Idempotent. */
    public void invalidate(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        repo.findById(token).ifPresent(repo::delete);
    }

    private ResponseStatusException unauthorized() {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid_or_expired_session");
    }
}
