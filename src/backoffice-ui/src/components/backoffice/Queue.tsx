import { useEffect, useState } from "react";
import { listHitlTasks, type HitlQueueItem } from "@/api";
import { Badge, money, recommendationTone } from "./EvidencePanel";

export function Queue({ onOpen }: { onOpen: (taskId: number) => void }) {
  const [tasks, setTasks] = useState<HitlQueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listHitlTasks()
      .then(setTasks)
      .catch(() =>
        setError("Could not load the queue. Is the backend running?"),
      );
  }, []);

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="mb-1 text-2xl font-semibold">Review queue</h1>
      <p className="mb-6 text-sm text-slate-500">
        Open HITL tasks awaiting a decision.
      </p>
      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      {tasks.length === 0 && !error && (
        <p className="text-sm text-slate-500">No open tasks.</p>
      )}
      <ul className="space-y-2">
        {tasks.map((t) => (
          <li key={t.taskId}>
            <button
              onClick={() => onOpen(t.taskId)}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 text-left hover:border-slate-400"
            >
              <span>
                <span className="font-medium">{t.customerName}</span>
                <span className="ml-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">
                    {t.amountRequested != null ? money(t.amountRequested) : "—"}
                  </span>{" "}
                  · {t.termMonths ?? "—"} months
                </span>
              </span>
              <span className="flex items-center gap-3">
                <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                  Agent Recommendation:
                  <Badge tone={recommendationTone(t.agentRecommendation)}>
                    {t.agentRecommendation}
                  </Badge>
                </span>
                <span className="text-sm text-slate-400">→</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
