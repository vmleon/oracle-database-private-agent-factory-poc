import { type DecisionToolCall } from "@/api";
import { Badge } from "./EvidencePanel";

const statusTone = (s: string) =>
  s === "SUCCESS" ? "good" : s === "SKIPPED" ? "neutral" : "bad";

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

/** Render a tool input/output payload as readable key→value rows; fall back to
 *  the raw text when it isn't a flat JSON object. */
function Payload({ label, raw }: { label: string; raw: string | null }) {
  if (!raw) return null;

  let parsed: unknown = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = null;
  }

  return (
    <div className="mt-2">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </div>
      {parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (
        <dl className="mt-1 divide-y divide-slate-100 rounded border border-slate-100">
          {Object.entries(parsed as Record<string, unknown>).map(([k, v]) => (
            <div
              key={k}
              className="flex justify-between gap-3 px-2 py-1 text-xs"
            >
              <dt className="text-slate-500">{k}</dt>
              <dd className="break-all text-right font-medium text-slate-800">
                {typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
          {raw}
        </pre>
      )}
    </div>
  );
}

export function ToolTrace({
  calls,
  runId,
}: {
  calls: DecisionToolCall[];
  runId?: string;
}) {
  if (!calls.length) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-400">
        {runId
          ? `No tool trace recorded for run ${runId}.`
          : "No tool trace recorded yet."}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {calls.map((c) => (
        <div
          key={c.auditId}
          className="rounded-lg border border-slate-200 bg-white p-3"
        >
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-400">#{c.stepNo}</span>
            <span className="font-medium">{c.toolName}</span>
            <Badge tone={statusTone(c.status)}>{c.status}</Badge>
            <span className="ml-auto text-xs text-slate-500">
              {c.durationMs != null ? `${c.durationMs} ms` : "—"} ·{" "}
              {fmtDate(c.startedAt)}
            </span>
          </div>
          <Payload label="Input" raw={c.toolInput} />
          <Payload label="Output" raw={c.toolOutput} />
        </div>
      ))}
    </div>
  );
}
