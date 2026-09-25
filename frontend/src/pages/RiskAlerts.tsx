import { AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Metric, MetricStrip, Panel, RiskBadge, TABLE_HEAD, riskBar, riskText } from "@/components/RiskUI";
import { RISK_LABEL, type RiskLevel } from "@/data/pilot";
import { cn } from "@/lib/utils";
import { useSim } from "@/state/simulation";

const ACTIONS: Record<string, string> = {
  severe: "Close segment, divert traffic and alert field response teams",
  high: "Monitor evacuation access and pre-position barricades",
  moderate: "Advise caution, monitor depth trend at 15-minute intervals",
  low: "No action required — continue monitoring",
};

export function RiskPage() {
  const sim = useSim();
  const m = sim.metrics;
  const flagged = (sim.roadImpact?.rows ?? [])
    .filter((row) => row.affected === true || row.affected === "True" || row.affected === "true")
    .sort((a, b) => Number(b.max_intersecting_depth_m ?? 0) - Number(a.max_intersecting_depth_m ?? 0));

  return (
    <AppShell title="Risk & Alerts" subtitle="Operator decision support — not a public notification channel">
      <div className="relative flex flex-wrap items-center justify-between gap-4 overflow-hidden rounded-lg bg-card py-4 pr-6 pl-7">
        <span className={cn("absolute inset-y-0 left-0 w-1.5", riskBar[m.overallRisk])} />
        <div>
          <p className={cn("text-xs font-medium", riskText[m.overallRisk])}>
            Current overall assessment
          </p>
          <p className="mt-1 text-2xl font-semibold">
            <span className={riskText[m.overallRisk]}>{RISK_LABEL[m.overallRisk]}</span> flood risk
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {sim.selectedTimestamp ?? "No validated timestamp selected"} · simulation time {m.clock}
          </p>
        </div>
        <div className="flex gap-8 text-center">
          <div>
            <p className="text-2xl font-semibold tabular">{sim.dataStatus === "ready" ? m.affectedZones : "—"}</p>
            <p className="text-xs text-muted-foreground">affected zones</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular">{sim.dataStatus === "ready" ? m.highRiskRoads : "—"}</p>
            <p className="text-xs text-muted-foreground">high-risk roads</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular">{sim.dataStatus === "ready" ? m.criticalAtRisk : "—"}</p>
            <p className="text-xs text-muted-foreground">critical locations</p>
          </div>
        </div>
      </div>

      <MetricStrip className="md:grid-cols-4">
        <Metric label="Max flood depth" value={sim.summary ? `${m.maxDepthCm.toFixed(1)} cm` : "Unavailable"} tone={m.overallRisk ?? "neutral"} />
        <Metric label="Affected area" value={sim.summary ? `${m.affectedAreaKm2.toFixed(1)} km²` : "Unavailable"} />
        <Metric label="Road impacts" value={sim.roadImpact ? flagged.length : "Unavailable"} tone="high" />
        <Metric label="Validated timestamp" value={sim.selectedTimestamp ?? "Unavailable"} />
      </MetricStrip>

      <Panel title="Critical alerts & recommended actions" bodyClassName="p-0">
        <ul>
          {flagged.length === 0 ? (
            <li className="px-4 pb-4 text-sm text-muted-foreground">
              No zones or roads currently classified above low risk.
            </li>
          ) : (
            flagged.map((r) => (
              <li key={String(r.road_id)} className="relative border-t border-border py-3 pr-4 pl-6">
                <span className={cn("absolute top-3 bottom-3 left-3 w-0.5 rounded-full", riskBar[String(r.risk_class ?? "high") as RiskLevel] ?? "bg-risk-high")} />
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className={cn("size-4", riskText[String(r.risk_class ?? "high") as RiskLevel] ?? "text-risk-high")} /> {String(r.road_id ?? "Unnamed road")}
                  </p>
                  {r.risk_class && String(r.risk_class) in riskText ? <RiskBadge risk={String(r.risk_class) as RiskLevel} /> : <span className="text-xs text-muted-foreground">{String(r.risk_class ?? "Affected")}</span>}
                </div>
                <div className="mt-1.5 grid gap-2 pl-6 text-xs md:grid-cols-[160px_220px_1fr]">
                  <p>
                    <span className="text-muted-foreground">Flood depth: </span>
                    <span className="font-medium tabular">{r.max_intersecting_depth_m == null ? "Unavailable" : `${Number(r.max_intersecting_depth_m) * 100} cm`}</span>
                  </p>
                  <p>
                    <span className="text-muted-foreground">Reason: </span>
                    Validated road-impact output
                  </p>
                  <p>
                    <span className="text-muted-foreground">Recommended action: </span>
                    {ACTIONS[String(r.risk_class ?? "moderate")] ?? "Review validated road-impact output"}
                  </p>
                </div>
              </li>
            ))
          )}
        </ul>
      </Panel>

      <Panel title="Critical infrastructure exposure" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className={TABLE_HEAD}>
              <th className="px-4 py-2.5 font-medium">Facility</th>
              <th className="px-4 py-2.5 font-medium">Type</th>
              <th className="px-4 py-2.5 font-medium">Access road</th>
              <th className="px-4 py-2.5 font-medium">Depth on access</th>
              <th className="px-4 py-2.5 font-medium">Access status</th>
              <th className="px-4 py-2.5 font-medium">Risk</th>
            </tr>
          </thead>
          <tbody>
            {sim.facilities.map((f) => (
              <tr key={f.id} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium">{f.name}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{f.type}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{f.accessRoad?.name}</td>
                <td className="px-4 py-2.5 tabular">{f.accessRoad?.depthCm ?? 0} cm</td>
                <td className="px-4 py-2.5">
                  {f.risk === "severe" ? "Blocked" : f.risk === "high" ? "Affected" : "Available"}
                </td>
                <td className="px-4 py-2.5">
                  <RiskBadge risk={f.risk} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </AppShell>
  );
}


