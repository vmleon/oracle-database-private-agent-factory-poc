package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(ChatController.class)
class ChatControllerTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    ChatService chatService;

    @Test
    void chatReturns202WithTurnId() throws Exception {
        when(chatService.startTurn(eq("sess_1"), eq("hi"))).thenReturn("turn-9");

        mvc.perform(post("/v1/chat")
                        .header("X-Session-Token", "sess_1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message\":\"hi\"}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.turnId").value("turn-9"));
    }

    @Test
    void chatWithBadTokenIs401() throws Exception {
        when(chatService.startTurn(eq(null), eq("hi")))
                .thenThrow(new ResponseStatusException(org.springframework.http.HttpStatus.UNAUTHORIZED));

        mvc.perform(post("/v1/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"message\":\"hi\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void streamStartsAnSseResponse() throws Exception {
        when(chatService.openStream(eq("sess_1"))).thenReturn(new SseEmitter());

        mvc.perform(get("/v1/chat/stream").param("token", "sess_1"))
                .andExpect(request().asyncStarted());
    }

    @Test
    void historyReturnsMessages() throws Exception {
        when(chatService.history(eq("sess_1")))
                .thenReturn(List.of(new ChatMessageView("AGENT", "hello", null)));

        mvc.perform(get("/v1/chat/history").header("X-Session-Token", "sess_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].sender").value("AGENT"))
                .andExpect(jsonPath("$[0].body").value("hello"));
    }
}
