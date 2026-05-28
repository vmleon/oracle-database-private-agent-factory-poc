package com.paf.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

@Entity
@Table(name = "LOAN_APPLICATION")
@Getter
@NoArgsConstructor
public class LoanApplication {

    @Id
    @Column(name = "APPLICATION_ID")
    private Long applicationId;

    @Column(name = "CUSTOMER_ID")
    private Long customerId;

    @Column(name = "PRODUCT_ID")
    private Long productId;

    @Column(name = "AMOUNT_REQUESTED")
    private BigDecimal amountRequested;

    @Column(name = "TERM_MONTHS")
    private Integer termMonths;

    @Column(name = "PURPOSE")
    private String purpose;

    @Column(name = "STATUS")
    private String status;
}
