package com.paf.backend.domain;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

public interface LoanApplicationRepository extends JpaRepository<LoanApplication, Long> {

    @Query(value = """
            SELECT * FROM APP.loan_application
             WHERE customer_id = :customerId
               AND status IN ('DRAFT','SUBMITTED','IN_REVIEW')
             ORDER BY application_id DESC
             FETCH FIRST 1 ROW ONLY
            """, nativeQuery = true)
    Optional<LoanApplication> findOpenByCustomer(@Param("customerId") Long customerId);
}
