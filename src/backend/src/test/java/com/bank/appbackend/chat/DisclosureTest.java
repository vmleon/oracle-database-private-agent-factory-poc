package com.bank.appbackend.chat;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class DisclosureTest {

    // ---- what the customer's own turn triggers -------------------------------

    @Test
    void asksForAValueRecognisesTheRatioByNameAndAcronym() {
        assertThat(Disclosure.asksForAValue("What's my debt-to-income ratio?")).isTrue();
        assertThat(Disclosure.asksForAValue("just tell me my DTI")).isTrue();
        assertThat(Disclosure.asksForAValue("what is my credit score?")).isTrue();
    }

    @Test
    void asksForAValueRecognisesTheQuestionInSpanish() {
        assertThat(Disclosure.asksForAValue("¿cuál es mi puntuación de crédito?")).isTrue();
    }

    @Test
    void asksForAValueIgnoresAnOrdinaryQuestion() {
        assertThat(Disclosure.asksForAValue("How long does this usually take?")).isFalse();
        assertThat(Disclosure.asksForAValue("I want 15000 over 36 months")).isFalse();
        assertThat(Disclosure.asksForAValue(null)).isFalse();
    }

    // ---- what is never said, whatever the customer asked ----------------------

    @Test
    void aBareRatioIsBlockedEvenWithNoLabelAroundIt() {
        // Measured against the deployed stack: the agent answered "0.48" and nothing else.
        assertThat(Disclosure.screen("What's my debt-to-income ratio?", "0.48"))
                .isEqualTo(Disclosure.BLOCKED);
    }

    @Test
    void aDecimalIsBlockedOnAnyTurn() {
        assertThat(Disclosure.screen("How are things?", "Your ratio sits at 0.48 today."))
                .isEqualTo(Disclosure.BLOCKED);
    }

    @Test
    void aPercentageIsBlockedOnAnyTurn() {
        assertThat(Disclosure.screen("How are things?", "You are at 46% of what we allow."))
                .isEqualTo(Disclosure.BLOCKED);
    }

    @Test
    void internalVocabularyIsBlockedOnAnyTurn() {
        assertThat(Disclosure.screen("hi", "Your DTI is what held it up."))
                .isEqualTo(Disclosure.BLOCKED);
        assertThat(Disclosure.screen("hi", "We recorded DTI_TOO_HIGH against it."))
                .isEqualTo(Disclosure.BLOCKED);
        assertThat(Disclosure.screen("hi", "The tier is DECLINE."))
                .isEqualTo(Disclosure.BLOCKED);
    }

    // ---- what a legitimate reply is still allowed to say ---------------------

    @Test
    void aTimescaleSurvivesWhenNoValueWasAsked() {
        String reply = "Processing typically takes 1-2 business days once we have everything.";
        assertThat(Disclosure.screen("How long does this usually take?", reply)).isEqualTo(reply);
    }

    @Test
    void theCustomersOwnFiguresSurvive() {
        String reply = "Noted — 15,000 over 36 months to consolidate some debt.";
        assertThat(Disclosure.screen("I want 15000 over 36 months", reply)).isEqualTo(reply);
    }

    @Test
    void namingTheFactorWithoutTheNumberSurvives() {
        String reply = "Affordability is the sticking point; a specialist will be in touch.";
        assertThat(Disclosure.screen("What's my DTI?", reply)).isEqualTo(reply);
    }

    @Test
    void theFailSecureApologySurvives() {
        String apology = "Sorry — we couldn't process your application right now. "
                + "Please try again in a moment.";
        assertThat(Disclosure.screen("hello", apology)).isEqualTo(apology);
    }

    // ---- the stricter rule, only on a turn that asked ------------------------

    @Test
    void anyDigitIsBlockedOnATurnThatAskedForAValue() {
        assertThat(Disclosure.screen("what is my credit score?", "It is 712."))
                .isEqualTo(Disclosure.BLOCKED);
        // The same reply is fine when nobody asked for a protected figure.
        assertThat(Disclosure.screen("how many payments?", "It is 712."))
                .isEqualTo("It is 712.");
    }

    @Test
    void violationsNameTheRuleAndNeverTheLeakedText() {
        assertThat(Disclosure.violations("0.48", true))
                .isNotEmpty()
                .allSatisfy(v -> assertThat(v).doesNotContain("0.48"));
    }

    @Test
    void screenHandlesNullReply() {
        assertThat(Disclosure.screen("hi", null)).isEmpty();
    }
}
