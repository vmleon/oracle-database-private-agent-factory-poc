import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Shape of the agent evidence packet (every field optional — it varies per run). */
interface Evidence {
  reason_codes?: string[];
  application_id?: number;
  required_documents?: {
    required?: string[];
    amount_band?: string;
    rationale?: string;
  };
  verify_employer?: {
    name?: string;
    registered?: boolean;
    trading_status?: string;
    sector?: string;
    registered_address?: string;
    last_filed_year?: number;
  };
  customer?: {
    id?: number;
    name?: string;
    age_years?: number;
    residency?: string;
    kyc_status?: string;
    kyc_age_days?: number;
    kyc_stale?: boolean;
  };
  application?: {
    id?: number;
    status?: string;
    amount_requested?: number;
    term_months?: number;
    purpose?: string;
    missing?: string[];
  };
  profile?: {
    employment_type?: string;
    employer_name?: string;
    monthly_salary?: number;
    income_stale?: boolean;
  };
  credit?: { score?: number };
  facilities?: { existing_monthly_debt?: number };
  derived?: { monthly_payment?: number; pti?: number; dti?: number };
}

type Tone = "good" | "warn" | "bad" | "neutral";

const badgeTone: Record<Tone, string> = {
  good: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-700",
  bad: "bg-rose-100 text-rose-700",
  neutral: "bg-slate-100 text-slate-600",
};

const valueTone: Record<Tone, string> = {
  good: "text-emerald-600",
  warn: "text-amber-600",
  bad: "text-rose-600",
  neutral: "text-slate-900",
};

// Thresholds mirror APP.system_config for display colouring only — they do not
// re-decide anything (the agent already produced the recommendation tier).
const SCORE_CAUTION = 670;
const SCORE_FLOOR = 600;
const DTI_CAP = 0.45;
const PTI_CAP = 0.25;

export const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
const pct = (n: number) => `${Math.round(n * 100)}%`;

const scoreTone = (s: number): Tone =>
  s >= SCORE_CAUTION ? "good" : s >= SCORE_FLOOR ? "warn" : "bad";
const ratioTone = (v: number, cap: number): Tone => (v <= cap ? "good" : "bad");
const kycTone = (status: string, stale?: boolean): Tone =>
  status !== "PASSED" ? "bad" : stale ? "warn" : "good";
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

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </div>
      <div className={cn("mt-1 text-lg font-semibold", valueTone[tone])}>
        {value}
      </div>
    </div>
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

  const {
    credit,
    derived,
    application,
    profile,
    customer,
    verify_employer,
    required_documents,
    facilities,
    reason_codes,
  } = e;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {credit?.score != null && (
          <Stat
            label="Credit score"
            value={credit.score}
            tone={scoreTone(credit.score)}
          />
        )}
        {derived?.dti != null && (
          <Stat
            label="DTI"
            value={pct(derived.dti)}
            tone={ratioTone(derived.dti, DTI_CAP)}
          />
        )}
        {derived?.pti != null && (
          <Stat
            label="PTI"
            value={pct(derived.pti)}
            tone={ratioTone(derived.pti, PTI_CAP)}
          />
        )}
        {derived?.monthly_payment != null && (
          <Stat label="Monthly payment" value={money(derived.monthly_payment)} />
        )}
        {application?.amount_requested != null && (
          <Stat label="Loan amount" value={money(application.amount_requested)} />
        )}
        {application?.term_months != null && (
          <Stat label="Term" value={`${application.term_months} mo`} />
        )}
        {profile?.monthly_salary != null && (
          <Stat label="Monthly salary" value={money(profile.monthly_salary)} />
        )}
        {facilities?.existing_monthly_debt != null && (
          <Stat
            label="Existing debt"
            value={money(facilities.existing_monthly_debt)}
          />
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {customer?.kyc_status && (
          <Badge tone={kycTone(customer.kyc_status, customer.kyc_stale)}>
            KYC {customer.kyc_status}
            {customer.kyc_stale ? " · stale" : ""}
          </Badge>
        )}
        {verify_employer && (verify_employer.name || verify_employer.trading_status) && (
          <Badge
            tone={employerTone(
              verify_employer.registered,
              verify_employer.trading_status,
            )}
          >
            {verify_employer.name ?? "Employer"}
            {verify_employer.trading_status
              ? ` · ${verify_employer.trading_status}`
              : ""}
            {verify_employer.registered === false ? " · unregistered" : ""}
          </Badge>
        )}
        {profile?.income_stale != null && (
          <Badge tone={profile.income_stale ? "warn" : "good"}>
            Income {profile.income_stale ? "stale" : "current"}
          </Badge>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {customer && (
          <Card title="Applicant">
            <Field label="Name" value={customer.name} />
            <Field
              label="Age"
              value={customer.age_years != null ? `${customer.age_years}` : undefined}
            />
            <Field label="Residency" value={customer.residency} />
            <Field label="Employment" value={profile?.employment_type} />
            <Field label="Employer" value={profile?.employer_name} />
            <Field
              label="KYC age"
              value={
                customer.kyc_age_days != null
                  ? `${customer.kyc_age_days} d`
                  : undefined
              }
            />
          </Card>
        )}
        {application && (
          <Card title="Application">
            <Field label="Status" value={application.status} />
            <Field label="Purpose" value={application.purpose} />
            <Field
              label="Amount"
              value={
                application.amount_requested != null
                  ? money(application.amount_requested)
                  : undefined
              }
            />
            <Field
              label="Term"
              value={
                application.term_months != null
                  ? `${application.term_months} months`
                  : undefined
              }
            />
            <Field
              label="Missing docs"
              value={
                application.missing && application.missing.length
                  ? application.missing.join(", ")
                  : "none"
              }
            />
          </Card>
        )}
      </div>

      {required_documents?.required?.length ? (
        <Card
          title={`Required documents${
            required_documents.amount_band
              ? ` · ${required_documents.amount_band} band`
              : ""
          }`}
        >
          <div className="flex flex-wrap gap-2">
            {required_documents.required.map((d) => (
              <Chip key={d}>{d}</Chip>
            ))}
          </div>
          {required_documents.rationale && (
            <p className="mt-2 text-xs text-slate-500">
              {required_documents.rationale}
            </p>
          )}
        </Card>
      ) : null}

      <Card title="Reason codes">
        {reason_codes && reason_codes.length ? (
          <div className="flex flex-wrap gap-2">
            {reason_codes.map((r) => (
              <Chip key={r}>{r}</Chip>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">None</p>
        )}
      </Card>
    </div>
  );
}
