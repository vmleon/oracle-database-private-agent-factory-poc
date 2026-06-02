# Chat UI (React + Vite) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser chat UI for the loan assistant: pick a customer to log in, chat (each turn shows a multi-minute "thinking" state and the reply arrives via SSE), replay history on reload, and log out (revoking the session server-side).

**Architecture:** A Vite + React + TypeScript single-page app under `src/frontend`. It calls the existing backend through a Vite dev proxy (`/v1` → `http://localhost:8090`). State lives in one `useReducer` hook. The async reply is delivered on a per-session SSE channel opened with the browser's native `EventSource`.

**Tech Stack:** Vite 5, React 18, TypeScript 5, Tailwind CSS 3 (+ a couple of shadcn-style primitives), Vitest for the reducer unit tests.

**Backend it talks to (already implemented + merged on `main`):**

- `GET /v1/customers` → `[{customerId, name, applicationId, productType, amountRequested, termMonths, hasOpenApplication}]`
- `POST /v1/login {customerId}` → `{sessionToken, customerId, applicationId, roomId}`
- `POST /v1/chat {message}` (header `X-Session-Token`) → **`202` `{turnId}`**
- `GET /v1/chat/stream?token=<sessionToken>` → SSE; events: `agent` `{turnId, reply, pafRoomId}`, `error` `{turnId, message}`
- `GET /v1/chat/history` (header `X-Session-Token`) → `[{sender, body, createdAt}]`
- `POST /v1/logout` (header `X-Session-Token`) → `204`

**Spec:** `docs/superpowers/specs/2026-06-02-chat-ui-async-sse-design.md` (frontend portions).

**Prereqs:** Node 18+ and npm available. The backend stack is up (`http://localhost:8090`).

---

## File Structure (all under `src/frontend/`)

- `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `index.html` — project + dev proxy + Vitest config.
- `tailwind.config.js`, `postcss.config.js`, `src/index.css` — Tailwind.
- `src/main.tsx`, `src/vite-env.d.ts` — entry.
- `src/lib/utils.ts` — `cn()` class-merge helper (shadcn convention).
- `src/components/ui/button.tsx` — one shadcn-style primitive (the rest is Tailwind on plain elements).
- `src/api.ts` — typed REST + SSE client.
- `src/chatState.ts` — pure reducer + types + actions (unit-tested).
- `src/useChat.ts` — the hook wiring reducer + api + EventSource.
- `src/components/Login.tsx`, `src/components/Chat.tsx`, `src/components/Composer.tsx`, `src/components/MessageList.tsx` — views.
- `src/App.tsx` — view switch (login ↔ chat).
- `src/chatState.test.ts` — Vitest reducer tests.

> **shadcn note:** we do NOT run the interactive `shadcn` CLI (non-deterministic). shadcn components are copy-paste Tailwind components anyway; we hand-add a `Button` primitive and the `cn` helper and style the rest with Tailwind directly. This satisfies the "component-library assisted" decision deterministically.

> **SSE `error` gotcha (important for Task 4):** the browser's `EventSource` fires its OWN `error` event on connection trouble, AND delivers our server-sent `event: error` to the same `addEventListener('error', …)`. Distinguish them by payload: a server turn-error is a `MessageEvent` with `.data` (JSON); a connection error has no `.data`. The reducer only acts on the `.data` form.

---

### Task 1: Scaffold Vite + React + TS + Tailwind + dev proxy

**Files (create all):** `src/frontend/package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `index.html`, `tailwind.config.js`, `postcss.config.js`, `src/index.css`, `src/main.tsx`, `src/vite-env.d.ts`, `src/App.tsx` (placeholder).

- [ ] **Step 1: Create `src/frontend/package.json`**

```json
{
  "name": "chat-ui",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "clsx": "^2.1.1",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "tailwind-merge": "^2.5.4"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4"
  }
}
```

