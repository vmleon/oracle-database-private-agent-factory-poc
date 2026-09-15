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
      onLoggedOut={() => setSession(null)}
    />
  );
}

export default function App() {
  return (
    <div className="flex h-full flex-col bg-slate-100">
      <header className="bg-blue-600">
        <div className="mx-auto max-w-2xl px-8 py-4 text-lg font-semibold tracking-tight text-white">
          Loan Assistant
        </div>
      </header>
      <main className="min-h-0 flex-1 p-4">
        <CustomerApp />
      </main>
    </div>
  );
}
