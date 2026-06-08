import { useEffect, useState } from "react";
import { getDecision, type DecisionView } from "@/api";
import {
  Badge,
  EvidencePanel,
  money,
  recommendationTone,
} from "./EvidencePanel";
import { ToolTrace } from "./ToolTrace";

const outcomeTone = (o: string) => (o === "APPROVE" ? "good" : "bad");

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

export function DecisionDetail({
  decisionId,
  onBack,
}: {
  decisionId: number;
  onBack: () => void;
}) {
  const [d, setD] = useState<DecisionView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDecision(decisionId)
      .then(setD)
      .catch(() => setError("Could not load the decision."));
  }, [decisionId]);

  if (!d) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        {error ? (
          <p className="text-sm text-red-700">{error}</p>
        ) : (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <button
        onClick={onBack}
        className="mb-4 text-sm text-slate-500 hover:underline"
      >
        ← Back to history
      </button>
      <h1 className="text-2xl font-semibold">{d.customerName}</h1>
      <p className="mb-4 text-sm text-slate-500">
        Decision {d.decisionId} · Application {d.applicationId} ·{" "}
        {d.purpose ?? "—"} ·{" "}
        {d.amountRequested != null ? money(d.amountRequested) : "—"} over{" "}
        {d.termMonths ?? "—"} months
      </p>

      {/* Human decision — the bank's tamper-evident call */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Decision</span>
          <Badge tone={outcomeTone(d.humanOutcome)}>{d.humanOutcome}</Badge>
        </div>
        <p className="mt-2 text-sm text-slate-700">
          {d.humanNote || <span className="text-slate-400">No note.</span>}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          {d.humanUser} · {fmtDate(d.decidedAt)}
        </p>
      </div>

      {/* Agent recommendation packet that informed the decision */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Agent recommendation</span>
          <Badge tone={recommendationTone(d.agentRecommendation)}>
            {d.agentRecommendation}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-slate-700">{d.agentReasoning}</p>
        {d.agentExploreHints && (
          <pre className="mt-3 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
            {d.agentExploreHints}
          </pre>
        )}
      </div>

      {d.agentEvidence && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Evidence</h2>
          <EvidencePanel raw={d.agentEvidence} />
        </div>
      )}

      <div className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">
          Tools called
        </h2>
        <ToolTrace calls={d.toolCalls} runId={d.agentRunId} />
      </div>
    </div>
  );
}
