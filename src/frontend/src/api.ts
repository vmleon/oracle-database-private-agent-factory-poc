export interface Customer {
  customerId: number;
  name: string;
  applicationId: number | null;
  productType: string | null;
  amountRequested: number | null;
  termMonths: number | null;
  hasOpenApplication: boolean;
}

export interface LoginResponse {
  sessionToken: string;
  customerId: number;
  applicationId: number | null;
  roomId: string;
}

export interface HistoryMessage {
  sender: "CUSTOMER" | "AGENT" | "SYSTEM";
  body: string;
  createdAt: string | null;
}

export interface AgentEvent {
  turnId: string;
  reply: string;
  pafRoomId: string | null;
}

export interface TurnErrorEvent {
  turnId: string;
  message: string;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function listCustomers(): Promise<Customer[]> {
  return fetch("/v1/customers").then((r) => json<Customer[]>(r));
}

export function login(customerId: number): Promise<LoginResponse> {
  return fetch("/v1/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customerId }),
  }).then((r) => json<LoginResponse>(r));
}

export function getHistory(token: string): Promise<HistoryMessage[]> {
  return fetch("/v1/chat/history", {
    headers: { "X-Session-Token": token },
  }).then((r) => json<HistoryMessage[]>(r));
}

/** Returns the turnId; the reply arrives later on the SSE channel. */
export function sendChat(
  token: string,
  message: string,
): Promise<{ turnId: string }> {
  return fetch("/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-Token": token },
    body: JSON.stringify({ message }),
  }).then((r) => json<{ turnId: string }>(r));
}

/** Best-effort: resolves even if the call fails. */
export async function logout(token: string): Promise<void> {
  try {
    await fetch("/v1/logout", {
      method: "POST",
      headers: { "X-Session-Token": token },
    });
  } catch {
    // ignore — logout is best-effort; the UI logs out regardless
  }
}

export interface StreamHandlers {
  onAgent: (e: AgentEvent) => void;
  onTurnError: (e: TurnErrorEvent) => void;
  onOpen: () => void;
}

/** Open the per-session SSE channel. Native EventSource can't set headers, so the
 *  token rides as a query param (PoC tradeoff — see the design spec). */
export function openStream(
  token: string,
  handlers: StreamHandlers,
): EventSource {
  const es = new EventSource(
    `/v1/chat/stream?token=${encodeURIComponent(token)}`,
  );
  es.addEventListener("open", () => handlers.onOpen());
  es.addEventListener("agent", (ev) => {
    handlers.onAgent(JSON.parse((ev as MessageEvent).data) as AgentEvent);
  });
  // NOTE: the browser also fires 'error' on connection trouble — those have no .data.
  // Only a server-sent turn error is a MessageEvent with .data.
  es.addEventListener("error", (ev) => {
    const data = (ev as MessageEvent).data;
    if (typeof data === "string" && data.length > 0) {
      handlers.onTurnError(JSON.parse(data) as TurnErrorEvent);
    }
    // else: connection blip; EventSource auto-reconnects and will fire 'open' again.
  });
  return es;
}

export interface HitlQueueItem {
  taskId: number;
  applicationId: number;
  customerName: string;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  amountRequested: number | null;
  termMonths: number | null;
  createdAt: string | null;
}

export interface HitlTaskView {
  taskId: number;
  applicationId: number;
  customerName: string;
  amountRequested: number | null;
  termMonths: number | null;
  purpose: string | null;
  state: string;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  agentReasoning: string | null;
  agentExploreHints: string | null; // raw JSON text
  agentEvidence: string | null; // raw JSON text
  agentRunId: string;
  humanOutcome: string | null;
  createdAt: string | null;
  closedAt: string | null;
}

export interface DecisionResponse {
  taskId: number;
  state: string;
  humanOutcome: string;
  humanUser: string;
}

export function listHitlTasks(): Promise<HitlQueueItem[]> {
  return fetch("/v1/hitl/tasks?state=OPEN").then((r) =>
    json<HitlQueueItem[]>(r),
  );
}

export function getHitlTask(taskId: number): Promise<HitlTaskView> {
  return fetch(`/v1/hitl/tasks/${taskId}`).then((r) => json<HitlTaskView>(r));
}

export function decideHitlTask(
  taskId: number,
  body: { outcome: "APPROVE" | "REJECT"; note: string; reviewer: string },
): Promise<DecisionResponse> {
  return fetch(`/v1/hitl/tasks/${taskId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<DecisionResponse>(r));
}
