package com.paf.backend.chat;

import com.paf.backend.api.Dtos.ChatMessageView;
import com.paf.backend.api.Dtos.ChatResponse;
import com.paf.backend.domain.AuthSession;
import com.paf.backend.domain.ChatMessage;
import com.paf.backend.domain.ChatMessageRepository;
import com.paf.backend.login.SessionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ChatService {

    private final SessionService sessions;
    private final ChatMessageRepository messages;
    private final PafClient paf;

    public ChatService(SessionService sessions, ChatMessageRepository messages, PafClient paf) {
        this.sessions = sessions;
        this.messages = messages;
        this.paf = paf;
    }

    /** One chat turn: persist the customer message, call PAF, persist + return the reply. */
    public ChatResponse handleTurn(String token, String message) {
        AuthSession session = sessions.resolve(token);
        String roomId = roomId(session);

        save(session, roomId, "CUSTOMER", message);
        String reply = paf.run(Envelope.build(token, message)); // throws 502 on PAF error -> no AGENT row
        save(session, roomId, "AGENT", reply);

        return new ChatResponse(reply, null);
    }

    /**
     * Replay the persisted conversation for the token's application. readOnly transaction
     * keeps the persistence session open while the CLOB body is read during DTO mapping
     * (open-in-view is false).
     */
    @Transactional(readOnly = true)
    public List<ChatMessageView> history(String token) {
        AuthSession session = sessions.resolve(token);
        return messages.findByCustomerIdOrderByMessageIdAsc(session.getCustomerId()).stream()
                .map(m -> new ChatMessageView(m.getSender(), m.getBody(), m.getCreatedAt()))
                .toList();
    }

    private void save(AuthSession session, String roomId, String sender, String body) {
        ChatMessage m = new ChatMessage();
        m.setRoomId(roomId);
        m.setCustomerId(session.getCustomerId());
        m.setApplicationId(session.getApplicationId());
        m.setSender(sender);
        m.setBody(body);
        messages.save(m);
    }

    private String roomId(AuthSession session) {
        return "room-cust-" + session.getCustomerId();
    }
}
