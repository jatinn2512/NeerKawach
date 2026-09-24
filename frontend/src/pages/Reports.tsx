import { Download, FileDown, FileText } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";

const PAST = [
  { id: "RPT-2026-0841", scenario: "Heavy Rainfall", created: "29 Aug 2026, 09:12", status: "Sent" },
  { id: "RPT-2026-0837", scenario: "Extreme Storm", created: "24 Aug 2026, 18:40", status: "Approved" },
  { id: "RPT-2026-0830", scenario: "Moderate Rainfall", created: "19 Aug 2026, 07:55", status: "Draft" },
];

export function ReportsPage() {
  const sim = useSim();
  const m = sim.metrics;
  const safer = sim.routeResults.floodAware;

  return (
    <AppShell
      title="Reports"
      subtitle="Simulation summary for official disaster-management records"
      actions={
        <div className="flex gap-2">
          <button
            onClick={() => toast.success("Report generated", { description: "RPT-2026-0842 created from the active simulation." })}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            <FileText className="size-3.5" /> Generate Report
          </button>
          <button
            onClick={() => toast("Export queued", { description: "PDF export will download when rendering completes." })}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-semibold hover:bg-accent"
          >
            <FileDown className="size-3.5" /> Export PDF
          </button>
          <button
            onClick={() => toast("Export queued", { description: "GeoJSON + CSV bundle prepared for download." })}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-semibold hover:bg-accent"
          >
            <Download className="size-3.5" /> Export Data
          </button>
        </div>
      }
    >
      <Panel title="Report RPT-2026-0842 (draft)">
        <div className="mb-4 flex items-center justify-between border-b border-border pb-3">
          <div>
            <h2 className="text-base font-semibold">Flood Simulation Summary Report</h2>
            <p className="text-xs text-muted-foreground">
              Issued by FloodOps · District Disaster Management Authority
            </p>
          </div>
          <StatusPill status="Draft" />
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Section
            title="Scenario & area"
            rows={[
              ["Region", sim.studyArea?.state ?? "Unavailable"],
              ["City / municipal body", sim.studyArea?.city ?? "Unavailable"],
              ["Catchment", sim.studyArea?.name ?? "Unavailable"],
              ["Replay timestamp", sim.selectedTimestamp ?? "Unavailable"],
              ["Rainfall intensity", `${m.rainfallNow} mm/hr`],
              ["Accumulated rainfall", `${m.accumulatedRainfallMm} mm`],
              ["Rainfall source", "Open-Meteo precipitation forecast"],
              ["Simulation duration", "03:00"],
              ["Simulation timestamp", m.startedAt],
            ]}
          />
          <Section
            title="Flood impact"
            rows={[
              ["Maximum flood depth", sim.summary ? `${m.maxDepthCm.toFixed(1)} cm` : "Unavailable"],
              ["Affected area", sim.summary ? `${m.affectedAreaKm2.toFixed(3)} km²` : "Unavailable"],
              ["Affected zones", `${m.affectedZones}`],
              ["Affected road segments", `${m.highRiskRoads}`],
              ["Critical facilities at risk", `${m.criticalAtRisk}`],
              ["Overall risk classification", sim.summary ? m.overallRisk.toUpperCase() : "UNAVAILABLE"],
            ]}
          />
        </div>

        <h3 className="mt-6 text-[12px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Affected roads
        </h3>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] tracking-[0.1em] text-muted-foreground uppercase">
              <th className="py-2 font-medium">Segment</th>
              <th className="py-2 font-medium">Category</th>
              <th className="py-2 font-medium">Depth</th>
              <th className="py-2 font-medium">Risk</th>
            </tr>
          </thead>
          <tbody>
            {(sim.roadImpact?.rows ?? []).filter((r) => r.affected === true).map((r) => (
                <tr key={String(r.road_id)} className="border-b border-border/60 last:border-0">
                  <td className="py-2">{String(r.road_id ?? "Unnamed road")}</td>
                  <td className="py-2 text-muted-foreground">Validated P7 output</td>
                  <td className="py-2 tabular">{r.max_intersecting_depth_m == null ? "Unavailable" : `${Number(r.max_intersecting_depth_m) * 100} cm`}</td>
                  <td className="py-2">{String(r.risk_class ?? "Unavailable")}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>

        <h3 className="mt-6 text-[12px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Critical infrastructure
        </h3>
        <ul className="mt-2 grid gap-2 md:grid-cols-2">
          {(sim.routeResults.floodAware ? [sim.routeResults.floodAware] : []).map((f) => (
            <li
              key={f.routing_mode}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-panel px-3 py-2 text-sm"
            >
              <span>
                Flood-aware route
                <span className="block text-xs text-muted-foreground">P8 validated routing result</span>
              </span>
              <span className="text-xs font-semibold uppercase">{(f.maximum_flood_depth_m * 100).toFixed(1)} cm max depth</span>
            </li>
          ))}
        </ul>

        <h3 className="mt-6 text-[12px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
          Safer route advisory
        </h3>
        <p className="mt-2 text-sm">
          {safer ? `Flood-aware route: ${(safer.total_distance_m / 1000).toFixed(2)} km, maximum depth ${(safer.maximum_flood_depth_m * 100).toFixed(1)} cm. Advisory only; passability must be confirmed by field teams.` : "No validated route result is available."}
        </p>
      </Panel>

      <Panel title="Previous reports" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <th className="px-4 py-2.5 font-medium">Report ID</th>
              <th className="px-4 py-2.5 font-medium">Scenario</th>
              <th className="px-4 py-2.5 font-medium">Created</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {sim.runs.map((p, index) => (
              <tr key={`${p.phase}-${index}`} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium tabular">{`${p.phase}-${index + 1}`}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{p.product}</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">{p.generated_at_utc ?? "—"}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status="Available" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </AppShell>
  );
}

function Section({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div>
      <h3 className="text-[12px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        {title}
      </h3>
      <dl className="mt-2 space-y-2 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-border/60 pb-1.5 last:border-0">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right font-medium tabular">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}


