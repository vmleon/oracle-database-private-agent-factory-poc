package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.api.Dtos.ChatRequest;
import com.bank.appbackend.api.Dtos.TurnAccepted;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

@RestController
@RequestMapping("/v1/chat")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    /** Start a turn; the reply arrives later on the SSE channel. */
    @PostMapping
    public ResponseEntity<TurnAccepted> chat(
            @RequestHeader(value = "X-Session-Token", required = false) String token,
            @RequestBody ChatRequest request) {
        String turnId = chatService.startTurn(token, request.message());
        return ResponseEntity.accepted().body(new TurnAccepted(turnId));
    }

    /**
     * Per-session SSE channel. The browser's native EventSource cannot send headers, so the
     * token comes as a query parameter (PoC tradeoff documented in the design spec).
     */
    @GetMapping("/stream")
    public SseEmitter stream(@RequestParam("token") String token) {
        return chatService.openStream(token);
    }

    @GetMapping("/history")
    public List<ChatMessageView> history(
            @RequestHeader(value = "X-Session-Token", required = false) String token) {
        return chatService.history(token);
    }
}
