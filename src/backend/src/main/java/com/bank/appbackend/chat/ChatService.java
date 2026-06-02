package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.api.Dtos.ChatResponse;
import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.ChatMessage;
import com.bank.appbackend.domain.ChatMessageRepository;
import com.bank.appbackend.login.SessionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ChatService {

    // The fixed fail-secure apology the flow returns when get_context can't resolve the session
    // (in practice: PAF's streamed tool-call corrupted the token). Used to detect-and-retry.
    private static final String PAF_APOLOGY =
            "Sorry — we couldn't process your application right now. Please try again in a moment.";
    private static final int MAX_PAF_ATTEMPTS = 3; // 1 try + 2 retries

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

        save(session, roomId, "CUSTOMER", message, null);
        String enveloped = Envelope.build(token, message);
        PafClient.Result result = paf.run(enveloped); // throws 502 on PAF error -> no AGENT row
        // PAF streams agent tool-calls, and vLLM's streamed tool-call args occasionally drop or
        // duplicate a character in the session_token, so get_context fails and the flow returns
        // this fixed apology. The corruption is random per run, so just re-run the turn a couple
        // of times; with a valid token the apology otherwise means corruption, not a real failure.
        for (int attempt = 2; attempt <= MAX_PAF_ATTEMPTS && PAF_APOLOGY.equals(result.reply()); attempt++) {
            result = paf.run(enveloped);
        }
        save(session, roomId, "AGENT", result.reply(), result.pafRoomId());

        return new ChatResponse(result.reply(), result.pafRoomId());
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

    private void save(AuthSession session, String roomId, String sender, String body, String pafRoomId) {
        ChatMessage m = new ChatMessage();
        m.setRoomId(roomId);
        m.setCustomerId(session.getCustomerId());
        m.setApplicationId(session.getApplicationId());
        m.setSender(sender);
        m.setBody(body);
        m.setPafRoomId(pafRoomId);
        messages.save(m);
    }

    private String roomId(AuthSession session) {
        return "room-cust-" + session.getCustomerId();
    }
}
