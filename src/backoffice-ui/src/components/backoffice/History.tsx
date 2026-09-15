import { useEffect, useState } from "react";
import { listDecisions, type DecisionListItem } from "@/api";
import { Badge, money } from "./EvidencePanel";
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
      <p className="mb-6 text-sm text-ink-mute">
        Closed loan decisions — the defensible record behind each call.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
        className="mb-6 flex flex-wrap items-end gap-3"
      >
        <label className="text-xs font-medium text-ink-mute">
          Customer ID
          <input
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            inputMode="numeric"
            className="mt-1 block w-32 rounded-card border border-ink-hair bg-ink-raised p-2 text-sm text-paper placeholder:text-ink-mute"
            placeholder="any"
          />
        </label>
        <label className="text-xs font-medium text-ink-mute">
          Application ID
          <input
            value={applicationId}
            onChange={(e) => setApplicationId(e.target.value)}
            inputMode="numeric"
            className="mt-1 block w-32 rounded-card border border-ink-hair bg-ink-raised p-2 text-sm text-paper placeholder:text-ink-mute"
            placeholder="any"
          />
        </label>
        <button
          type="submit"
          className="rounded-card bg-paper px-4 py-2 text-sm font-medium text-ink hover:bg-paper/90"
        >
          Apply
        </button>
      </form>

      {error && (
        <p className="mb-4 rounded bg-decline/10 p-3 text-sm text-decline">
          {error}
        </p>
      )}
      {decisions.length === 0 && !error && (
        <p className="text-sm text-ink-mute">No decisions found.</p>
      )}
      <ul className="space-y-2">
        {decisions.map((d) => (
          <li key={d.decisionId}>
            <button
              onClick={() => setSelected(d.decisionId)}
              className="flex w-full items-center justify-between gap-3 rounded-card border border-ink-hair bg-ink-raised p-4 text-left hover:border-ink-mute"
            >
              <span className="min-w-0">
                <span className="flex items-baseline gap-2">
                  <span className="truncate font-medium text-paper">
                    {d.customerName}
                  </span>
                  <span className="text-sm text-paper">
                    {d.amountRequested != null ? money(d.amountRequested) : "—"}
                  </span>
                </span>
                <span className="mt-0.5 block text-xs text-ink-mute">
                  over {d.termMonths ?? "—"} months, decided{" "}
                  {fmtDate(d.decidedAt)}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <Badge tone={outcomeTone(d.humanOutcome)}>
                  {d.humanOutcome.toLowerCase()}
                </Badge>
                <span className="text-xs text-ink-mute">
                  agent said {d.agentRecommendation.toLowerCase()}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
