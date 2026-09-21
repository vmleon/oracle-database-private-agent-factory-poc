async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface HitlQueueItem {
  taskId: number;
  applicationId: number;
  customerName: string;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  amountRequested: number | null;
  termMonths: number | null;
  createdAt: string | null;
  state: "OPEN" | "IN_REVIEW";
  assignedTo: string | null;
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
  toolCalls: DecisionToolCall[];
}

export interface DecisionResponse {
  taskId: number;
  state: string;
  humanOutcome: string;
  humanUser: string;
}

export function listHitlTasks(): Promise<HitlQueueItem[]> {
  return fetch("/v1/hitl/tasks").then((r) => json<HitlQueueItem[]>(r));
}

/** Take the next waiting case. Resolves null when nothing is waiting. */
export function claimNextTask(reviewer: string): Promise<HitlTaskView | null> {
  return fetch(`/v1/hitl/claim?reviewer=${encodeURIComponent(reviewer)}`, {
    method: "POST",
  }).then((r) => {
    if (r.status === 204) return null;
    return json<HitlTaskView>(r);
  });
}

export function getHitlTask(taskId: number): Promise<HitlTaskView> {
  return fetch(`/v1/hitl/tasks/${taskId}`).then((r) => json<HitlTaskView>(r));
}

export function decideHitlTask(
  taskId: number,
  body: { outcome: "APPROVE" | "DECLINE"; note: string; reviewer: string },
): Promise<DecisionResponse> {
  return fetch(`/v1/hitl/tasks/${taskId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<DecisionResponse>(r));
}

export interface DecisionListItem {
  decisionId: number;
  applicationId: number;
  customerName: string;
  humanOutcome: "APPROVE" | "DECLINE";
  humanUser: string;
  decidedAt: string | null;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  amountRequested: number | null;
  termMonths: number | null;
}

export interface DecisionToolCall {
  auditId: number;
  stepNo: number;
  toolName: string;
  toolInput: string | null; // raw JSON text
  toolOutput: string | null; // raw JSON text
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  status: "SUCCESS" | "FAILED" | "SKIPPED" | "TIMEOUT";
}

export interface DecisionView {
  decisionId: number;
  applicationId: number;
  customerName: string;
  amountRequested: number | null;
  termMonths: number | null;
  purpose: string | null;
  humanOutcome: "APPROVE" | "DECLINE";
  humanUser: string;
  humanNote: string | null;
  decidedAt: string | null;
  agentRecommendation: "APPROVE" | "REVIEW" | "DECLINE";
  agentReasoning: string | null;
  agentExploreHints: string | null; // raw JSON text
  agentEvidence: string | null; // raw JSON text
  agentRunId: string;
  pricingOffer: string | null; // raw JSON text
  reasonCodes: string | null; // raw JSON text
  computedDti: number | null;
  computedPti: number | null;
  toolCalls: DecisionToolCall[];
}

export function listDecisions(filters?: {
  customerId?: number;
  applicationId?: number;
}): Promise<DecisionListItem[]> {
  const q = new URLSearchParams();
  if (filters?.customerId != null) q.set("customerId", String(filters.customerId));
  if (filters?.applicationId != null)
    q.set("applicationId", String(filters.applicationId));
  const qs = q.toString();
  return fetch(`/v1/hitl/decisions${qs ? `?${qs}` : ""}`).then((r) =>
    json<DecisionListItem[]>(r),
  );
}

export function getDecision(decisionId: number): Promise<DecisionView> {
  return fetch(`/v1/hitl/decisions/${decisionId}`).then((r) =>
    json<DecisionView>(r),
  );
}

export interface ResearchView {
  taskId: number;
  summary: string;
  reviewer: string;
  createdAt: string | null;
  researchRunId: string | null;
}

/** The stored summary for a task, or null when research has never been run. */
export async function getResearch(
  taskId: number,
): Promise<ResearchView | null> {
  const r = await fetch(`/v1/research/tasks/${taskId}`);
  if (r.status === 204) return null;
  return json<ResearchView>(r);
}

export function runResearch(
  taskId: number,
  reviewer: string,
): Promise<ResearchView> {
  return fetch(`/v1/research/tasks/${taskId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer }),
  }).then((r) => json<ResearchView>(r));
}
