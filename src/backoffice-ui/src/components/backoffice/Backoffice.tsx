import { useState } from "react";
import { Queue } from "./Queue";
import { TaskDetail } from "./TaskDetail";
import { History } from "./History";
import { cn } from "@/lib/utils";

/** The queue stays on screen while a case is open: a reviewer works through a
 *  list, and swapping the whole screen for each case loses their place. */
function ReviewQueue() {
  const [selected, setSelected] = useState<number | null>(null);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[19rem_minmax(0,1fr)]">
      <aside className="border-b border-ink-hair lg:border-b-0 lg:border-r">
        <Queue selected={selected} onOpen={setSelected} />
      </aside>
      <main className="min-w-0">
        {selected === null ? (
          <div className="flex h-full items-center justify-center px-8 py-16 text-center">
            <p className="max-w-sm text-sm leading-relaxed text-ink-mute">
              Pick a case from the queue. You will see what the agent found, and
              the decision is yours to make.
            </p>
          </div>
        ) : (
          <TaskDetail taskId={selected} onDecided={() => setSelected(null)} />
        )}
      </main>
    </div>
  );
}

const icon = "h-[18px] w-[18px] shrink-0";

/** Cases arrive in the queue the way post arrives: unopened, waiting on you. */
function TrayIcon() {
  return (
    <svg
      className={icon}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2.5" y="4.5" width="15" height="11" rx="1.5" />
      <path d="M3.2 5.6 10 10.8l6.8-5.2" />
    </svg>
  );
}

/** A closed decision is a filed record — written once, kept. */
function RecordIcon() {
  return (
    <svg
      className={icon}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5.5 2.5h5.2L15.5 7v10.5a0 0 0 0 1 0 0H5.5a1 1 0 0 1-1-1v-13a1 1 0 0 1 1-1Z" />
      <path d="M10.6 2.6V7h4.6" />
      <path d="M7.2 11h5.4M7.2 13.8h3.4" />
    </svg>
  );
}

const tab =
  "flex items-center gap-2 px-3 py-3.5 text-base font-medium border-b-2 -mb-px transition-colors";

function Nav({ active }: { active: "queue" | "history" }) {
  return (
    <nav className="border-b border-ink-hair">
      <div className="flex gap-4 px-6">
        <a
          href="/backoffice"
          aria-current={active === "queue" ? "page" : undefined}
          className={cn(
            tab,
            active === "queue"
              ? "border-paper text-paper"
              : "border-transparent text-ink-mute hover:text-paper",
          )}
        >
          <TrayIcon />
          Review queue
        </a>
        <a
          href="/backoffice/history"
          aria-current={active === "history" ? "page" : undefined}
          className={cn(
            tab,
            active === "history"
              ? "border-paper text-paper"
              : "border-transparent text-ink-mute hover:text-paper",
          )}
        >
          <RecordIcon />
          Decision history
        </a>
      </div>
    </nav>
  );
}

export function Backoffice() {
  const isHistory = window.location.pathname.startsWith("/backoffice/history");

  return (
    <div className="flex min-h-screen flex-col bg-ink">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-ink-hair px-6 py-5">
        <span className="text-2xl font-semibold tracking-tight text-paper">
          Loan Review
        </span>
        <span className="text-base text-ink-mute">Northbank credit desk</span>
      </header>
      <Nav active={isHistory ? "history" : "queue"} />
      {isHistory ? <History /> : <ReviewQueue />}
    </div>
  );
}
