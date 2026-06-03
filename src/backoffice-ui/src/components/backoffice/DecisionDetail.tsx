import { useEffect, useState } from "react";
import { getDecision, type DecisionToolCall, type DecisionView } from "@/api";
import {
  Badge,
  EvidencePanel,
  money,
  recommendationTone,
} from "./EvidencePanel";

const outcomeTone = (o: string) => (o === "APPROVE" ? "good" : "bad");
const statusTone = (s: string) =>
  s === "SUCCESS" ? "good" : s === "SKIPPED" ? "neutral" : "bad";

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

function ToolTrace({
  calls,
  runId,
}: {
  calls: DecisionToolCall[];
  runId: string;
}) {
  if (!calls.length) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-400">
        No tool trace recorded for run {runId}.
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-400">
            <th className="p-2 font-medium">#</th>
            <th className="p-2 font-medium">Tool</th>
            <th className="p-2 font-medium">Status</th>
            <th className="p-2 font-medium">Duration</th>
            <th className="p-2 font-medium">Started</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr
              key={c.auditId}
              className="border-b border-slate-100 align-top last:border-0"
            >
              <td className="p-2 text-slate-500">{c.stepNo}</td>
              <td className="p-2">
                <span className="font-medium">{c.toolName}</span>
                {(c.toolInput || c.toolOutput) && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-slate-400 hover:underline">
                      input / output
                    </summary>
                    {c.toolInput && (
                      <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
                        {c.toolInput}
                      </pre>
                    )}
                    {c.toolOutput && (
                      <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
                        {c.toolOutput}
                      </pre>
                    )}
                  </details>
                )}
              </td>
              <td className="p-2">
                <Badge tone={statusTone(c.status)}>{c.status}</Badge>
              </td>
              <td className="p-2 text-slate-500">
                {c.durationMs != null ? `${c.durationMs} ms` : "—"}
              </td>
              <td className="p-2 text-xs text-slate-500">
                {fmtDate(c.startedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
