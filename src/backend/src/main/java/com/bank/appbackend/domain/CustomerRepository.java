package com.bank.appbackend.domain;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface CustomerRepository extends JpaRepository<Customer, Long> {

    @Query(value = """
            SELECT c.customer_id   AS customerId,
                   c.full_name     AS name,
                   la.application_id AS applicationId,
                   pc.product_type AS productType,
                   la.amount_requested AS amountRequested,
                   la.term_months  AS termMonths
              FROM APP.customer c
              LEFT JOIN APP.loan_application la
                     ON la.customer_id = c.customer_id
                    AND la.status IN ('DRAFT','SUBMITTED','IN_REVIEW')
              LEFT JOIN APP.product_catalog pc ON pc.product_id = la.product_id
             ORDER BY c.customer_id, la.application_id
            """, nativeQuery = true)
    List<CustomerOption> findCustomerOptions();
}