- [ ] **Step 2: Create `src/frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend chat turn runs for minutes; the SSE stream can sit silent between
// "open" and the "agent" event, so the proxy read timeout must exceed a turn.
const TEN_MIN = 600_000;

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": {
        target: "http://localhost:8090",
        changeOrigin: true,
        timeout: TEN_MIN,
        proxyTimeout: TEN_MIN,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
```

- [ ] **Step 3: Create `src/frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create `src/frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create `src/frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Loan Assistant</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `src/frontend/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 7: Create `src/frontend/postcss.config.js`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 8: Create `src/frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html,
body,
#root {
  height: 100%;
}
body {
  @apply bg-slate-100 text-slate-900;
}
```

- [ ] **Step 9: Create `src/frontend/src/vite-env.d.ts`**

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 10: Create `src/frontend/src/App.tsx` (placeholder for now)**

```tsx
export default function App() {
  return <div className="p-8 text-lg">Loan Assistant — UI scaffold</div>;
}
```

- [ ] **Step 11: Create `src/frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 12: Install and build**

Run:

```bash
cd src/frontend && npm install && npm run build
```

Expected: `npm install` succeeds; `npm run build` completes with no TypeScript errors and emits `dist/`.

- [ ] **Step 13: Add a `.gitignore` for node_modules/dist and commit**

Create `src/frontend/.gitignore`:

```
node_modules
dist
```

```bash
cd /Users/vmartina/Documents/ws/oracle-database-private-agent-factory-poc
git add src/frontend/.gitignore src/frontend/package.json src/frontend/package-lock.json \
        src/frontend/vite.config.ts src/frontend/tsconfig.json src/frontend/tsconfig.node.json \
        src/frontend/index.html src/frontend/tailwind.config.js src/frontend/postcss.config.js \
        src/frontend/src/index.css src/frontend/src/main.tsx src/frontend/src/vite-env.d.ts \
        src/frontend/src/App.tsx
git commit -m "feat(ui): scaffold Vite React+TS app with Tailwind and dev proxy"
```

---

### Task 2: API client (`api.ts`) + `cn` helper + Button

**Files:** Create `src/frontend/src/lib/utils.ts`, `src/frontend/src/components/ui/button.tsx`, `src/frontend/src/api.ts`.

- [ ] **Step 1: Create `src/frontend/src/lib/utils.ts`**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 2: Create `src/frontend/src/components/ui/button.tsx`**

```tsx
import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost";

export function Button({
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none",
        variant === "primary" && "bg-slate-900 text-white hover:bg-slate-700",
        variant === "ghost" &&
          "bg-transparent text-slate-700 hover:bg-slate-200",
        className,
      )}
      {...props}
    />
  );
}
```

- [ ] **Step 3: Create `src/frontend/src/api.ts`**

```ts
export interface Customer {
  customerId: number;
  name: string;
  applicationId: number | null;
  productType: string | null;
  amountRequested: number | null;
  termMonths: number | null;
  hasOpenApplication: boolean;
}

export interface LoginResponse {
  sessionToken: string;
  customerId: number;
  applicationId: number | null;
  roomId: string;
}

export interface HistoryMessage {
  sender: "CUSTOMER" | "AGENT" | "SYSTEM";
  body: string;
  createdAt: string | null;
}

export interface AgentEvent {
  turnId: string;
  reply: string;
  pafRoomId: string | null;
}

export interface TurnErrorEvent {
  turnId: string;
  message: string;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function listCustomers(): Promise<Customer[]> {
  return fetch("/v1/customers").then((r) => json<Customer[]>(r));
}

export function login(customerId: number): Promise<LoginResponse> {
  return fetch("/v1/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customerId }),
  }).then((r) => json<LoginResponse>(r));
}

export function getHistory(token: string): Promise<HistoryMessage[]> {
  return fetch("/v1/chat/history", {
    headers: { "X-Session-Token": token },
  }).then((r) => json<HistoryMessage[]>(r));
}

/** Returns the turnId; the reply arrives later on the SSE channel. */
export function sendChat(
  token: string,
  message: string,
): Promise<{ turnId: string }> {
  return fetch("/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-Token": token },
    body: JSON.stringify({ message }),
  }).then((r) => json<{ turnId: string }>(r));
}

