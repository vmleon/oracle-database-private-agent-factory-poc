import { useChat, type Session } from "@/useChat";
import { MessageList } from "@/components/MessageList";
import { Composer } from "@/components/Composer";
import { Button } from "@/components/ui/button";

export function Chat({
  session,
  name,
  onLoggedOut,
}: {
  session: Session;
  name: string;
  onLoggedOut: () => void;
}) {
  const { messages, sending, connected, send, logout } = useChat(
    session,
    onLoggedOut,
  );

  return (
    <div className="mx-auto flex h-full w-full max-w-xl flex-col">
      <header className="flex items-center justify-between border-b border-paper-hair px-5 py-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-ink">{name}</div>
          <div className="flex items-center gap-1.5 text-xs text-graphite">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connected ? "bg-approve" : "bg-review"
              }`}
            />
            {connected ? "Connected" : "Connecting"}
          </div>
        </div>
        <Button variant="ghost" onClick={logout}>
          Log out
        </Button>
      </header>
      <MessageList messages={messages} name={name} />
      <Composer disabled={sending} onSend={send} />
    </div>
  );
}
