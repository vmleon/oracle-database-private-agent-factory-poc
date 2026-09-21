import { useEffect, useState } from "react";
import { decideHitlTask, getHitlTask, type HitlTaskView } from "@/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Badge, EvidencePanel, recommendationTone } from "./EvidencePanel";
import { RequestSummary } from "./RequestSummary";
import { ResearchPanel } from "./ResearchPanel";
import { ToolTrace } from "./ToolTrace";

// PoC: a single backoffice reviewer, no login. Recorded as human_user.
const REVIEWER = "Backoffice Reviewer";

export function TaskDetail({
  taskId,
  onDecided,
}: {
  taskId: number;
  onDecided: () => void;
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
      onDecided();
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
      <div className="mx-auto max-w-3xl px-6 py-6">
        {error ? (
          <p className="text-sm text-decline">{error}</p>
        ) : (
          <p className="text-sm text-ink-mute">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-6">
      <RequestSummary
        customerName={task.customerName}
        amountRequested={task.amountRequested}
        purpose={task.purpose}
        termMonths={task.termMonths}
        applicationId={task.applicationId}
      />

      <div className="mb-6 rounded-card border border-ink-hair bg-ink-raised p-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Agent recommendation</span>
          <Badge tone={recommendationTone(task.agentRecommendation)}>
            {task.agentRecommendation}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-paper">{task.agentReasoning}</p>
        {task.agentExploreHints && (
          <pre className="mt-3 overflow-x-auto rounded bg-ink p-2 text-xs">
            {task.agentExploreHints}
          </pre>
        )}
      </div>

      {task.agentEvidence && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-paper">Evidence</h2>
          <EvidencePanel raw={task.agentEvidence} />
        </div>
      )}

      <ResearchPanel taskId={taskId} reviewer={REVIEWER} />

      {error && (
        <p className="mb-4 rounded bg-decline/10 p-3 text-sm text-decline">
          {error}
        </p>
      )}

      <div className="mb-6 rounded-card border border-ink-hair bg-ink-raised p-4">
        <div className="mb-3 flex gap-2">
          <button
            onClick={() => setOutcome("APPROVE")}
            aria-pressed={outcome === "APPROVE"}
            className={cn(
              "inline-flex flex-1 items-center justify-center rounded-card px-4 py-2.5 text-sm font-semibold transition-colors",
              outcome === "APPROVE"
                ? "bg-approve text-paper"
                : "border border-approve/40 text-approve hover:bg-approve/10",
            )}
          >
            Approve
          </button>
          <button
            onClick={() => setOutcome("DECLINE")}
            aria-pressed={outcome === "DECLINE"}
            className={cn(
              "inline-flex flex-1 items-center justify-center rounded-card px-4 py-2.5 text-sm font-semibold transition-colors",
              outcome === "DECLINE"
                ? "bg-decline text-paper"
                : "border border-decline/40 text-decline hover:bg-decline/10",
            )}
          >
            Decline
          </button>
        </div>
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
          placeholder="Say why. This is recorded with the decision and cannot be changed later."
          rows={2}
          className="w-full rounded-card border border-ink-hair bg-ink-raised p-3 text-sm text-paper placeholder:text-ink-mute"
        />
        <Button
          onClick={submit}
          disabled={busy || noteMissing || !outcome}
          className="mt-3 w-full py-2.5"
        >
          {busy
            ? "Recording"
            : outcome
              ? `Record ${outcome.toLowerCase()} decision`
              : "Choose approve or decline"}
        </Button>
      </div>

      <ToolTrace calls={task.toolCalls} runId={task.agentRunId} />
    </div>
  );
}
