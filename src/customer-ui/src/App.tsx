import { useState } from "react";
import { Login } from "@/components/Login";
import { Chat } from "@/components/Chat";
import type { Session } from "@/useChat";

interface StoredSession extends Session {
  name: string;
}

function load(): StoredSession | null {
  const raw = sessionStorage.getItem("session");
  return raw ? (JSON.parse(raw) as StoredSession) : null;
}

function CustomerApp() {
  const [session, setSession] = useState<StoredSession | null>(load);

  if (!session) {
    return (
      <Login
        onLoggedIn={(r, customer) => {
          const s: StoredSession = {
            token: r.sessionToken,
            customerId: r.customerId,
            roomId: r.roomId,
            name: customer.name,
          };
          sessionStorage.setItem("session", JSON.stringify(s));
          setSession(s);
        }}
      />
    );
  }

  return (
    <Chat
      session={session}
      name={session.name}
      onLoggedOut={() => {
        sessionStorage.removeItem("session");
        setSession(null);
      }}
    />
  );
}

export default function App() {
  return (
    <div className="flex h-full flex-col bg-paper">
      <header className="border-b border-paper-hair bg-ink">
        <div className="mx-auto flex max-w-2xl flex-wrap items-baseline gap-x-3 gap-y-1 px-6 py-5">
          <span className="text-2xl font-semibold tracking-tight text-paper">
            Loan Assistant
          </span>
          <span className="text-base text-ink-mute">Northbank</span>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <CustomerApp />
      </main>
    </div>
  );
}
