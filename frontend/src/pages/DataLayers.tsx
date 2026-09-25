import { AppShell } from "@/components/AppShell";
import { Panel, StatusPill } from "@/components/RiskUI";
import { DEMO_RAINFALL_SOURCES } from "@/data/demo";
import { useSim } from "@/state/simulation";

export function DataLayersPage() {
  const sim = useSim();
  const datasets = [
    { name: "P6 coupled outputs", available: sim.apiStatus?.available_data_products.p6 === true },
    { name: "P7 flood summary / extent / time series", available: sim.apiStatus?.available_data_products.p7 === true },
    { name: "P8 flood-safe routing", available: sim.apiStatus?.available_data_products.p8 === true },
    { name: "Rainfall source catalog", available: sim.rainfallSources.length > 0 },
  ];
  return (
    <AppShell title="Data & Layers" subtitle="Geospatial and environmental inputs to the simulation engine">
      <Panel title="Configured coverage">
        <div className="grid gap-4 text-sm md:grid-cols-4">
          <Item label="Region" value={sim.studyArea?.city ?? "Unavailable"} />
          <Item label="Catchment" value={sim.studyArea?.name ?? "Unavailable"} />
          <Item label="Coverage" value={sim.studyArea ? `${sim.studyArea.approximate_area_km2} km²` : "Unavailable"} />
          <Item label="Reference system" value={sim.studyArea?.crs ?? "Unavailable"} />
        </div>
      </Panel>

      <Panel title="Dataset inventory" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">Dataset</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Coverage area</th>
              <th className="px-4 py-2.5 font-medium">Source</th>
              <th className="px-4 py-2.5 font-medium">Size</th>
              <th className="px-4 py-2.5 font-medium">Last updated</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.name} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium">{d.name}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={d.available ? "Available" : "Unavailable"} />
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{d.available ? "Published by backend" : "Not available"}</td>
                <td className="px-4 py-2.5 text-muted-foreground">P9 API</td>
                <td className="px-4 py-2.5 tabular">—</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">Backend metadata</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Rainfall source registry" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="px-4 py-2.5 font-medium">Source</th><th className="px-4 py-2.5 font-medium">Product</th><th className="px-4 py-2.5 font-medium">Role</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Notes</th></tr></thead>
          <tbody>{DEMO_RAINFALL_SOURCES.map((source) => <tr key={String(source.source_id)} className="border-b border-border/60 last:border-0"><td className="px-4 py-2.5 font-medium">{String(source.source_name)}</td><td className="px-4 py-2.5 text-muted-foreground">{String(source.product)}</td><td className="px-4 py-2.5 text-muted-foreground">{String(source.role)}</td><td className="px-4 py-2.5"><StatusPill status={source.available === false ? "Unavailable" : source.status === "metadata_only" ? "Warning" : "Available"} /></td><td className="px-4 py-2.5 text-muted-foreground">{String(source.detail)}</td></tr>)}</tbody>
        </table>
      </Panel>

      <Panel title="Notes">
        <p className="text-sm text-muted-foreground">
          Simulation accuracy depends on the currency and resolution of these
          datasets. Elevation and drainage layers are the primary drivers of
          modelled flood depth; rainfall feeds drive the temporal progression.
          Onboarding a new region requires the same six layers to be published
          and validated by the GIS cell.
        </p>
      </Panel>
    </AppShell>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium">{value}</p>
    </div>
  );
}


