import { AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Metric, Panel, RiskBadge } from "@/components/RiskUI";
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
  const flagged = (sim.roadImpact?.rows ?? []).filter((row) => row.affected === true || row.affected === "True" || row.affected === "true");

  return (
    <AppShell title="Risk & Alerts" subtitle="Operator decision support — not a public notification channel">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-md border border-risk-high/40 bg-risk-high/10 px-5 py-4">
        <div>
          <p className="text-[11px] tracking-[0.16em] text-risk-high uppercase">
            Current overall assessment
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {(m.overallRisk ?? "unavailable").toUpperCase()} FLOOD RISK
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

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Max flood depth" value={sim.summary ? `${m.maxDepthCm.toFixed(1)} cm` : "Unavailable"} tone={m.overallRisk ?? "neutral"} />
        <Metric label="Affected area" value={sim.summary ? `${m.affectedAreaKm2.toFixed(3)} km²` : "Unavailable"} />
        <Metric label="Road impacts" value={sim.roadImpact ? flagged.length : "Unavailable"} tone="high" />
        <Metric label="Validated timestamp" value={sim.selectedTimestamp ?? "Unavailable"} />
      </div>

      <Panel title="Critical alerts & recommended actions">
        <ul className="space-y-2.5">
          {flagged.length === 0 ? (
            <li className="text-sm text-muted-foreground">
              No zones or roads currently classified above low risk.
            </li>
          ) : (
            flagged.map((r) => (
              <li key={String(r.road_id)} className="rounded-md border border-border bg-panel p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className="size-4 text-risk-high" /> {String(r.road_id ?? "Unnamed road")}
                  </p>
                  <span className="text-xs font-semibold uppercase text-risk-high">{String(r.risk_class ?? "affected")}</span>
                </div>
                <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
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
            <tr className="border-b border-border text-left text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
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


