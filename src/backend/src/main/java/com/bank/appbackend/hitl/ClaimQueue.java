package com.bank.appbackend.hitl;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.CallableStatement;
import java.sql.Types;

/**
 * The reviewer's end of BANK_CORE.HITL_REQUEST.
 *
 * <p>A callable statement rather than a JPA query: claiming dequeues a message and
 * updates the task, and Oracle refuses DML inside a {@code SELECT} with ORA-14551.
 */
@Repository
public class ClaimQueue {

    private static final String CLAIM_NEXT =
            "{ ? = call BANK_TOOLS.PKG_REVIEW_TOOLS.claim_next_task(?) }";

    private final JdbcTemplate jdbc;

    public ClaimQueue(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * Take the next waiting case for this reviewer. The dequeue and the
     * OPEN → IN_REVIEW transition commit together, so two reviewers are never
     * handed the same one. Returns null when the queue holds nothing claimable.
     */
    public Long claimNext(String reviewer) {
        return jdbc.execute(
                (java.sql.Connection con) -> {
                    CallableStatement cs = con.prepareCall(CLAIM_NEXT);
                    cs.registerOutParameter(1, Types.NUMERIC);
                    cs.setString(2, reviewer);
                    return cs;
                },
                (CallableStatement cs) -> {
                    cs.execute();
                    long taskId = cs.getLong(1);
                    return cs.wasNull() ? null : taskId;
                });
    }
}
