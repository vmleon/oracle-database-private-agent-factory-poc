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
                   la.term_months  AS termMonths,
                   la.status       AS applicationStatus,
                   la.purpose      AS purpose,
                   (SELECT COUNT(*)
                      FROM BANK_CORE.chat_message m
                     WHERE m.customer_id = c.customer_id) AS messageCount,
                   (SELECT t.state
                      FROM BANK_CORE.hitl_task t
                     WHERE t.application_id = la.application_id
                     ORDER BY t.task_id DESC
                     FETCH FIRST 1 ROW ONLY) AS reviewState
              FROM BANK_CORE.customer c
              LEFT JOIN BANK_CORE.loan_application la
                     ON la.customer_id = c.customer_id
                    AND la.status IN ('DRAFT','SUBMITTED','IN_REVIEW')
              LEFT JOIN BANK_CORE.product_catalog pc ON pc.product_id = la.product_id
             ORDER BY c.customer_id, la.application_id
            """, nativeQuery = true)
    List<CustomerOption> findCustomerOptions();
}
