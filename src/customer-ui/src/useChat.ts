import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getHistory, logout as apiLogout, openStream, sendChat } from "./api";
import { chatReducer, initialChatState } from "./chatState";

export interface Session {
  token: string;
  customerId: number;
  roomId: string;
}

export function useChat(session: Session, onLoggedOut: () => void) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadHistory = () => {
      getHistory(session.token)
        .then((msgs) => {
          if (!cancelled) dispatch({ type: "history", messages: msgs });
        })
        .catch(() => {
          /* history is best-effort; SSE still delivers live replies */
        });
    };

    const es = openStream(session.token, {
      onOpen: () => {
        setConnected(true);
        loadHistory(); // reconcile on first open AND on every reconnect
      },
      onAgent: (e) => dispatch({ type: "agent", event: e }),
      onTurnError: (e) => dispatch({ type: "turnError", event: e }),
    });
    esRef.current = es;

    return () => {
      cancelled = true;
      es.close();
      esRef.current = null;
    };
  }, [session.token]);

  const doLogout = useCallback(async () => {
    esRef.current?.close();
    esRef.current = null;
    await apiLogout(session.token);
    sessionStorage.removeItem("session");
    onLoggedOut();
  }, [session.token, onLoggedOut]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || state.sending) return;
      try {
        const { turnId } = await sendChat(session.token, trimmed);
        dispatch({ type: "send", text: trimmed, turnId });
      } catch {
        // 401 (expired/revoked) or network — log the user out.
        doLogout();
      }
    },
    [session.token, state.sending, doLogout],
  );

  return {
    messages: state.messages,
    sending: state.sending,
    connected,
    send,
    logout: doLogout,
  };
}
