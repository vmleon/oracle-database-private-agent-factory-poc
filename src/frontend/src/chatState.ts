import type { AgentEvent, HistoryMessage, TurnErrorEvent } from "./api";

export interface Message {
  id: string;
  sender: "CUSTOMER" | "AGENT" | "SYSTEM";
  body: string;
  pending: boolean;
  failed: boolean;
  turnId?: string;
}

export interface ChatState {
  messages: Message[];
  sending: boolean;
  seq: number; // monotonic id source for message keys
}

export const initialChatState: ChatState = {
  messages: [],
  sending: false,
  seq: 0,
};

export type ChatAction =
  | { type: "send"; text: string; turnId: string }
  | { type: "agent"; event: AgentEvent }
  | { type: "turnError"; event: TurnErrorEvent }
  | { type: "history"; messages: HistoryMessage[] };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send": {
      const userMsg: Message = {
        id: `m${state.seq}`,
        sender: "CUSTOMER",
        body: action.text,
        pending: false,
        failed: false,
      };
      const placeholder: Message = {
        id: `m${state.seq + 1}`,
        sender: "AGENT",
        body: "",
        pending: true,
        failed: false,
        turnId: action.turnId,
      };
      return {
        messages: [...state.messages, userMsg, placeholder],
        sending: true,
        seq: state.seq + 2,
      };
    }
    case "agent": {
      const idx = state.messages.findIndex(
        (m) => m.pending && m.turnId === action.event.turnId,
      );
      if (idx === -1) return state;
      const messages = state.messages.slice();
      messages[idx] = {
        ...messages[idx],
        body: action.event.reply,
        pending: false,
      };
      return { ...state, messages, sending: false };
    }
    case "turnError": {
      const idx = state.messages.findIndex(
        (m) => m.pending && m.turnId === action.event.turnId,
      );
      if (idx === -1) return state;
      const messages = state.messages.slice();
      messages[idx] = {
        ...messages[idx],
        body: "We couldn't get a response. Please try again.",
        pending: false,
        failed: true,
      };
      return { ...state, messages, sending: false };
    }
    case "history": {
      // Replace the persisted history, but keep any still-pending turn appended so a
      // reconnect mid-turn doesn't drop the in-flight placeholder.
      // If history already contains an AGENT reply, the pending turn resolved — drop it.
      const historyHasAgentReply = action.messages.some(
        (h) => h.sender === "AGENT",
      );
      const pending = historyHasAgentReply
        ? []
        : state.messages.filter((m) => m.pending);
      let seq = 0;
      const replayed: Message[] = action.messages.map((h) => ({
        id: `m${seq++}`,
        sender: h.sender,
        body: h.body,
        pending: false,
        failed: false,
      }));
      const pendingReindexed = pending.map((m) => ({ ...m, id: `m${seq++}` }));
      return {
        messages: [...replayed, ...pendingReindexed],
        sending: pending.length > 0,
        seq,
      };
    }
  }
}
