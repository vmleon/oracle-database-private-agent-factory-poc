import { useEffect, useState } from "react";
import { listCustomers, login, type Customer, type LoginResponse } from "@/api";

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
