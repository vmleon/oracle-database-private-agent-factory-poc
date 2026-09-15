import { useEffect, useRef } from "react";
import type { Message } from "@/chatState";
import { cn } from "@/lib/utils";

/** An empty thread is the common case on a fresh customer, and a blank panel
 *  cannot be told apart from one that failed to load. Say which it is. */
function Empty({ name }: { name: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <p className="text-sm font-medium text-ink">
        Nothing said yet as {name}
      </p>
      <p className="mt-1 max-w-xs text-sm leading-relaxed text-graphite">
        The assistant replies when you write. Ask about a loan, or say hello to
        get started.
      </p>
    </div>
  );
}

export function MessageList({
  messages,
  name,
}: {
  messages: Message[];
  name: string;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto">
        <Empty name={name} />
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-2.5 overflow-y-auto px-5 py-5">
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
              "max-w-[78%] whitespace-pre-wrap px-4 py-2.5 text-sm leading-relaxed",
              // The two voices differ in shape as well as colour, so the thread
              // is readable without relying on it.
              m.sender === "CUSTOMER" &&
                "rounded-2xl rounded-br-sm bg-ink text-paper",
              m.sender === "AGENT" &&
                !m.failed &&
                "rounded-2xl rounded-bl-sm border border-paper-hair bg-paper-raised text-ink",
              m.sender === "SYSTEM" &&
                "rounded-card bg-review/10 text-[13px] text-review",
              m.failed &&
                "rounded-card border border-decline/20 bg-decline/5 text-decline",
            )}
          >
            {m.pending ? (
              <span className="flex items-center gap-2 text-graphite">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-graphite" />
                Reviewing your application. This can take a few minutes.
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
