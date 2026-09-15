import { useEffect, useState } from "react";
import { listCustomers, login, type Customer, type LoginResponse } from "@/api";
import { Button } from "@/components/ui/button";

const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{value}</span>
    </div>
  );
}

/** What the customer walks into: an application to talk about, or intake. */
function Context({ c }: { c: Customer }) {
  return (
    <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Before you sign in
      </h2>
      {c.hasOpenApplication ? (
        <>
          <Row
            label="Application"
            value={`#${c.applicationId} · ${c.applicationStatus}`}
          />
          <Row label="Product" value={c.productType} />
          <Row
            label="Asking for"
            value={
              c.amountRequested === null
                ? "—"
                : `${money(c.amountRequested)} over ${c.termMonths} months`
            }
          />
          {c.purpose && <Row label="Purpose" value={c.purpose} />}
        </>
      ) : (
        <p className="py-1 text-sm text-slate-600">
          No open application — the agent will collect one from scratch.
        </p>
      )}
      <Row
        label="Conversation"
        value={
          c.messageCount > 0
            ? `${c.messageCount} message${c.messageCount === 1 ? "" : "s"} — resumes`
            : "none yet"
        }
      />
      <Row
        label="Review"
        value={c.reviewState ? `task ${c.reviewState}` : "nothing filed yet"}
      />
    </div>
  );
}

export function Login({
  onLoggedIn,
}: {
  onLoggedIn: (session: LoginResponse, customer: Customer) => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listCustomers()
      .then(setCustomers)
      .catch(() =>
        setError("Could not load customers. Is the backend running?"),
      );
  }, []);

  const selected = customers.find((c) => c.customerId === selectedId) ?? null;

  const signIn = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      onLoggedIn(await login(selected.customerId), selected);
    } catch {
      setError("Login failed. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md p-8">
      <h1 className="mb-1 text-2xl font-semibold">Loan Assistant</h1>
      <p className="mb-6 text-sm text-slate-500">
        Pick a customer to sign in as.
      </p>
      {error && (
        <p className="mb-4 rounded bg-red-100 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <label
        htmlFor="customer"
        className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400"
      >
        Customer
      </label>
      <select
        id="customer"
        value={selectedId ?? ""}
        disabled={busy || customers.length === 0}
        onChange={(e) =>
          setSelectedId(e.target.value === "" ? null : Number(e.target.value))
        }
        className="mb-4 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm disabled:opacity-50"
      >
        <option value="">
          {customers.length === 0 ? "Loading…" : "Select a customer…"}
        </option>
        {customers.map((c) => (
          <option key={c.customerId} value={c.customerId}>
            {c.name}
            {c.hasOpenApplication ? "" : " (no application)"}
          </option>
        ))}
      </select>

      {selected && <Context c={selected} />}

      <Button
        onClick={signIn}
        disabled={!selected || busy}
        className="w-full py-3"
      >
        {busy ? "Signing in…" : "Log in"}
      </Button>
    </div>
  );
}
