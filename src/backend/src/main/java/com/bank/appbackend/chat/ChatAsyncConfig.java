package com.bank.appbackend.chat;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * Executor for chat turns. PAF/vLLM is the bottleneck (~4 min per turn) and turns are
 * one-at-a-time per session, so a small pool is sufficient for the PoC. A turn that can't
 * be queued is rejected and surfaces as an SSE error on that turn.
 */
@Configuration
public class ChatAsyncConfig {

    @Bean(name = "chatExecutor")
    public Executor chatExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(50);
        executor.setThreadNamePrefix("chat-turn-");
        executor.initialize();
        return executor;
    }
}
