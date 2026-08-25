import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Shape of the agent evidence packet (every field optional — it varies per run). */
interface Evidence {
  reason_codes?: string[];
  documents?: string[];
  employer?: {
    name?: string;
    registered?: boolean;
    trading_status?: string;
    sector?: string;
    registered_address?: string;
    last_filed_year?: number;
  };
}

type Tone = "good" | "warn" | "bad" | "neutral";

const badgeTone: Record<Tone, string> = {
  good: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-700",
  bad: "bg-rose-100 text-rose-700",
  neutral: "bg-slate-100 text-slate-600",
};

export const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });

const employerTone = (registered?: boolean, status?: string): Tone => {
  if (registered === false) return "bad";
  if (status === "active") return "good";
  if (status === "dormant") return "warn";
  return "neutral";
};

/** Recommendation-tier colour, reused by the task header. */
export const recommendationTone = (rec: string): Tone =>
  rec === "APPROVE" ? "good" : rec === "DECLINE" ? "bad" : "warn";

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        badgeTone[tone],
      )}
    >
      {children}
    </span>
  );
}

function Field({ label, value }: { label: string; value?: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-3 py-1 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{value}</span>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      {children}
    </span>
  );
}

export function EvidencePanel({ raw }: { raw: string | null }) {
  if (!raw) return null;

  let e: Evidence | null = null;
  try {
    e = JSON.parse(raw) as Evidence;
  } catch {
    e = null;
  }
  // Unparseable evidence: fall back to the raw text rather than hiding it.
  if (!e || typeof e !== "object") {
    return (
      <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
        {raw}
      </pre>
    );
  }

  const { employer, documents, reason_codes } = e;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <Card title="Employer">
        {employer ? (
          <>
            <div className="mb-2">
              <Badge
                tone={employerTone(employer.registered, employer.trading_status)}
              >
                {employer.registered === false
                  ? "Unregistered"
                  : (employer.trading_status ?? "—")}
              </Badge>
            </div>
            <Field label="Name" value={employer.name} />
            <Field label="Sector" value={employer.sector} />
            <Field label="Address" value={employer.registered_address} />
            <Field label="Last filed" value={employer.last_filed_year} />
          </>
        ) : (
          <p className="text-sm text-slate-400">Not checked.</p>
        )}
      </Card>

      <Card title="Required documents">
        {documents?.length ? (
          <div className="flex flex-wrap gap-2">
            {documents.map((d) => (
              <Chip key={d}>{d}</Chip>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">None.</p>
        )}
      </Card>

      <Card title="Reasons">
        {reason_codes && reason_codes.length ? (
          <div className="flex flex-wrap gap-2">
            {reason_codes.map((r) => (
              <Chip key={r}>{r}</Chip>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">None.</p>
        )}
      </Card>
    </div>
  );
}
