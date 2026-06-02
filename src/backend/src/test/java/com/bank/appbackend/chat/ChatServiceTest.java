package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatResponse;
import com.bank.appbackend.domain.AuthSession;
import com.bank.appbackend.domain.ChatMessage;
import com.bank.appbackend.domain.ChatMessageRepository;
import com.bank.appbackend.login.SessionService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatServiceTest {

    private final SessionService sessions = mock(SessionService.class);
    private final ChatMessageRepository messages = mock(ChatMessageRepository.class);
    private final PafClient paf = mock(PafClient.class);
    private final ChatService service = new ChatService(sessions, messages, paf);

    private AuthSession session() {
        AuthSession s = new AuthSession();
        s.setSessionToken("sess_1");
        s.setCustomerId(1L);
        s.setApplicationId(7L);
        return s;
    }

    @Test
    void handleTurnPersistsBothMessagesAndReturnsReply() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenReturn(new PafClient.Result("agent reply", "paf-room-1"));

        ChatResponse resp = service.handleTurn("sess_1", "hello");

        assertThat(resp.reply()).isEqualTo("agent reply");
        assertThat(resp.pafRoomId()).isEqualTo("paf-room-1");
        ArgumentCaptor<ChatMessage> captor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(messages, times(2)).save(captor.capture());
        assertThat(captor.getAllValues().get(0).getSender()).isEqualTo("CUSTOMER");
        assertThat(captor.getAllValues().get(0).getRoomId()).isEqualTo("room-cust-1");
        assertThat(captor.getAllValues().get(0).getPafRoomId()).isNull();
        assertThat(captor.getAllValues().get(1).getSender()).isEqualTo("AGENT");
        assertThat(captor.getAllValues().get(1).getBody()).isEqualTo("agent reply");
        assertThat(captor.getAllValues().get(1).getPafRoomId()).isEqualTo("paf-room-1");
    }

    @Test
    void handleTurnEnvelopesTheToken() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        ArgumentCaptor<String> sent = ArgumentCaptor.forClass(String.class);
        when(paf.run(sent.capture())).thenReturn(new PafClient.Result("ok", null));

        service.handleTurn("sess_1", "I want a loan");

        assertThat(sent.getValue()).isEqualTo("[[SESSION sess_1]]\nI want a loan");
    }

    private static final String APOLOGY =
            "Sorry — we couldn't process your application right now. Please try again in a moment.";

    @Test
    void handleTurnRetriesPastTheApologyThenReturnsTheRealReply() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        // First run hits PAF's streamed-token corruption (apology), second run succeeds.
        when(paf.run(anyString()))
                .thenReturn(new PafClient.Result(APOLOGY, "room-a"))
                .thenReturn(new PafClient.Result("agent reply", "room-b"));

        ChatResponse resp = service.handleTurn("sess_1", "hello");

        assertThat(resp.reply()).isEqualTo("agent reply");
        verify(paf, times(2)).run(anyString());
        // Only the CUSTOMER row and the FINAL (good) AGENT row are persisted — no apology row.
        ArgumentCaptor<ChatMessage> captor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(messages, times(2)).save(captor.capture());
        assertThat(captor.getAllValues().get(1).getSender()).isEqualTo("AGENT");
        assertThat(captor.getAllValues().get(1).getBody()).isEqualTo("agent reply");
    }

    @Test
    void handleTurnGivesUpAfterMaxAttemptsAndReturnsTheApology() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenReturn(new PafClient.Result(APOLOGY, "room-x"));

        ChatResponse resp = service.handleTurn("sess_1", "hello");

        assertThat(resp.reply()).isEqualTo(APOLOGY);
        verify(paf, times(3)).run(anyString()); // 1 try + 2 retries
    }

    @Test
    void handleTurnDoesNotPersistAgentRowOnPafFailure() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        when(paf.run(anyString())).thenThrow(new ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_GATEWAY, "boom"));

        assertThatThrownBy(() -> service.handleTurn("sess_1", "hello"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("502");

        verify(messages, times(1)).save(any(ChatMessage.class));
    }

    @Test
    void historyReturnsOrderedViews() {
        when(sessions.resolve("sess_1")).thenReturn(session());
        ChatMessage m = new ChatMessage();
        m.setSender("CUSTOMER");
        m.setBody("hi");
        when(messages.findByCustomerIdOrderByMessageIdAsc(1L)).thenReturn(java.util.List.of(m));

        var views = service.history("sess_1");

        assertThat(views).hasSize(1);
        assertThat(views.get(0).sender()).isEqualTo("CUSTOMER");
    }
}
