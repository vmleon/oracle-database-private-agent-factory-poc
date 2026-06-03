import { describe, expect, it } from "vitest";
import { chatReducer, initialChatState, type ChatState } from "./chatState";

function withPendingTurn(): { state: ChatState; turnId: string } {
  const start = chatReducer(initialChatState, {
    type: "send",
    text: "hello",
    turnId: "t1",
  });
  return { state: start, turnId: "t1" };
}

describe("chatReducer", () => {
  it("send adds a user bubble and a pending agent placeholder", () => {
    const { state } = withPendingTurn();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      sender: "CUSTOMER",
      body: "hello",
    });
    expect(state.messages[1]).toMatchObject({
      sender: "AGENT",
      pending: true,
      turnId: "t1",
    });
    expect(state.sending).toBe(true);
  });

  it("agent event replaces the matching pending placeholder with the reply", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "agent",
      event: { turnId: "t1", reply: "Looks strong", pafRoomId: "r1" },
    });
    expect(next.messages).toHaveLength(2);
    expect(next.messages[1]).toMatchObject({
      sender: "AGENT",
      body: "Looks strong",
      pending: false,
    });
    expect(next.sending).toBe(false);
  });

  it("turn error marks the pending placeholder as failed and re-enables sending", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "turnError",
      event: { turnId: "t1", message: "boom" },
    });
    expect(next.messages[1]).toMatchObject({
      sender: "AGENT",
      failed: true,
      pending: false,
    });
    expect(next.sending).toBe(false);
  });

  it("ignores an agent event whose turnId does not match a pending turn", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "agent",
      event: { turnId: "other", reply: "nope", pafRoomId: null },
    });
    expect(next).toEqual(state);
  });

  it("history replaces messages (used on load and SSE reconnect)", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "history",
      messages: [
        { sender: "CUSTOMER", body: "old q", createdAt: null },
        { sender: "AGENT", body: "old a", createdAt: null },
      ],
    });
    expect(next.messages).toHaveLength(2);
    expect(next.messages[0]).toMatchObject({
      sender: "CUSTOMER",
      body: "old q",
      pending: false,
    });
    // a still-pending turn is preserved after history reconciliation
    const pendingPreserved = chatReducer(
      chatReducer(initialChatState, { type: "send", text: "q2", turnId: "t2" }),
      {
        type: "history",
        messages: [{ sender: "CUSTOMER", body: "old q", createdAt: null }],
      },
    );
    expect(pendingPreserved.messages.some((m) => m.pending)).toBe(true);
  });
});
