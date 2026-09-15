import { useEffect, useState } from "react";
import { getDecision, type DecisionView } from "@/api";
import { Badge, EvidencePanel, money, recommendationTone } from "./EvidencePanel";
import { RequestSummary } from "./RequestSummary";
import { ToolTrace } from "./ToolTrace";

const outcomeTone = (o: string) => (o === "APPROVE" ? "good" : "bad");

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

const pct = (n: number | null) => (n === null ? "—" : `${(n * 100).toFixed(1)}%`);

/** The raw JSON columns are stored as text; a bad parse shows nothing rather than crashing. */
const parse = <T,>(raw: string | null): T | null => {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
};

interface PricingOffer {
  risk_band?: string;
  rate_value?: number;
  amount?: number;
  term_months?: number;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{value}</span>
    </div>
  );
}

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
      <RequestSummary
        customerName={d.customerName}
        amountRequested={d.amountRequested}
        purpose={d.purpose}
        termMonths={d.termMonths}
        applicationId={d.applicationId}
        decisionId={d.decisionId}
      />

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

      {/* The typed columns of the blockchain row. The table is append-only, so
          these are the figures as they stood when the decision was recorded. */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Recorded figures
        </h3>
        <Row label="Debt-to-income" value={pct(d.computedDti)} />
        <Row label="Payment-to-income" value={pct(d.computedPti)} />
        {(() => {
          const offer = parse<PricingOffer>(d.pricingOffer);
          if (!offer) return <Row label="Indicative offer" value="—" />;
          return (
            <>
              <Row label="Risk band" value={offer.risk_band ?? "—"} />
              <Row
                label="Indicative rate"
                value={
                  offer.rate_value === undefined
                    ? "—"
                    : `${(offer.rate_value * 100).toFixed(2)}%`
                }
              />
              <Row
                label="On"
                value={
                  offer.amount === undefined
                    ? "—"
                    : `${money(offer.amount)} over ${offer.term_months} months`
                }
              />
            </>
          );
        })()}
        <div className="mt-2 flex flex-wrap gap-1">
          {(parse<string[]>(d.reasonCodes) ?? []).map((code) => (
            <span
              key={code}
              className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
            >
              {code}
            </span>
          ))}
        </div>
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
