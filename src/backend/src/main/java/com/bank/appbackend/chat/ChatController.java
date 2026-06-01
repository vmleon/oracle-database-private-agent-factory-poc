package com.bank.appbackend.chat;

import com.bank.appbackend.api.Dtos.ChatMessageView;
import com.bank.appbackend.api.Dtos.ChatRequest;
import com.bank.appbackend.api.Dtos.ChatResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/v1/chat")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping
    public ChatResponse chat(@RequestHeader(value = "X-Session-Token", required = false) String token,
                             @RequestBody ChatRequest request) {
        return chatService.handleTurn(token, request.message());
    }

    @GetMapping("/history")
    public List<ChatMessageView> history(
            @RequestHeader(value = "X-Session-Token", required = false) String token) {
        return chatService.history(token);
    }
}
