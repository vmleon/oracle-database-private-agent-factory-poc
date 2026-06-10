import { useEffect, useState } from "react";
import { decideHitlTask, getHitlTask, type HitlTaskView } from "@/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Badge, EvidencePanel, recommendationTone } from "./EvidencePanel";
import { RequestSummary } from "./RequestSummary";
import { ToolTrace } from "./ToolTrace";

// PoC: a single backoffice reviewer, no login. Recorded as human_user.
const REVIEWER = "Backoffice Reviewer";

export function TaskDetail({
  taskId,
  onBack,
}: {
  taskId: number;
  onBack: () => void;
}) {
  const [task, setTask] = useState<HitlTaskView | null>(null);
  // Preselected from the agent recommendation: APPROVE→Approve, DECLINE→Decline,
  // REVIEW→nothing (the reviewer must make a deliberate call).
  const [outcome, setOutcome] = useState<"APPROVE" | "DECLINE" | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getHitlTask(taskId)
      .then((t) => {
        setTask(t);
        if (t.agentRecommendation === "APPROVE") setOutcome("APPROVE");
        else if (t.agentRecommendation === "DECLINE") setOutcome("DECLINE");
      })
      .catch(() => setError("Could not load the task."));
  }, [taskId]);

  const noteMissing = note.trim() === "";

  const submit = async () => {
    if (noteMissing || !outcome) return;
    setBusy(true);
    setError(null);
    try {
      await decideHitlTask(taskId, { outcome, note, reviewer: REVIEWER });
      onBack();
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("409")
          ? "This task was already decided."
          : "Could not submit the decision.",
      );
      setBusy(false);
    }
  };

  if (!task) {
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
        ← Back to queue
      </button>
      <RequestSummary
        customerName={task.customerName}
        amountRequested={task.amountRequested}
        purpose={task.purpose}
        termMonths={task.termMonths}
        applicationId={task.applicationId}
      />

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Agent recommendation</span>
          <Badge tone={recommendationTone(task.agentRecommendation)}>
            {task.agentRecommendation}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-slate-700">{task.agentReasoning}</p>
        {task.agentExploreHints && (
          <pre className="mt-3 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
            {task.agentExploreHints}
          </pre>
        )}
      </div>

      {task.agentEvidence && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Evidence</h2>
          <EvidencePanel raw={task.agentEvidence} />
        </div>
      )}

      <div className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">
          Tools called
        </h2>
        <ToolTrace calls={task.toolCalls} runId={task.agentRunId} />
      </div>

      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="space-y-3">
        <div className="flex gap-2">
          <button
            onClick={() => setOutcome("APPROVE")}
            className={cn(
              "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors",
              outcome === "APPROVE"
                ? "bg-emerald-600 text-white"
                : "border border-emerald-300 bg-white text-emerald-700 hover:bg-emerald-50",
            )}
          >
            Approve
          </button>
          <button
            onClick={() => setOutcome("DECLINE")}
            className={cn(
              "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors",
              outcome === "DECLINE"
                ? "bg-rose-600 text-white"
                : "border border-rose-300 bg-white text-rose-700 hover:bg-rose-50",
            )}
          >
            Decline
          </button>
        </div>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            Comments (mandatory)
          </span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              // Enter submits; Shift+Enter inserts a newline.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Why you reached this decision…"
            rows={3}
            className="w-full rounded-md border border-slate-200 p-2 text-sm"
          />
        </label>
        {noteMissing && (
          <p className="text-xs text-slate-500">
            Comments are required before submitting a decision.
          </p>
        )}
        <Button onClick={submit} disabled={busy || noteMissing || !outcome}>
          {busy ? "Submitting…" : "Submit decision"}
        </Button>
      </div>
    </div>
  );
}
