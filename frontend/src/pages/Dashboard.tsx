import { RouteLink } from "@/utils/router";
import { ArrowRight, Waves } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { DepthLegend } from "@/components/DepthLegend";
import { MapSurface } from "@/components/MapSurface";
import { Metric, MetricStrip, Panel, RiskBadge, StatusPill, riskBar, riskText } from "@/components/RiskUI";
import { RISK_LABEL, type RiskLevel } from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

export function DashboardPage() {
  const sim = useSim();
  const m = sim.metrics;

  const affected = (sim.roadImpact?.rows ?? [])
    .filter((row) => row.affected === true || row.affected === "True" || row.affected === "true")
    .map((row) => ({
      id: String(row.road_id),
      title: String(row.road_id ?? "Unnamed road"),
      depth: row.max_intersecting_depth_m == null ? null : Number(row.max_intersecting_depth_m) * 100,
      risk: String(row.risk_class ?? "moderate") as RiskLevel,
    }))
    .sort((a, b) => (b.depth ?? 0) - (a.depth ?? 0));
  const alerts = affected.slice(0, 4);
  const zones = [...sim.zones].sort((a, b) => b.depthCm - a.depthCm);
  const simState = sim.status === "running" ? "Processing" : sim.status === "complete" ? "Complete" : "Ready";

  return (
    <AppShell
      fill
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
      <MetricStrip className="shrink-0 grid-cols-2 md:grid-cols-3 xl:grid-cols-[1.3fr_repeat(5,minmax(0,1fr))]">
        <div className="relative min-w-0 py-3 pr-4 pl-5">
          <span className={cn("absolute inset-y-0 left-0 w-1", sim.summary ? riskBar[m.overallRisk] : "bg-muted")} />
          <p className="text-xs text-muted-foreground">Current flood risk</p>
          <p className={cn("mt-1 text-2xl leading-tight font-bold", sim.summary ? riskText[m.overallRisk] : "text-muted-foreground")}>
            {sim.summary ? RISK_LABEL[m.overallRisk] : "Unavailable"}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{sim.scenario.name} · T+{m.clock}</p>
        </div>
        <Metric label="Max flood depth" value={`${m.maxDepthCm.toFixed(1)} cm`} sub={`at T+${m.clock}`} />
        <Metric label="Rainfall now" value={`${m.rainfallNow} mm/hr`} sub={`${m.accumulatedRainfallMm} mm accumulated`} />
        <Metric label="Affected area" value={`${m.affectedAreaKm2.toFixed(1)} km²`} sub="Flood extent" />
        <Metric label="Affected roads" value={m.highRiskRoads} sub="Roads with access impact" />
        <Metric label="Critical locations" value={m.criticalAtRisk} sub="Facilities with affected access" />
      </MetricStrip>

      <div className="grid gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel
          className="flex min-h-115 flex-col overflow-hidden"
          title={
            <span className="flex items-center gap-3">
              Current situation
              <span className="text-xs font-normal text-muted-foreground">
                Simulation {simState.toLowerCase()} · {sim.status === "complete" ? `flood result at T+${m.clock}` : "extreme rainfall scenario configured"}
              </span>
            </span>
          }
          action={
            <RouteLink to="/map" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              Open flood map <ArrowRight className="size-3.5" />
            </RouteLink>
          }
          bodyClassName="relative min-h-0 flex-1 p-0"
        >
          <MapSurface className="absolute inset-0" interactive={false} padding={[48, 20, 28, 20]} />
          <DepthLegend className="absolute top-3 left-3 z-1000" />
        </Panel>

        <div className="flex min-h-0 flex-col gap-4">
          <Panel
            className="flex min-h-0 flex-col xl:flex-1"
            title={
              <span className="flex items-center gap-2">
                Active alerts
                {affected.length ? <span className="rounded bg-risk-severe/15 px-1.5 text-[11px] font-semibold text-risk-severe tabular">{affected.length}</span> : null}
              </span>
            }
            action={
              <RouteLink to="/risk" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                All alerts <ArrowRight className="size-3.5" />
              </RouteLink>
            }
            bodyClassName="min-h-0 flex-1 overflow-y-auto"
          >
            <ul className="space-y-1">
              {alerts.length === 0 ? (
                <li className="py-1 text-sm text-muted-foreground">
                  No high-risk conditions at the current simulation time.
                </li>
              ) : (
                alerts.map((a) => (
                  <li key={a.id} className="flex items-stretch gap-3 rounded-md bg-panel/70 py-2 pr-2.5">
                    <span className={cn("w-0.5 shrink-0 rounded-full", riskBar[a.risk])} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{a.title}</p>
                      <p className="text-xs text-muted-foreground tabular">
                        Flood depth {a.depth == null ? "—" : `${a.depth.toFixed(0)} cm`} · road access
                      </p>
                    </div>
                    <RiskBadge risk={a.risk} label={RISK_LABEL[a.risk]} className="self-center" />
                  </li>
                ))
              )}
              {affected.length > alerts.length ? (
                <li className="px-3 pt-1 text-xs text-muted-foreground">
                  +{affected.length - alerts.length} more affected road segments
                </li>
              ) : null}
            </ul>
            <div className="mt-3 flex items-start gap-2.5 border-t border-border pt-3">
              <Waves className={cn("mt-0.5 size-4 shrink-0", sim.status === "complete" ? "text-risk-high" : "text-primary")} />
              <div>
                <p className="text-sm font-medium">{sim.status === "complete" ? "Bellandur lake spillover channel above threshold" : "Rainfall event is being monitored"}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {sim.status === "complete" ? "Drainage capacity exceeded in Ward 04 — rapid accumulation in the low-lying basin." : "Run the simulation to project runoff, flood depth and road access."}
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Zone risk board" className="shrink-0">
            <ul className="space-y-2">
              {zones.map((z) => (
                <li key={z.id} className="grid grid-cols-[minmax(0,1fr)_64px_44px] items-center gap-3 text-sm">
                  <p className="truncate">
                    {z.name} <span className="text-xs text-muted-foreground">· {z.ward}</span>
                  </p>
                  <span className="h-1.5 overflow-hidden rounded-full bg-white/6">
                    <span className={cn("block h-full rounded-full transition-[width] duration-500", riskBar[z.risk])} style={{ width: `${Math.min(100, z.depthCm)}%` }} />
                  </span>
                  <span className={cn("text-right text-xs font-medium tabular", z.depthCm >= 10 ? riskText[z.risk] : "text-muted-foreground")}>{z.depthCm} cm</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Rainfall event" className="shrink-0" action={<StatusPill status={sim.status === "running" ? "Processing" : sim.status === "complete" ? "Available" : "Draft"} />}>
            <dl className="space-y-1.5 text-sm">
              {[
                ["Event", "Extreme monsoon storm"],
                ["Rainfall source", "Open-Meteo precipitation forecast"],
                ["Simulation time", `T+${m.clock}`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-4">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="text-right font-medium tabular">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
