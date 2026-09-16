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
  /** Compliance packages, evaluated as evidence — none of them moves the tier. */
  kyc?: ComplianceResult;
  aml?: ComplianceResult;
}

interface ComplianceResult {
  allow?: boolean;
  deny?: string[];
  warn?: string[];
}

type Tone = "good" | "warn" | "bad" | "neutral";

const badgeTone: Record<Tone, string> = {
  good: "bg-approve/15 text-approve",
  warn: "bg-review/15 text-review",
  bad: "bg-decline/15 text-decline",
  neutral: "bg-paper/10 text-ink-mute",
};

/** The queue rail carries the recommendation as a dot rather than a badge —
 *  a list of badges competes with itself. */
export const outcomeDot = (rec: string) =>
  rec === "APPROVE"
    ? "bg-approve"
    : rec === "DECLINE"
      ? "bg-decline"
      : "bg-review";

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
      <span className="text-ink-mute">{label}</span>
      <span className="text-right font-medium text-paper">{value}</span>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-card border border-ink-hair bg-ink-raised p-4">
      <h3 className="mb-2 text-xs font-semibold text-ink-mute">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-ink px-2 py-0.5 text-xs font-medium text-ink-mute">
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
      <pre className="overflow-x-auto rounded-card border border-ink-hair bg-ink p-3 text-xs">
        {raw}
      </pre>
    );
  }

  const { employer, documents, reason_codes, kyc, aml } = e;

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
          <p className="text-sm text-ink-mute">Not checked.</p>
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
          <p className="text-sm text-ink-mute">None.</p>
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
          <p className="text-sm text-ink-mute">None.</p>
        )}
      </Card>

      <Compliance title="KYC" result={kyc} />
      <Compliance title="Sanctions and AML" result={aml} />
    </div>
  );
}

/** A compliance package's findings. Read before the decision, and never part of
 *  it — the tier is eligibility plus the employer record and nothing else. */
function Compliance({ title, result }: { title: string; result?: ComplianceResult }) {
  if (!result) {
    return (
      <Card title={title}>
        <p className="text-sm text-ink-mute">Not checked on this run.</p>
      </Card>
    );
  }

  const deny = result.deny ?? [];
  const warn = result.warn ?? [];
  const tone: Tone = deny.length ? "bad" : warn.length ? "warn" : "good";

  return (
    <Card title={title}>
      <div className="mb-2">
        <Badge tone={tone}>
          {deny.length ? "Finding" : warn.length ? "Needs a look" : "Clear"}
        </Badge>
      </div>
      {deny.length === 0 && warn.length === 0 ? (
        <p className="text-sm text-ink-mute">Nothing raised.</p>
      ) : (
        <ul className="space-y-1">
          {[...deny, ...warn].map((m) => (
            <li key={m} className="text-sm leading-relaxed text-paper">
              {m}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
