package com.bank.appbackend.research;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class ResearchSummaryTest {

    private static final String ORGANISED = """
            The agent recommended REVIEW on credit history.

            SUPPORTS APPROVING
            - 4 comparable cases were approved in the same score band
            - 24 months of stable salary credits

            ARGUES AGAINST
            - 2 comparable cases were declined on affordability
            - 3 large round outflows in the last 30 days

            NOT ESTABLISHED
            - no prior decision for this customer
            - the score floor moved 3 weeks ago
            """;

    @Test
    void anOrganisedSummaryPassesThrough() {
        assertThat(ResearchSummary.screen(ORGANISED)).isEqualTo(ORGANISED);
        assertThat(ResearchSummary.verdicts(ORGANISED)).isEmpty();
    }

    @Test
    void tierNamesAndHeadingsAreNotVerdicts() {
        // The reviewer is bank staff: naming the tier and heading a section
        // "SUPPORTS APPROVING" is the job. Only a conclusion is barred.
        assertThat(ResearchSummary.verdicts("The agent recommended DECLINE.")).isEmpty();
        assertThat(ResearchSummary.verdicts("SUPPORTS APPROVING\n- stable income")).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "On balance, the evidence points to approval.",
            "I recommend approving this application.",
            "My recommendation is to decline.",
            "This should be approved.",
            "It ought to be declined given the outflows.",
            "The evidence leans toward approving.",
            "The case leans towards declining.",
            "The evidence supports approving this case.",
            "You should approve this application.",
            "I would recommend approving this application.",
            "We recommend declining.",
            "The comparable cases favor approval.",
            "The data supports decline.",
            "Recommendation: DECLINE",
            "Decline this application.",
            "This warrants approval.",
            "This is a strong case for approval.",
            "I would not recommend approving this application.",
            "This case supports approval.",
            "We recommend proceeding with the approval.",
            "I would suggest going ahead with the declination.",
    })
    void aVerdictIsRejected(String summary) {
        assertThat(ResearchSummary.verdicts(summary)).isNotEmpty();
        assertThat(ResearchSummary.screen(summary)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "Approve.",
            "Decline.",
    })
    void aBareVerdictOnItsOwnLineIsRejected(String summary) {
        assertThat(ResearchSummary.screen(summary)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "I suggest re-verifying the employer record.",
            "We should request a recent payslip.",
            "The exposure is reported on balance sheets.",
    })
    void aSuggestionThatNamesNoOutcomeIsAllowed(String summary) {
        assertThat(ResearchSummary.verdicts(summary)).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "We recommend requesting a payslip before approval.",
            "I suggest obtaining a payslip before approval.",
    })
    void anActionSuggestionNearAnOutcomeWordIsAllowed(String summary) {
        assertThat(ResearchSummary.verdicts(summary)).isEmpty();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "- the record does not point to approval on its own",
            "The data does not support approval.",
            "The comparable cases never favour approval outright.",
    })
    void aDeniedLeanIsAllowed(String summary) {
        assertThat(ResearchSummary.verdicts(summary)).isEmpty();
    }

    @Test
    void aVerdictBuriedInAnOtherwiseGoodSummaryIsStillRejected() {
        String withLean = ORGANISED + "\nON BALANCE\n- I recommend approving.\n";
        assertThat(ResearchSummary.screen(withLean)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @Test
    void theOrganisedSummaryStillPasses() {
        assertThat(ResearchSummary.screen(ORGANISED)).isEqualTo(ORGANISED);
    }

    @Test
    void anEmptySummaryIsBlocked() {
        // Nothing to show is not the same as nothing to say; the panel must
        // never render an empty research section as though it had run.
        assertThat(ResearchSummary.screen("")).isEqualTo(ResearchSummary.BLOCKED);
        assertThat(ResearchSummary.screen(null)).isEqualTo(ResearchSummary.BLOCKED);
    }

    @Test
    void theBlockedTextNamesNoOutcome() {
        assertThat(ResearchSummary.BLOCKED).doesNotContain("APPROVE", "DECLINE");
    }
}
