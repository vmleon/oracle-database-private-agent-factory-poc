import { money } from "./EvidencePanel";

/** Detail-screen header. The loan request — amount, purpose, term — is the
 *  point of the case, so it leads visually; the ids drop to a muted meta line. */
export function RequestSummary({
  customerName,
  amountRequested,
  purpose,
  termMonths,
  applicationId,
  decisionId,
}: {
  customerName: string;
  amountRequested: number | null;
  purpose: string | null;
  termMonths: number | null;
  applicationId: number;
  decisionId?: number;
}) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{customerName}</h1>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-2xl font-bold text-slate-900">
          {amountRequested != null ? money(amountRequested) : "—"}
        </span>
        <span className="text-slate-300">·</span>
        <span className="text-base font-medium text-slate-700">
          {purpose ?? "—"}
        </span>
        <span className="text-slate-300">·</span>
        <span className="text-sm text-slate-500">{termMonths ?? "—"} months</span>
      </div>
      <div className="mt-1 text-xs text-slate-400">
        {decisionId != null ? `Decision ${decisionId} · ` : ""}
        Application {applicationId}
      </div>
    </div>
  );
}
