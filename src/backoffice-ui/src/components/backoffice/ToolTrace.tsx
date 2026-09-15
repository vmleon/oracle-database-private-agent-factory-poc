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
    if (!value.length) return <span className="text-ink-mute">empty</span>;
    return (
      <div className="space-y-1">
        {value.map((item, i) =>
          item && typeof item === "object" ? (
            <div key={i} className="rounded border border-ink-hair p-1">
              <ValueTree value={item} />
            </div>
          ) : (
            <div key={i} className="text-paper">
              • {fmtScalar(item)}
            </div>
          ),
        )}
      </div>
    );
  }
  if (value && typeof value === "object") {
    return (
      <dl className="divide-y divide-ink-hair">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => {
          const nested = v != null && typeof v === "object";
          return (
            <div key={k} className="px-2 py-1 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-mute">{k}</dt>
                {!nested && (
                  <dd className="break-all text-right font-medium text-paper">
                    {fmtScalar(v)}
                  </dd>
                )}
              </div>
              {nested && (
                <div className="mt-1 border-l border-ink-hair pl-2">
                  <ValueTree value={v} />
                </div>
              )}
            </div>
          );
        })}
      </dl>
    );
  }
  return <span className="font-medium text-paper">{fmtScalar(value)}</span>;
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
      <div className="text-[11px] font-medium text-ink-mute">
        {label}
      </div>
      {parsed != null && typeof parsed === "object" ? (
        <div className="mt-1 rounded border border-ink-hair">
          <ValueTree value={parsed} />
        </div>
      ) : (
        <pre className="mt-1 overflow-x-auto rounded bg-ink p-2 text-xs">
          {raw}
        </pre>
      )}
    </div>
  );
}

/** The trace is how a reviewer checks the agent's working, not how they reach a
 *  decision — so it sits closed until someone asks for it. */
export function ToolTrace({
  calls,
  runId,
}: {
  calls: DecisionToolCall[];
  runId?: string;
}) {
  return (
    <details className="rounded-card border border-ink-hair [&[open]_.chevron-outer]:rotate-90">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm [&::-webkit-details-marker]:hidden">
        <svg
          className="chevron-outer h-3.5 w-3.5 shrink-0 text-ink-mute transition-transform"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M7 5l6 5-6 5V5z" />
        </svg>
        <span className="font-medium text-paper">Tools called</span>
        <span className="ml-auto text-xs text-ink-mute">
          {calls.length || "none"}
        </span>
      </summary>
      <div className="border-t border-ink-hair p-3">
        <ToolCalls calls={calls} runId={runId} />
      </div>
    </details>
  );
}

function ToolCalls({
  calls,
  runId,
}: {
  calls: DecisionToolCall[];
  runId?: string;
}) {
  if (!calls.length) {
    return (
      <p className="text-sm text-ink-mute">
        {runId
          ? `Nothing recorded for run ${runId}.`
          : "Nothing recorded yet."}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {calls.map((c) => (
        <details
          key={c.auditId}
          className="rounded-card border border-ink-hair bg-ink-raised [&[open]_.chevron]:rotate-90"
        >
          <summary className="flex cursor-pointer list-none items-center gap-2 p-3 text-sm [&::-webkit-details-marker]:hidden">
            <svg
              className="chevron h-3.5 w-3.5 shrink-0 text-ink-mute transition-transform"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M7 5l6 5-6 5V5z" />
            </svg>
            <span className="text-ink-mute">#{c.stepNo}</span>
            <span className="font-medium">{c.toolName}</span>
            <Badge tone={statusTone(c.status)}>{c.status}</Badge>
            <span className="ml-auto text-xs text-ink-mute">
              {c.durationMs != null ? `${c.durationMs} ms` : "—"}{" at "}
              {fmtDate(c.startedAt)}
            </span>
          </summary>
          <div className="border-t border-ink-hair p-3 pt-2">
            <Payload label="Input" raw={c.toolInput} />
            <Payload label="Output" raw={c.toolOutput} />
          </div>
        </details>
      ))}
    </div>
  );
}
