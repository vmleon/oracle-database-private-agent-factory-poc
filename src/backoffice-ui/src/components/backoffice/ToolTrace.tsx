import { type DecisionToolCall } from "@/api";
import { Badge } from "./EvidencePanel";

const statusTone = (s: string) =>
  s === "SUCCESS" ? "good" : s === "SKIPPED" ? "neutral" : "bad";

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString() : "—";

const fmtScalar = (v: unknown) =>
  v === null || v === undefined ? "—" : String(v);

/** Render a parsed JSON value as readable rows, recursing into nested objects
 *  and arrays instead of dumping them as raw JSON text. */
function ValueTree({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slate-400">empty</span>;
    return (
      <div className="space-y-1">
        {value.map((item, i) =>
          item && typeof item === "object" ? (
            <div key={i} className="rounded border border-slate-100 p-1">
              <ValueTree value={item} />
            </div>
          ) : (
            <div key={i} className="text-slate-800">
              • {fmtScalar(item)}
            </div>
          ),
        )}
      </div>
    );
  }
  if (value && typeof value === "object") {
    return (
      <dl className="divide-y divide-slate-100">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => {
          const nested = v != null && typeof v === "object";
          return (
            <div key={k} className="px-2 py-1 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">{k}</dt>
                {!nested && (
                  <dd className="break-all text-right font-medium text-slate-800">
                    {fmtScalar(v)}
                  </dd>
                )}
              </div>
              {nested && (
                <div className="mt-1 border-l border-slate-100 pl-2">
                  <ValueTree value={v} />
                </div>
              )}
            </div>
          );
        })}
      </dl>
    );
  }
  return <span className="font-medium text-slate-800">{fmtScalar(value)}</span>;
}

/** A tool input/output payload: rendered as a value tree when it's JSON, or
 *  raw text when it isn't. */
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
      {parsed != null && typeof parsed === "object" ? (
        <div className="mt-1 rounded border border-slate-100">
          <ValueTree value={parsed} />
        </div>
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
        <details
          key={c.auditId}
          className="rounded-lg border border-slate-200 bg-white [&[open]_.chevron]:rotate-90"
        >
          <summary className="flex cursor-pointer list-none items-center gap-2 p-3 text-sm [&::-webkit-details-marker]:hidden">
            <svg
              className="chevron h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M7 5l6 5-6 5V5z" />
            </svg>
            <span className="text-slate-400">#{c.stepNo}</span>
            <span className="font-medium">{c.toolName}</span>
            <Badge tone={statusTone(c.status)}>{c.status}</Badge>
            <span className="ml-auto text-xs text-slate-500">
              {c.durationMs != null ? `${c.durationMs} ms` : "—"} ·{" "}
              {fmtDate(c.startedAt)}
            </span>
          </summary>
          <div className="border-t border-slate-100 p-3 pt-2">
            <Payload label="Input" raw={c.toolInput} />
            <Payload label="Output" raw={c.toolOutput} />
          </div>
        </details>
      ))}
    </div>
  );
}
