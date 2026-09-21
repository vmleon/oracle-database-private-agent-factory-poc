import { useEffect, useState } from "react";
import { getResearch, runResearch, type ResearchView } from "@/api";
import { Button } from "@/components/ui/button";

export type { ResearchView };

/** What the panel shows. A stored summary renders on load; a run in flight wins. */
export function researchState(
  view: ResearchView | null,
  busy: boolean,
): "idle" | "running" | "ready" {
  if (busy) return "running";
  return view ? "ready" : "idle";
}

export function ResearchPanel({
  taskId,
  reviewer,
}: {
  taskId: number;
  reviewer: string;
}) {
  const [view, setView] = useState<ResearchView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getResearch(taskId)
      .then(setView)
      .catch(() => setError("Could not load earlier research."));
  }, [taskId]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setView(await runResearch(taskId, reviewer));
    } catch {
      setError("Research could not be run. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const state = researchState(view, busy);

  return (
    <div className="mb-6 rounded-card border border-ink-hair bg-ink-raised p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-paper">Case research</h2>
        <Button onClick={run} disabled={busy}>
          {state === "running"
            ? "Researching…"
            : state === "ready"
              ? "Run again"
              : "Run research"}
        </Button>
      </div>

      {state === "idle" && (
        <p className="mt-2 text-sm text-ink-mute">
          Gathers comparable closed cases, this customer's decision history,
          their full transactions and any policy changes since this case was
          assessed. The decision stays yours.
        </p>
      )}

      {error && <p className="mt-2 text-sm text-decline">{error}</p>}

      {state === "ready" && view && (
        <>
          <pre className="mt-3 whitespace-pre-wrap text-sm text-paper">
            {view.summary}
          </pre>
          <p className="mt-2 text-xs text-ink-mute">
            Run by {view.reviewer}
            {view.createdAt
              ? ` · ${new Date(view.createdAt).toLocaleString()}`
              : ""}
          </p>
        </>
      )}
    </div>
  );
}
