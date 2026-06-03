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
    <div className="mx-auto flex h-full max-w-2xl flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <div className="font-medium">{name}</div>
          <div className="text-xs text-slate-400">
            {connected ? "connected" : "connecting…"}
          </div>
        </div>
        <Button variant="ghost" onClick={logout}>
          Log out
        </Button>
      </header>
      <MessageList messages={messages} />
      <Composer disabled={sending} onSend={send} />
    </div>
  );
}
