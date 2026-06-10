import { useEffect, useRef } from "react";
import type { Message } from "@/chatState";
import { cn } from "@/lib/utils";

export function MessageList({ messages }: { messages: Message[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-4">
      {messages.map((m) => (
        <div
          key={m.id}
          className={cn(
            "flex",
            m.sender === "CUSTOMER" ? "justify-end" : "justify-start",
          )}
        >
          <div
            className={cn(
              "max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm",
              m.sender === "CUSTOMER" && "bg-slate-900 text-white",
              m.sender === "AGENT" &&
                !m.failed &&
                "bg-white text-slate-900 shadow",
              m.sender === "SYSTEM" && "bg-amber-100 text-amber-900",
              m.failed && "bg-red-100 text-red-700",
            )}
          >
            {m.pending ? (
              <span className="inline-flex items-center gap-2 text-slate-500">
                <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" />
                The agent is reviewing your application — this can take a few
                minutes.
              </span>
            ) : (
              m.body
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
