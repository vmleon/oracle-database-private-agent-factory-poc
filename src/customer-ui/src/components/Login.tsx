import { useEffect, useRef, useState } from "react";
import { listCustomers, login, type Customer, type LoginResponse } from "@/api";
import { Button } from "@/components/ui/button";

const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

/** At-a-glance state for whoever is driving the demo: does this customer already
 *  have a thread waiting, or is the row seed data nobody has talked to? */
function Tag({
  tone,
  children,
}: {
  tone: "live" | "review";
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
        tone === "live"
          ? "bg-approve/10 text-approve"
          : "bg-review/10 text-review"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          tone === "live" ? "bg-approve" : "bg-review"
        }`}
      />
      {children}
    </span>
  );
}

const sentence = (s: string | null) =>
  s === null ? "—" : s.charAt(0) + s.slice(1).toLowerCase();

const term = (c: Customer) =>
  c.amountRequested === null
    ? (c.productType ?? "Application open")
    : `${money(c.amountRequested)} over ${c.termMonths} months`;

/** A listbox rather than a <select>: the badges are the reason to open it. */
function CustomerPicker({
  customers,
  selected,
  disabled,
  onSelect,
}: {
  customers: Customer[];
  selected: Customer | null;
  disabled: boolean;
  onSelect: (c: Customer) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 rounded-card border border-paper-hair bg-paper-raised px-4 py-3 text-left disabled:opacity-40"
      >
        <span className="min-w-0">
          <span
            className={`block truncate text-[15px] ${
              selected ? "font-medium text-ink" : "text-graphite"
            }`}
          >
            {selected
              ? selected.name
              : customers.length === 0
                ? "Loading customers"
                : "Choose a customer"}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {selected && selected.messageCount > 0 && (
            <Tag tone="live">Conversation</Tag>
          )}
          {selected?.reviewState && <Tag tone="review">In review</Tag>}
          <svg width="10" height="6" viewBox="0 0 10 6" aria-hidden="true">
            <path
              d={open ? "M0 6 L5 0 L10 6" : "M0 0 L5 6 L10 0"}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="text-graphite"
            />
          </svg>
        </span>
      </button>

      {open && (
        <ul
          role="listbox"
          className="absolute z-10 mt-1 max-h-[22rem] w-full overflow-y-auto rounded-card border border-paper-hair bg-paper-raised py-1 shadow-xl shadow-ink/5"
        >
          {customers.map((c) => (
            <li key={c.customerId}>
              <button
                type="button"
                role="option"
                aria-selected={c.customerId === selected?.customerId}
                onClick={() => {
                  onSelect(c);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-paper"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-ink">
                    {c.name}
                  </span>
                  <span className="block truncate text-xs text-graphite">
                    {c.hasOpenApplication ? term(c) : "No application"}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {c.messageCount > 0 && <Tag tone="live">Conversation</Tag>}
                  {c.reviewState && <Tag tone="review">In review</Tag>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-t border-paper-hair py-2 text-sm">
      <span className="text-graphite">{label}</span>
      <span className="text-right font-medium text-ink">{value}</span>
    </div>
  );
}

/** What the customer walks into: an application to talk about, or intake. */
function Context({ c }: { c: Customer }) {
  return (
    <div className="mt-4 rounded-card border border-paper-hair bg-paper-raised px-4 pb-1 pt-4">
      {c.hasOpenApplication ? (
        <>
          <div className="pb-3">
            <div className="text-[2rem] font-semibold leading-none tracking-tight text-ink">
              {c.amountRequested === null ? "—" : money(c.amountRequested)}
            </div>
            <div className="mt-1.5 text-sm text-graphite">
              over {c.termMonths} months
            </div>
          </div>
          {c.purpose && <Row label="Purpose" value={c.purpose} />}
          <Row label="Application" value={`#${c.applicationId}`} />
          <Row label="Status" value={sentence(c.applicationStatus)} />
        </>
      ) : (
        <p className="pb-3 text-sm leading-relaxed text-graphite">
          Nothing on file. The assistant will start from the beginning and
          collect an application in the conversation.
        </p>
      )}
      <Row
        label="Conversation"
        value={
          c.messageCount > 0
            ? `${c.messageCount} message${c.messageCount === 1 ? "" : "s"} waiting`
            : "Not started"
        }
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
  const [selected, setSelected] = useState<Customer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listCustomers()
      .then(setCustomers)
      .catch(() =>
        setError("The customer list did not load. Check the backend is up."),
      );
  }, []);

  const signIn = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      onLoggedIn(await login(selected.customerId), selected);
    } catch {
      setError("That sign-in did not go through. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">
        Start a conversation
      </h1>
      <p className="mb-6 mt-1 text-sm leading-relaxed text-graphite">
        Sign in as a customer to see what the assistant says to them.
      </p>

      {error && (
        <p className="mb-4 rounded-card border border-decline/20 bg-decline/5 px-4 py-3 text-sm text-decline">
          {error}
        </p>
      )}

      <CustomerPicker
        customers={customers}
        selected={selected}
        disabled={busy || customers.length === 0}
        onSelect={setSelected}
      />

      {selected && <Context c={selected} />}

      <Button
        onClick={signIn}
        disabled={!selected || busy}
        className="mt-5 w-full py-3"
      >
        {busy
          ? "Signing in"
          : selected
            ? `Log in as ${selected.name}`
            : "Log in"}
      </Button>
    </div>
  );
}