/** Best-effort: resolves even if the call fails. */
export async function logout(token: string): Promise<void> {
  try {
    await fetch("/v1/logout", {
      method: "POST",
      headers: { "X-Session-Token": token },
    });
  } catch {
    // ignore — logout is best-effort; the UI logs out regardless
  }
}

export interface StreamHandlers {
  onAgent: (e: AgentEvent) => void;
  onTurnError: (e: TurnErrorEvent) => void;
  onOpen: () => void;
}

/** Open the per-session SSE channel. Native EventSource can't set headers, so the
 *  token rides as a query param (PoC tradeoff — see the design spec). */
export function openStream(
  token: string,
  handlers: StreamHandlers,
): EventSource {
  const es = new EventSource(
    `/v1/chat/stream?token=${encodeURIComponent(token)}`,
  );
  es.addEventListener("open", () => handlers.onOpen());
  es.addEventListener("agent", (ev) => {
    handlers.onAgent(JSON.parse((ev as MessageEvent).data) as AgentEvent);
  });
  // NOTE: the browser also fires 'error' on connection trouble — those have no .data.
  // Only a server-sent turn error is a MessageEvent with .data.
  es.addEventListener("error", (ev) => {
    const data = (ev as MessageEvent).data;
    if (typeof data === "string" && data.length > 0) {
      handlers.onTurnError(JSON.parse(data) as TurnErrorEvent);
    }
    // else: connection blip; EventSource auto-reconnects and will fire 'open' again.
  });
  return es;
}
```

- [ ] **Step 4: Type-check**

Run: `cd src/frontend && npx tsc -b`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/lib/utils.ts src/frontend/src/components/ui/button.tsx src/frontend/src/api.ts
git commit -m "feat(ui): typed REST + SSE api client and Button primitive"
```

---

### Task 3: Chat state — pure reducer + types (`chatState.ts`) + tests

**Files:** Create `src/frontend/src/chatState.ts` and `src/frontend/src/chatState.test.ts`.

- [ ] **Step 1: Write the failing test — `src/frontend/src/chatState.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { chatReducer, initialChatState, type ChatState } from "./chatState";

function withPendingTurn(): { state: ChatState; turnId: string } {
  const start = chatReducer(initialChatState, {
    type: "send",
    text: "hello",
    turnId: "t1",
  });
  return { state: start, turnId: "t1" };
}

describe("chatReducer", () => {
  it("send adds a user bubble and a pending agent placeholder", () => {
    const { state } = withPendingTurn();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      sender: "CUSTOMER",
      body: "hello",
    });
    expect(state.messages[1]).toMatchObject({
      sender: "AGENT",
      pending: true,
      turnId: "t1",
    });
    expect(state.sending).toBe(true);
  });

  it("agent event replaces the matching pending placeholder with the reply", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "agent",
      event: { turnId: "t1", reply: "Looks strong", pafRoomId: "r1" },
    });
    expect(next.messages).toHaveLength(2);
    expect(next.messages[1]).toMatchObject({
      sender: "AGENT",
      body: "Looks strong",
      pending: false,
    });
    expect(next.sending).toBe(false);
  });

  it("turn error marks the pending placeholder as failed and re-enables sending", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "turnError",
      event: { turnId: "t1", message: "boom" },
    });
    expect(next.messages[1]).toMatchObject({
      sender: "AGENT",
      failed: true,
      pending: false,
    });
    expect(next.sending).toBe(false);
  });

  it("ignores an agent event whose turnId does not match a pending turn", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "agent",
      event: { turnId: "other", reply: "nope", pafRoomId: null },
    });
    expect(next).toEqual(state);
  });

  it("history replaces messages (used on load and SSE reconnect)", () => {
    const { state } = withPendingTurn();
    const next = chatReducer(state, {
      type: "history",
      messages: [
        { sender: "CUSTOMER", body: "old q", createdAt: null },
        { sender: "AGENT", body: "old a", createdAt: null },
      ],
    });
    expect(next.messages).toHaveLength(2);
    expect(next.messages[0]).toMatchObject({
      sender: "CUSTOMER",
      body: "old q",
      pending: false,
    });
    // a still-pending turn is preserved after history reconciliation
    const pendingPreserved = chatReducer(
      chatReducer(initialChatState, { type: "send", text: "q2", turnId: "t2" }),
      {
        type: "history",
        messages: [{ sender: "CUSTOMER", body: "old q", createdAt: null }],
      },
    );
    expect(pendingPreserved.messages.some((m) => m.pending)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src/frontend && npm run test`
