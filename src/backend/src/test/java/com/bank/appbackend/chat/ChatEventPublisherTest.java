package com.bank.appbackend.chat;

import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

class ChatEventPublisherTest {

    private final ChatEventPublisher publisher = new ChatEventPublisher();

    @Test
    void registerMakesEmitterRetrievableByToken() {
        SseEmitter emitter = publisher.register("sess_a");
        assertThat(emitter).isNotNull();
        assertThat(publisher.hasEmitter("sess_a")).isTrue();
    }

    @Test
    void registerTwiceKeepsOneEmitterPerToken() {
        publisher.register("sess_a");
        publisher.register("sess_a");
        assertThat(publisher.emitterCount()).isEqualTo(1);
        assertThat(publisher.hasEmitter("sess_a")).isTrue();
    }

    @Test
    void removeDropsTheEmitter() {
        publisher.register("sess_a");
        publisher.remove("sess_a");
        assertThat(publisher.hasEmitter("sess_a")).isFalse();
    }

    @Test
    void pushToUnknownTokenIsSafeNoop() {
        assertThatCode(() -> publisher.pushAgent("nobody", "t1", "hi", null)).doesNotThrowAnyException();
        assertThatCode(() -> publisher.pushError("nobody", "t1", "boom")).doesNotThrowAnyException();
    }

    @Test
    void removeUnknownTokenIsSafeNoop() {
        assertThatCode(() -> publisher.remove("nobody")).doesNotThrowAnyException();
    }
}
