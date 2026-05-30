package com.paf.backend.domain;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    List<ChatMessage> findByApplicationIdOrderByMessageIdAsc(Long applicationId);
    List<ChatMessage> findByCustomerIdOrderByMessageIdAsc(Long customerId);
}
