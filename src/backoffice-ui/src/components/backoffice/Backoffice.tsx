import { useState } from "react";
import { Queue } from "./Queue";
import { TaskDetail } from "./TaskDetail";
import { History } from "./History";
import { cn } from "@/lib/utils";

function ReviewQueue() {
  const [selected, setSelected] = useState<number | null>(null);

  return selected === null ? (
    <Queue onOpen={setSelected} />
  ) : (
    <TaskDetail taskId={selected} onBack={() => setSelected(null)} />
  );
}

const tab =
  "px-4 py-3 text-sm font-medium border-b-2 -mb-px transition-colors";

function Nav({ active }: { active: "queue" | "history" }) {
  return (
    <nav className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-3xl gap-1 px-8">
        <a
          href="/backoffice"
          className={cn(
            tab,
            active === "queue"
              ? "border-slate-800 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          Review queue
        </a>
        <a
          href="/backoffice/history"
          className={cn(
            tab,
            active === "history"
              ? "border-slate-800 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          Decision history
        </a>
      </div>
    </nav>
  );
}

function BankIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 3 21 7H3l9-4Z" />
      <path d="M4 10h16" />
      <path d="M5 10v10M9 10v10M15 10v10M19 10v10" />
      <path d="M3 20h18" />
    </svg>
  );
}

export function Backoffice() {
  const isHistory = window.location.pathname.startsWith("/backoffice/history");

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-slate-800">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-8 py-4 text-lg font-semibold tracking-tight text-white">
          <BankIcon className="h-5 w-5" />
          Loan Review Portal
        </div>
      </header>
      <Nav active={isHistory ? "history" : "queue"} />
      {isHistory ? <History /> : <ReviewQueue />}
    </div>
  );
}
