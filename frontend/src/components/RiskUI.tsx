import { cn } from "@/lib/utils";
import { RISK_LABEL, type RiskLevel } from "@/data/pilot";
import type { ReactNode } from "react";

const riskClasses: Record<RiskLevel, string> = {
  low: "bg-risk-low/12 text-risk-low",
  moderate: "bg-risk-moderate/12 text-risk-moderate",
  high: "bg-risk-high/14 text-risk-high",
  severe: "bg-risk-severe/16 text-risk-severe",
};

export const riskText: Record<RiskLevel, string> = {
  low: "text-risk-low",
  moderate: "text-risk-moderate",
  high: "text-risk-high",
  severe: "text-risk-severe",
};

export const riskBar: Record<RiskLevel, string> = {
  low: "bg-risk-low",
  moderate: "bg-risk-moderate",
  high: "bg-risk-high",
  severe: "bg-risk-severe",
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
        "inline-flex shrink-0 items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap",
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
  Operational: "bg-status-ok/12 text-status-ok",
  Loaded: "bg-status-ok/12 text-status-ok",
  Available: "bg-status-busy/12 text-status-busy",
  Processing: "bg-status-busy/12 text-status-busy",
  Sent: "bg-status-ok/12 text-status-ok",
  Approved: "bg-status-busy/12 text-status-busy",
  Draft: "bg-muted text-muted-foreground",
  Warning: "bg-status-warn/12 text-status-warn",
  Unavailable: "bg-status-down/12 text-status-down",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap",
        statusClasses[status] ?? "bg-muted text-muted-foreground",
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
    <section className={cn("rounded-lg border border-white/4 bg-card", className)}>
      {title ? (
        <header className="flex items-center justify-between gap-3 px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {action}
        </header>
      ) : null}
      <div className={cn("px-4 pb-4", !title && "pt-4", bodyClassName)}>{children}</div>
    </section>
  );
}

/** One container for a row of metrics — cells are separated by hairlines, not boxed. */
export function MetricStrip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid divide-x divide-white/5 overflow-hidden rounded-lg border border-white/4 bg-card", className)}>
      {children}
    </div>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: RiskLevel | "neutral";
  className?: string;
}) {
  const toneClass = tone && tone !== "neutral" ? riskText[tone] : "text-foreground";
  return (
    <div className={cn("min-w-0 px-4 py-3", className)}>
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 truncate text-xl leading-tight font-semibold tabular", toneClass)}>
        {value}
      </p>
      {sub ? <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

/** Column header style shared by the data tables. */
export const TABLE_HEAD = "border-b border-border text-left text-xs text-muted-foreground";