Expected: FAIL — `chatState` module not found.

- [ ] **Step 3: Implement `src/frontend/src/chatState.ts`**

```ts
import type { AgentEvent, HistoryMessage, TurnErrorEvent } from "./api";

export interface Message {
  id: string;
  sender: "CUSTOMER" | "AGENT" | "SYSTEM";
  body: string;
  pending: boolean;
  failed: boolean;
  turnId?: string;
}

export interface ChatState {
  messages: Message[];
  sending: boolean;
  seq: number; // monotonic id source for message keys
}

export const initialChatState: ChatState = {
  messages: [],
  sending: false,
  seq: 0,
};

export type ChatAction =
  | { type: "send"; text: string; turnId: string }
  | { type: "agent"; event: AgentEvent }
  | { type: "turnError"; event: TurnErrorEvent }
  | { type: "history"; messages: HistoryMessage[] };

export function chatReducer(
  state: ChatState,
  action: ChatState extends never ? never : ChatAction,
): ChatState {
  switch (action.type) {
    case "send": {
      const userMsg: Message = {
        id: `m${state.seq}`,
        sender: "CUSTOMER",
        body: action.text,
        pending: false,
        failed: false,
      };
      const placeholder: Message = {
        id: `m${state.seq + 1}`,
        sender: "AGENT",
        body: "",
        pending: true,
        failed: false,
        turnId: action.turnId,
      };
      return {
        messages: [...state.messages, userMsg, placeholder],
        sending: true,
        seq: state.seq + 2,
      };
    }
    case "agent": {
      const idx = state.messages.findIndex(
        (m) => m.pending && m.turnId === action.event.turnId,
      );
      if (idx === -1) return state;
      const messages = state.messages.slice();
      messages[idx] = {
        ...messages[idx],
        body: action.event.reply,
        pending: false,
      };
      return { ...state, messages, sending: false };
    }
    case "turnError": {
      const idx = state.messages.findIndex(
        (m) => m.pending && m.turnId === action.event.turnId,
      );
      if (idx === -1) return state;
      const messages = state.messages.slice();
      messages[idx] = {
        ...messages[idx],
        body: "We couldn't get a response. Please try again.",
        pending: false,
        failed: true,
      };
      return { ...state, messages, sending: false };
    }
    case "history": {
      // Replace the persisted history, but keep any still-pending turn appended so a
      // reconnect mid-turn doesn't drop the in-flight placeholder.
      const pending = state.messages.filter((m) => m.pending);
      let seq = 0;
      const replayed: Message[] = action.messages.map((h) => ({
        id: `m${seq++}`,
        sender: h.sender,
        body: h.body,
        pending: false,
        failed: false,
      }));
      const pendingReindexed = pending.map((m) => ({ ...m, id: `m${seq++}` }));
      return {
        messages: [...replayed, ...pendingReindexed],
        sending: pending.length > 0,
        seq,
      };
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd src/frontend && npm run test`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/frontend/src/chatState.ts src/frontend/src/chatState.test.ts
git commit -m "feat(ui): chat state reducer with pending-turn handling + tests"
```

---

### Task 4: `useChat` hook (reducer + api + EventSource)

**Files:** Create `src/frontend/src/useChat.ts`.

- [ ] **Step 1: Implement `src/frontend/src/useChat.ts`**

```ts
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getHistory, logout as apiLogout, openStream, sendChat } from "./api";
import { chatReducer, initialChatState } from "./chatState";

