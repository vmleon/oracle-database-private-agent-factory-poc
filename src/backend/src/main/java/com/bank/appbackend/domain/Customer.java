package com.bank.appbackend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "CUSTOMER", schema = "BANK_CORE")
@Getter
@NoArgsConstructor
public class Customer {

    @Id
    @Column(name = "CUSTOMER_ID")
    private Long customerId;

    @Column(name = "FULL_NAME")
    private String fullName;
}
