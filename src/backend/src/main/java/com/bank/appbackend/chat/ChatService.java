package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.ChatMessage;
import com.bank.appbackend.domain.ChatMessageRepository;
import com.bank.appbackend.domain.HitlRepository;
import com.bank.appbackend.login.SessionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executor;

@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    // The fixed fail-secure apology the flow returns when get_context can't resolve the session.
    // Belt-and-suspenders: CHAT_WORKFLOW now loads get_context through a deterministic MCP node
    // (token wired, never transcribed), so streamed-token corruption can't happen on the read
    // path — this retry only still matters while a flow build predates that node. On a genuinely
    // invalid/expired token, retrying changes nothing (it stays the apology); it's not a failure.
    private static final String PAF_APOLOGY =
            "Sorry — we couldn't process your application right now. Please try again in a moment.";
    private static final int MAX_PAF_ATTEMPTS = 3; // 1 try + 2 retries

    private final SessionService sessions;
    private final ChatMessageRepository messages;
    private final PafClient paf;
    private final ChatEventPublisher events;
    private final HitlRepository tasks;
    private final Executor chatExecutor;

    public ChatService(SessionService sessions, ChatMessageRepository messages, PafClient paf,
                       ChatEventPublisher events, HitlRepository tasks,
                       @Qualifier("chatExecutor") Executor chatExecutor) {
        this.sessions = sessions;
        this.messages = messages;
        this.paf = paf;
        this.events = events;
        this.tasks = tasks;
        this.chatExecutor = chatExecutor;
    }

    /** Open (or replace) the customer's SSE channel. Fails 401 if the token is bad. */
    public SseEmitter openStream(String token) {
        sessions.resolve(token);
        return events.register(token);
    }

    /** Persist the customer message, kick off the PAF turn in the background, return its id. */
    public String startTurn(String token, String message) {
        AuthSession session = sessions.resolve(token);
        String roomId = roomId(session);
        // Sanitize before the thread sees it, not on the way out to PAF. The thread is
        // replayed — by the history endpoint today and by the outcome message to come —
        // so storing the raw text would keep an injection alive for whatever reads it
        // next. `Envelope.build` sanitizes again downstream and is idempotent, which
        // keeps it the one guaranteed choke point rather than a second opinion.
        String clean = Envelope.sanitize(message);
        if (!clean.equals(message)) {
            // The payload is exactly what should not be written down, so this records
            // that a message was cleaned and nothing about what it held.
            log.warn("customer message on room {} carried an envelope delimiter and was cleaned",
                    roomId);
        }
        save(session, roomId, "CUSTOMER", clean, null);
        String turnId = UUID.randomUUID().toString();
        chatExecutor.execute(() -> runTurn(token, clean, session, roomId, turnId));
        return turnId;
    }

    /** Background worker: call PAF (with apology-retry), persist the reply, push it over SSE. */
    void runTurn(String token, String message, AuthSession session, String roomId, String turnId) {
        try {
            String enveloped = Envelope.build(token, message);
            PafClient.Result result = paf.run(enveloped);
            // Belt-and-suspenders retry (see PAF_APOLOGY): inert once the deployed flow loads
            // get_context via the deterministic MCP node; harmless to keep during the transition.
            for (int attempt = 2; attempt <= MAX_PAF_ATTEMPTS && PAF_APOLOGY.equals(result.reply()); attempt++) {
                result = paf.run(enveloped);
            }
            // The disclosure policy is a rule here, not a request in a prompt: every
            // reply passes through this line on its way to both the thread and the
            // customer's screen, so a reply that breaks it reaches neither.
            // A decision is only ever shown with a task row behind it. The flow states the
            // same property in its final gate, but PAF runs the nodes after an agent only on
            // the turns where the agent answers and calls a tool in one step (issues/15), so
            // the guard on the delivery path lives here, where every reply passes.
            String reply = result.reply();
            if (result.announcesDecision() && tasks.countByCustomerId(session.getCustomerId()) == 0) {
                log.warn("turn {} announced a decision with no hitl_task behind it", turnId);
                reply = PAF_APOLOGY;
            }
            String shown = Disclosure.screen(message, reply);
            if (!shown.equals(reply)) {
                // The rule names only, never the text that broke them — a log line
                // is the last place the protected value should end up.
                log.warn("turn {} blocked by the disclosure policy: {}", turnId,
                        Disclosure.violations(reply, Disclosure.asksForAValue(message)));
            }
            save(session, roomId, "AGENT", shown, result.pafRoomId());
            events.pushAgent(token, turnId, shown, result.pafRoomId());
        } catch (RuntimeException e) {
            log.warn("chat turn {} failed", turnId, e);
            events.pushError(token, turnId, "We couldn't get a response. Please try again.");
        }
    }

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
