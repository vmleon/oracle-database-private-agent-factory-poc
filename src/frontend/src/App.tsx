import { useState } from "react";
import { Login } from "@/components/Login";
import { Chat } from "@/components/Chat";
import { Backoffice } from "@/components/backoffice/Backoffice";
import { isBackofficePath } from "@/lib/route";
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
        onLoggedIn={(r) => {
          // The customer name isn't in the login response; fetch-free: we only have ids here,
          // so store a friendly fallback. (Name is shown on the picker; header uses room id label.)
          const s: StoredSession = {
            token: r.sessionToken,
            customerId: r.customerId,
            roomId: r.roomId,
            name: `Customer ${r.customerId}`,
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
  if (isBackofficePath(window.location.pathname)) {
    return <Backoffice />;
  }
  return <CustomerApp />;
}
