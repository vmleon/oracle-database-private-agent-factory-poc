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
      <h1 className="text-sm font-medium text-ink-mute">{customerName}</h1>
      <div className="mt-3 text-[2.5rem] font-semibold leading-none tracking-tight text-paper">
        {amountRequested != null ? money(amountRequested) : "—"}
      </div>
      <p className="mt-2 text-sm text-ink-mute">
        {purpose ?? "No purpose given"}, over {termMonths ?? "—"} months
      </p>
      <p className="mt-1 text-xs text-ink-mute">
        Application {applicationId}
        {decisionId != null ? `, decision ${decisionId}` : ""}
      </p>
    </div>
  );
}
