import { AppShell } from "@/components/AppShell";
import { Metric, MetricStrip, Panel, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";

export function SystemStatusPage() {
  const sim = useSim();
  const selectedRainfall = sim.rainfallStatus?.sources.find((source) => source.source_id === sim.rainfallStatus?.source_used);
  const currentRainfall = sim.rainfallCurrentStatus;
  const currentRainfallLabel = currentRainfall?.source_name ?? currentRainfall?.source_used ?? "Unavailable";
  const services = [
    { name: "Application API", status: sim.health ? "Operational" : sim.dataStatus === "loading" ? "Processing" : "Unavailable", detail: sim.health?.message ?? "No health response" },
    { name: "P6 coupled products", status: sim.apiStatus?.available_data_products.p6 ? "Available" : "Unavailable", detail: "Validated product availability from /api/status" },
    { name: "P7 flood products", status: sim.apiStatus?.available_data_products.p7 ? "Available" : "Unavailable", detail: "Summary, extent, time series and road impact" },
    { name: "P8 routing", status: sim.apiStatus?.available_data_products.p8 ? "Available" : "Unavailable", detail: sim.apiStatus?.routing_capability ?? "No routing status" },
    { name: "Quantitative rainfall", status: sim.rainfallStatus?.source_used ? "Available" : "Unavailable", detail: selectedRainfall?.product ?? sim.rainfallStatus?.source_used ?? sim.rainfallStatus?.fallback_reason ?? "No rainfall source status" },
    { name: "Current/forecast rainfall", status: currentRainfall?.source_used ? "Available" : "Unavailable", detail: currentRainfall?.source_role === "model_forecast" ? `${currentRainfallLabel} (model-based forecast; not radar/DWR)` : currentRainfallLabel },
  ];
  return (
    <AppShell title="System Status" subtitle="Platform health and recent activity">
      <MetricStrip className="md:grid-cols-5">
        <Metric label="Platform state" value={sim.health ? "Operational" : sim.dataStatus === "loading" ? "Loading" : "Unavailable"} tone={sim.health ? "low" : "neutral"} />
        <Metric label="Historical rainfall" value={sim.rainfallStatus?.source_name ?? "MOSDAC INSAT-3DR"} sub={selectedRainfall?.product ?? "3RIMG_L2B_IMC"} />
        <Metric label="Current/forecast rainfall" value={currentRainfall?.source_role === "model_forecast" ? `${currentRainfallLabel} · model` : currentRainfallLabel} sub="Precipitation forecast, not radar" />
        <Metric label="Validated runs" value={sim.runs.length} />
        <Metric label="API environment" value={sim.health?.environment ?? "Unavailable"} />
      </MetricStrip>

      <Panel title="Services" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">Service</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.name} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium">{s.name}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={s.status} />
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{s.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Recent simulation runs" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">Run ID</th>
              <th className="px-4 py-2.5 font-medium">Scenario</th>
              <th className="px-4 py-2.5 font-medium">Operator</th>
              <th className="px-4 py-2.5 font-medium">Started</th>
              <th className="px-4 py-2.5 font-medium">Duration</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {sim.runs.map((r, index) => (
              <tr key={`${r.phase}-${index}`} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium tabular">{`${r.phase}-${index + 1}`}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{r.product}</td>
                <td className="px-4 py-2.5 text-muted-foreground">Neer Kawach API</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">{r.generated_at_utc ?? "—"}</td>
                <td className="px-4 py-2.5 tabular">{r.timestamps.length} timestamp(s)</td>
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


