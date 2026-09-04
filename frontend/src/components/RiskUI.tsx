import { cn } from "@/lib/utils";
import { RISK_LABEL, type RiskLevel } from "@/data/pilot";
import type { ReactNode } from "react";

const riskClasses: Record<RiskLevel, string> = {
  low: "border-risk-low/40 bg-risk-low/10 text-risk-low",
  moderate: "border-risk-moderate/40 bg-risk-moderate/10 text-risk-moderate",
  high: "border-risk-high/40 bg-risk-high/10 text-risk-high",
  severe: "border-risk-severe/45 bg-risk-severe/15 text-risk-severe",
};

export function RiskBadge({
  risk,
  label,
  className,
}: {
  risk: RiskLevel;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase",
        riskClasses[risk],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {label ?? `${RISK_LABEL[risk]} risk`}
    </span>
  );
}

const statusClasses: Record<string, string> = {
  Operational: "border-status-ok/40 bg-status-ok/10 text-status-ok",
  Loaded: "border-status-ok/40 bg-status-ok/10 text-status-ok",
  Available: "border-status-busy/40 bg-status-busy/10 text-status-busy",
  Processing: "border-status-busy/40 bg-status-busy/10 text-status-busy",
  Sent: "border-status-ok/40 bg-status-ok/10 text-status-ok",
  Approved: "border-status-busy/40 bg-status-busy/10 text-status-busy",
  Draft: "border-border bg-muted text-muted-foreground",
  Warning: "border-status-warn/40 bg-status-warn/10 text-status-warn",
  Unavailable: "border-status-down/40 bg-status-down/10 text-status-down",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase",
        statusClasses[status] ?? "border-border bg-muted text-muted-foreground",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

export function Panel({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-md border border-border bg-card shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset]",
        className,
      )}
    >
      {title ? (
        <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <h2 className="text-[12px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
            {title}
          </h2>
          {action}
        </header>
      ) : null}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: RiskLevel | "neutral";
}) {
  const toneClass =
    tone && tone !== "neutral"
      ? {
          low: "text-risk-low",
          moderate: "text-risk-moderate",
          high: "text-risk-high",
          severe: "text-risk-severe",
        }[tone]
      : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-card px-4 py-3">
      <p className="text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
        {label}
      </p>
      <p className={cn("mt-1.5 text-2xl leading-none font-semibold tabular", toneClass)}>
        {value}
      </p>
      {sub ? <p className="mt-1.5 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}


