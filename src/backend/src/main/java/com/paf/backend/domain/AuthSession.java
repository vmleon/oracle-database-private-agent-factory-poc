package com.paf.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "AUTH_SESSION")
@Getter
@Setter
@NoArgsConstructor
public class AuthSession {

    @Id
    @Column(name = "SESSION_TOKEN")
    private String sessionToken;

    @Column(name = "CUSTOMER_ID")
    private Long customerId;

    @Column(name = "APPLICATION_ID")
    private Long applicationId;

    @Column(name = "SCENARIO_LABEL")
    private String scenarioLabel;

    @Column(name = "CREATED_AT", insertable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "EXPIRES_AT")
    private Instant expiresAt;
}