export interface Session {
  token: string;
  customerId: number;
  roomId: string;
}

export function useChat(session: Session, onLoggedOut: () => void) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadHistory = () => {
      getHistory(session.token)
        .then((msgs) => {
          if (!cancelled) dispatch({ type: "history", messages: msgs });
        })
        .catch(() => {
          /* history is best-effort; SSE still delivers live replies */
        });
    };

    const es = openStream(session.token, {
      onOpen: () => {
        setConnected(true);
        loadHistory(); // reconcile on first open AND on every reconnect
      },
      onAgent: (e) => dispatch({ type: "agent", event: e }),
      onTurnError: (e) => dispatch({ type: "turnError", event: e }),
    });
    esRef.current = es;

    return () => {
      cancelled = true;
      es.close();
      esRef.current = null;
    };
  }, [session.token]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || state.sending) return;
      try {
        const { turnId } = await sendChat(session.token, trimmed);
        dispatch({ type: "send", text: trimmed, turnId });
      } catch {
        // 401 (expired/revoked) or network — log the user out.
        doLogout();
      }
    },
    [session.token, state.sending],
  );

  const doLogout = useCallback(async () => {
    esRef.current?.close();
    esRef.current = null;
    await apiLogout(session.token);
    sessionStorage.removeItem("session");
    onLoggedOut();
  }, [session.token, onLoggedOut]);

  return {
    messages: state.messages,
    sending: state.sending,
    connected,
    send,
    logout: doLogout,
  };
}
```

> Note: `send` calls the backend first to get the real `turnId`, then dispatches `send` so the placeholder is keyed by the server's `turnId` (which the SSE `agent` event references). `POST /v1/chat` returns `202` in milliseconds now, so this is effectively instant.

- [ ] **Step 2: Type-check**

Run: `cd src/frontend && npx tsc -b`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/frontend/src/useChat.ts
git commit -m "feat(ui): useChat hook wiring SSE, send, logout"
```

---

### Task 5: Views — Login, Chat, MessageList, Composer + App wiring

**Files:** Create `src/frontend/src/components/Login.tsx`, `MessageList.tsx`, `Composer.tsx`, `Chat.tsx`; rewrite `src/frontend/src/App.tsx`.

- [ ] **Step 1: Create `src/frontend/src/components/Login.tsx`**

```tsx
import { useEffect, useState } from "react";
import { listCustomers, login, type Customer, type LoginResponse } from "@/api";
import { Button } from "@/components/ui/button";

export function Login({
  onLoggedIn,
}: {
  onLoggedIn: (s: LoginResponse) => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    listCustomers()
      .then(setCustomers)
      .catch(() =>
        setError("Could not load customers. Is the backend running?"),
      );
  }, []);

  const pick = async (c: Customer) => {
    setBusy(c.customerId);
    setError(null);
    try {
      onLoggedIn(await login(c.customerId));
    } catch {
      setError("Login failed. Try again.");
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-md p-8">
      <h1 className="mb-1 text-2xl font-semibold">Loan Assistant</h1>
      <p className="mb-6 text-sm text-slate-500">
        Choose a customer to start a chat.
      </p>
      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      <ul className="space-y-2">
        {customers.map((c) => (
          <li key={c.customerId}>
            <button
              onClick={() => pick(c)}
              disabled={busy !== null}
              className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-left hover:border-slate-400 disabled:opacity-50"
            >
              <span>
                <span className="font-medium">{c.name}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {c.hasOpenApplication
                    ? `${c.productType} · ${c.amountRequested}`
                    : "no application"}
                </span>
              </span>
              <span className="text-sm text-slate-400">
                {busy === c.customerId ? "…" : "→"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Create `src/frontend/src/components/MessageList.tsx`**

```tsx
import { useEffect, useRef } from "react";
import type { Message } from "@/chatState";
import { cn } from "@/lib/utils";

