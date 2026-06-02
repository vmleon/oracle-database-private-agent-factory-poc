package com.bank.appbackend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "CHAT_MESSAGE")
@Getter
@Setter
@NoArgsConstructor
public class ChatMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "MESSAGE_ID")
    private Long messageId;

    @Column(name = "ROOM_ID")
    private String roomId;

    @Column(name = "CUSTOMER_ID")
    private Long customerId;

    @Column(name = "APPLICATION_ID")
    private Long applicationId;

    @Column(name = "SENDER")
    private String sender;

    @Lob
    @Column(name = "BODY")
    private String body;

    @Column(name = "AGENT_RUN_ID")
    private String agentRunId;

    @Column(name = "PAF_ROOM_ID")
    private String pafRoomId;

    @Column(name = "CREATED_AT", insertable = false, updatable = false)
    private Instant createdAt;
}
