import { RouteLink } from "@/utils/router";
import { AlertTriangle, ArrowRight, Droplets, Waves } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { Metric, Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { REGION } from "@/data/pilot";
import { useSim } from "@/state/simulation";

export function DashboardPage() {
  const sim = useSim();
  const m = sim.metrics;

  const alerts = sim.roads
    .filter((r) => r.risk === "high" || r.risk === "severe")
    .slice(0, 4)
    .map((r) => ({
      id: r.id,
      title: r.name,
      depth: r.depthCm,
      risk: r.risk,
      reason:
        r.depthCm > 60
          ? "Drainage capacity exceeded — rapid surface accumulation"
          : "Runoff from upstream ward exceeding channel capacity",
    }));

  return (
    <AppShell
      title="Flood Management Control Center"
      subtitle={`${REGION.area} · ${REGION.city} · ${REGION.region}`}
      actions={
        <RouteLink
          to="/simulation"
          className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
        >
          New Simulation
        </RouteLink>
      }
    >
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">
        <Metric label="Active simulation" value={sim.scenario.name} sub={`${sim.scenario.intensityMmHr} mm/hr · ${sim.scenario.durationHrs} h`} />
        <Metric
          label="Current flood risk"
          value={m.overallRisk.toUpperCase()}
          tone={m.overallRisk}
          sub={`Max depth ${m.maxDepthCm} cm`}
        />
        <Metric label="Affected zones" value={m.affectedZones} sub={`of ${sim.zones.length} configured wards`} />
        <Metric label="High-risk roads" value={m.highRiskRoads} sub={`of ${sim.roads.length} monitored segments`} />
        <Metric label="Critical locations" value={m.criticalAtRisk} sub="Facilities with affected access" />
        <Metric
          label="Simulation status"
          value={sim.status === "running" ? `${sim.progress}%` : `T+${m.clock}`}
          sub={sim.status === "running" ? "Model executing" : "Results available"}
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
              ["Selected area", `${REGION.area} · Ward 04`],
              ["Rainfall intensity", `${sim.scenario.intensityMmHr} mm/hr (${sim.scenario.returnPeriod})`],
              ["Storm duration", `${sim.scenario.durationHrs} hours`],
              ["Simulation start", m.startedAt],
              ["Current simulation time", `T+${m.clock}`],
              ["Maximum predicted depth", `${m.maxDepthCm} cm`],
              ["Affected area", `${m.affectedAreaKm2} km²`],
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
                      {a.reason} · Flood depth {a.depth} cm
                    </p>
                  </div>
                </li>
              ))
            )}
            <li className="flex items-start gap-3 rounded-md border border-border bg-panel px-3 py-2.5">
              <Waves className="mt-0.5 size-4 text-risk-high" />
              <div className="flex-1">
                <p className="text-sm font-medium">Bellandur lake spillover channel above threshold</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Drainage capacity exceeded in Ward 04 — rapid accumulation in the low-lying basin.
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


