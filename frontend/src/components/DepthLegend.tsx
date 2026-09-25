import { RISK_COLOR, type RiskLevel } from "@/data/pilot";
import { cn } from "@/lib/utils";

const entries: [RiskLevel, string][] = [["low", "< 10"], ["moderate", "10–30"], ["high", "30–50"], ["severe", "> 50 cm"]];

/** Compact flood-depth key for overlaying on a map corner. */
export function DepthLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-3 rounded-md bg-[#06121e]/85 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-lg backdrop-blur", className)}>
      <span className="font-medium text-foreground/85">Flood depth</span>
      {entries.map(([risk, label]) => (
        <span key={risk} className="flex items-center gap-1.5 tabular">
          <span className="h-2 w-3 rounded-xs" style={{ backgroundColor: RISK_COLOR[risk] }} />
          {label}
        </span>
      ))}
    </div>
  );
}
