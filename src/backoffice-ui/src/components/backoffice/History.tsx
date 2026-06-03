import { useEffect, useState } from "react";
import { listDecisions, type DecisionListItem } from "@/api";
import { Badge, money, recommendationTone } from "./EvidencePanel";
import { DecisionDetail } from "./DecisionDetail";

const outcomeTone = (o: string) => (o === "APPROVE" ? "good" : "bad");

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

export function History() {
  const [decisions, setDecisions] = useState<DecisionListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  const load = () => {
    setError(null);
    listDecisions({
      customerId: customerId.trim() ? Number(customerId) : undefined,
      applicationId: applicationId.trim() ? Number(applicationId) : undefined,
    })
      .then(setDecisions)
      .catch(() =>
        setError("Could not load decision history. Is the backend running?"),
      );
  };

  // Initial load (unfiltered). The Apply button re-runs with the filters.
  useEffect(() => {
    listDecisions()
      .then(setDecisions)
      .catch(() =>
        setError("Could not load decision history. Is the backend running?"),
      );
  }, []);

  if (selected !== null) {
    return (
      <DecisionDetail
        decisionId={selected}
        onBack={() => setSelected(null)}
      />
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="mb-1 text-2xl font-semibold">Decision history</h1>
      <p className="mb-6 text-sm text-slate-500">
        Closed loan decisions — the defensible record behind each call.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
        className="mb-6 flex flex-wrap items-end gap-3"
      >
        <label className="text-xs font-medium text-slate-500">
          Customer ID
          <input
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            inputMode="numeric"
            className="mt-1 block w-32 rounded-md border border-slate-200 p-2 text-sm text-slate-900"
            placeholder="any"
          />
        </label>
        <label className="text-xs font-medium text-slate-500">
          Application ID
          <input
            value={applicationId}
            onChange={(e) => setApplicationId(e.target.value)}
            inputMode="numeric"
            className="mt-1 block w-32 rounded-md border border-slate-200 p-2 text-sm text-slate-900"
            placeholder="any"
          />
        </label>
        <button
          type="submit"
          className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Apply
        </button>
      </form>

      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      {decisions.length === 0 && !error && (
        <p className="text-sm text-slate-500">No decisions found.</p>
      )}
      <ul className="space-y-2">
        {decisions.map((d) => (
          <li key={d.decisionId}>
            <button
              onClick={() => setSelected(d.decisionId)}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 text-left hover:border-slate-400"
            >
              <span>
                <span className="font-medium">{d.customerName}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {d.amountRequested != null ? money(d.amountRequested) : "—"} ·{" "}
                  {d.termMonths ?? "—"} months · {fmtDate(d.decidedAt)}
                </span>
              </span>
              <span className="flex items-center gap-3">
                <Badge tone={outcomeTone(d.humanOutcome)}>
                  {d.humanOutcome}
                </Badge>
                <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                  Agent:
                  <Badge tone={recommendationTone(d.agentRecommendation)}>
                    {d.agentRecommendation}
                  </Badge>
                </span>
                <span className="text-sm text-slate-400">→</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
