import { RouteLink } from "@/utils/router";
import { AlertTriangle, ArrowRight, Droplets, Waves } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { Metric, Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";

export function DashboardPage() {
  const sim = useSim();
  const m = sim.metrics;

  const alerts = (sim.roadImpact?.rows ?? [])
    .filter((row) => row.affected === true || row.affected === "True" || row.affected === "true")
    .slice(0, 4)
    .map((row) => ({
      id: String(row.road_id),
      title: String(row.road_id ?? "Unnamed road"),
      depth: row.max_intersecting_depth_m == null ? null : Number(row.max_intersecting_depth_m) * 100,
      risk: String(row.risk_class ?? "moderate") as "low" | "moderate" | "high" | "severe",
      reason: "Dynamic road access assessment",
    }));

  return (
    <AppShell
      title="Flood Management Control Center"
      subtitle={sim.studyArea ? `${sim.studyArea.name} · ${sim.studyArea.city}, ${sim.studyArea.state}` : "Study area metadata unavailable"}
      actions={
        <RouteLink
          to="/simulation"
          className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Run Simulation
        </RouteLink>
      }
    >
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">
        <Metric label="Study area" value="Bellandur" sub="Bengaluru · Bellandur Lake Basin" />
        <Metric
          label="Current flood risk"
          value={sim.summary ? m.overallRisk.toUpperCase() : "UNAVAILABLE"}
          tone={m.overallRisk}
          sub={`Max depth ${m.maxDepthCm.toFixed(1)} cm at ${m.clock}`}
        />
        <Metric label="Rainfall now" value={`${m.rainfallNow} mm/hr`} sub={`${m.accumulatedRainfallMm} mm accumulated`} />
        <Metric label="Affected area" value={`${m.affectedAreaKm2.toFixed(1)} km²`} sub="Flood extent" />
        <Metric label="Affected roads" value={m.highRiskRoads} sub="Roads with access impact" />
        <Metric label="Critical locations" value={m.criticalAtRisk} sub="Facilities with affected access" />
        <Metric
          label="Simulation status"
          value={sim.status === "running" ? "Processing" : sim.status === "complete" ? "Complete" : "Ready"}
          sub={sim.status === "complete" ? `Flood result at T+${m.clock}` : "Extreme rainfall scenario configured"}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Panel
          title="Current situation"
          action={
            <RouteLink
              to="/map"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Open flood map <ArrowRight className="size-3.5" />
            </RouteLink>
          }
          bodyClassName="p-0"
        >
          <MapSurface className="h-[420px]" interactive={false} zoom={12} />
        </Panel>

        <Panel title="Simulation summary">
          <dl className="space-y-3 text-sm">
            {[
              ["Selected area", sim.studyArea?.name ?? "Unavailable"],
              ["Selected area", "Bellandur, Bengaluru"],
              ["Rainfall event", "Extreme monsoon storm"],
              ["Rainfall source", "Open-Meteo precipitation forecast"],
              ["Current simulation time", `T+${m.clock}`],
              ["Rainfall intensity", `${m.rainfallNow} mm/hr`],
              ["Accumulated rainfall", `${m.accumulatedRainfallMm} mm`],
              ["Maximum flood depth", `${m.maxDepthCm.toFixed(1)} cm`],
              ["Affected area", `${m.affectedAreaKm2.toFixed(1)} km²`],
            ].map(([k, v]) => (
              <div key={k} className="flex items-start justify-between gap-4 border-b border-border/60 pb-2.5 last:border-0">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="text-right font-medium tabular">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 flex items-center justify-between rounded-md border border-border bg-panel px-3 py-2.5">
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <Droplets className="size-4 text-primary" /> Rainfall now
            </span>
            <span className="text-sm font-semibold tabular">{m.rainfallNow} mm/hr</span>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Panel title="Critical alerts">
          <ul className="space-y-2.5">
            {alerts.length === 0 ? (
              <li className="text-sm text-muted-foreground">
                No high-risk conditions at the current simulation time.
              </li>
            ) : (
              alerts.map((a) => (
                <li
                  key={a.id}
                  className="flex items-start gap-3 rounded-md border border-border bg-panel px-3 py-2.5"
                >
                  <AlertTriangle
                    className={
                      a.risk === "severe" ? "mt-0.5 size-4 text-risk-severe" : "mt-0.5 size-4 text-risk-high"
                    }
                  />
                  <div className="flex-1">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium">{a.title}</p>
                      <RiskBadge risk={a.risk} />
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {a.reason} · Flood depth {a.depth == null ? "—" : `${a.depth.toFixed(1)} cm`}
                    </p>
                  </div>
                </li>
              ))
            )}
            <li className="flex items-start gap-3 rounded-md border border-border bg-panel px-3 py-2.5">
              <Waves className="mt-0.5 size-4 text-risk-high" />
              <div className="flex-1">
                <p className="text-sm font-medium">{sim.status === "complete" ? "Bellandur lake spillover channel above threshold" : "Rainfall event is being monitored"}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {sim.status === "complete" ? "Drainage capacity exceeded in Ward 04 — rapid accumulation in the low-lying basin." : "Run the simulation to project runoff, flood depth and road access."}
                </p>
              </div>
            </li>
          </ul>
        </Panel>

        <Panel title="Zone risk board">
          <ul className="space-y-2">
            {sim.zones.map((z) => (
              <li key={z.id} className="flex items-center justify-between gap-3 text-sm">
                <div>
                  <p className="font-medium">{z.name}</p>
                  <p className="text-xs text-muted-foreground">{z.ward}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground tabular">{z.depthCm} cm</span>
                  <StatusPill status={z.risk === "low" ? "Operational" : "Warning"} />
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </AppShell>
  );
}


