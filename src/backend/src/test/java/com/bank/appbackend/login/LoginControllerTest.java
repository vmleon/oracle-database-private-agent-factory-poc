package com.bank.appbackend.login;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(LoginController.class)
class LoginControllerTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    LoginService loginService;

    @Test
    void logoutReturns204AndInvalidatesSession() throws Exception {
        mvc.perform(post("/v1/logout").header("X-Session-Token", "sess_1"))
                .andExpect(status().isNoContent());

        verify(loginService).logout("sess_1");
    }

    @Test
    void logoutWithoutTokenStillReturns204() throws Exception {
        mvc.perform(post("/v1/logout"))
                .andExpect(status().isNoContent());

        verify(loginService).logout(null);
    }
}