export function MessageList({ messages }: { messages: Message[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex-1 space-y-3 overflow-y-auto p-4">
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
```

- [ ] **Step 3: Create `src/frontend/src/components/Composer.tsx`**

```tsx
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <form
      onSubmit={submit}
      className="flex gap-2 border-t border-slate-200 bg-white p-3"
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        placeholder={disabled ? "Waiting for the agent…" : "Type a message…"}
        className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100"
      />
      <Button type="submit" disabled={disabled || !text.trim()}>
        Send
      </Button>
    </form>
  );
}
```

- [ ] **Step 4: Create `src/frontend/src/components/Chat.tsx`**

```tsx
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
```

- [ ] **Step 5: Rewrite `src/frontend/src/App.tsx`**

```tsx
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

export default function App() {
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
```

- [ ] **Step 6: Type-check + build + run reducer tests**

Run:

```bash
cd src/frontend && npx tsc -b && npm run build && npm run test
```

Expected: tsc clean, build emits `dist/`, 5 reducer tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/frontend/src/components/Login.tsx src/frontend/src/components/MessageList.tsx \
        src/frontend/src/components/Composer.tsx src/frontend/src/components/Chat.tsx \
        src/frontend/src/App.tsx
git commit -m "feat(ui): login picker, chat view, composer, thinking + logout"
```

---

### Task 6: Manual end-to-end verification

No code. Confirms the UI works against the live backend.

- [ ] **Step 1: Ensure the backend stack is up**

```bash
curl -s -m 10 http://localhost:8090/actuator/health; echo
```

Expected: `{"status":"UP"}`. (If not, bring the stack up per the project's run docs.)

- [ ] **Step 2: Start the Vite dev server**

```bash
cd src/frontend && npm run dev
```

Expected: Vite prints a local URL (typically `http://localhost:5173`).

- [ ] **Step 3: Drive the UI in a browser** (manually, or with the project's browser tooling)

1. Open the dev URL → the **login picker** lists seeded customers.
2. Click **Alice** → lands in the chat view; header shows "connected" once the SSE opens.
3. Type "What is the status of my loan application?" and Send → your message appears, the input disables, and the **"agent is reviewing…"** indicator shows.
4. After ~3–4 minutes the indicator is replaced by the agent reply (delivered via SSE).
5. **Reload** the page → you stay logged in (sessionStorage) and the conversation replays from history.
6. Click **Log out** → returns to the picker.
7. Confirm revocation: the old token no longer works (a manual `curl` chat with the old token returns `401`), proving server-side logout.

- [ ] **Step 4: Done**

No commit (verification only). If anything fails, fix the relevant task.

---

## Self-review notes

- **Spec coverage:** customer-picker login (Task 5), `sessionStorage` persistence (Task 5), SSE channel via `?token=` (Task 2/4), optimistic send + `turnId`-keyed pending placeholder (Task 3/4), multi-minute "thinking" indicator (Task 5), `agent`/`error` event handling incl. the EventSource `error` collision (Task 2/3), history replay on load + on SSE reconnect (Task 4), best-effort logout + server revocation (Task 2/4/5), error→login on 401 (Task 4), Tailwind + shadcn-style components (Tasks 1/2/5), dev proxy with long SSE timeout (Task 1).
- **Out of scope:** production CORS/static serving, HITL `SYSTEM` push (backend path exists, no UI trigger), multi-conversation, rich design polish, automated browser tests (manual e2e only — reducer logic is unit-tested).
- **Type consistency:** `Session{token,customerId,roomId}`, `Message{id,sender,body,pending,failed,turnId?}`, actions `send|agent|turnError|history`, api fns `listCustomers/login/getHistory/sendChat/logout/openStream`, SSE handlers `onAgent/onTurnError/onOpen` — consistent across api.ts, chatState.ts, useChat.ts, components.
- **Known PoC trade-off:** the chat header shows `Customer <id>` rather than the name (the login response has no name; the picker has it). If the name matters, a later tweak can pass it from the picker through `sessionStorage`. Flagged, not blocking.
