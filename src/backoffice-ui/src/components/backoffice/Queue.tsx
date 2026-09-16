import { useEffect, useState } from "react";
import { claimNextTask, listHitlTasks, type HitlQueueItem } from "@/api";
import { money, outcomeDot } from "./EvidencePanel";
import { cn } from "@/lib/utils";

// PoC: a single backoffice reviewer, no login. Recorded as assigned_to.
const REVIEWER = "Backoffice Reviewer";

export function Queue({
  selected,
  onOpen,
}: {
  selected: number | null;
  onOpen: (taskId: number) => void;
}) {
  const [tasks, setTasks] = useState<HitlQueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    listHitlTasks()
      .then(setTasks)
      .catch(() => setError("The queue did not load. Check the backend is up."));
  }, [selected, refresh]);

  const waiting = tasks.filter((t) => t.state === "OPEN").length;

  // Claiming takes a case off the queue and onto this reviewer, in one step, so
  // two people never open the same one. Picking a row by hand does not.
  async function claim() {
    setClaiming(true);
    setNote(null);
    try {
      const claimed = await claimNextTask(REVIEWER);
      setRefresh((n) => n + 1);
      if (claimed) onOpen(claimed.taskId);
      else setNote("Nothing waiting to claim.");
    } catch {
      setError("The claim did not go through. Check the backend is up.");
    } finally {
      setClaiming(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-baseline justify-between px-5 pb-2 pt-4">
        <h1 className="text-sm font-semibold text-paper">Awaiting a decision</h1>
        <span className="text-xs text-ink-mute">{waiting}</span>
      </div>

      <div className="px-5 pb-4">
        <button
          onClick={claim}
          disabled={claiming || waiting === 0}
          className="w-full rounded-card border border-paper/20 px-3 py-2 text-sm font-medium text-paper transition-colors hover:bg-ink-raised disabled:cursor-not-allowed disabled:opacity-40"
        >
          {claiming ? "Claiming…" : "Claim next"}
        </button>
        {note && <p className="mt-2 text-xs text-ink-mute">{note}</p>}
      </div>

      {error && (
        <p className="mx-5 mb-3 rounded-card border border-decline/30 bg-decline/10 px-3 py-2 text-sm text-decline">
          {error}
        </p>
      )}

      {tasks.length === 0 && !error && (
        <p className="px-5 pb-5 text-sm leading-relaxed text-ink-mute">
          Nothing waiting. Cases arrive here when the assistant files a
          recommendation for a customer.
        </p>
      )}

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {tasks.map((t) => (
          <li key={t.taskId}>
            <button
              onClick={() => onOpen(t.taskId)}
              className={cn(
                "w-full border-l-2 px-5 py-3 text-left transition-colors",
                t.taskId === selected
                  ? "border-paper bg-ink-raised"
                  : "border-transparent hover:bg-ink-raised/60",
              )}
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-medium text-paper">
                  {t.customerName}
                </span>
                <span className="shrink-0 text-sm text-paper">
                  {t.amountRequested != null ? money(t.amountRequested) : "—"}
                </span>
              </span>
              <span className="mt-1 flex items-center gap-2 text-xs text-ink-mute">
                <span
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    outcomeDot(t.agentRecommendation),
                  )}
                />
                {t.agentRecommendation.toLowerCase()} suggested
                <span className="ml-auto">
                  {t.state === "IN_REVIEW"
                    ? `with ${t.assignedTo ?? "a reviewer"}`
                    : `${t.termMonths ?? "—"} months`}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
