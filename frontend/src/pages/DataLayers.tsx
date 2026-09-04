import { AppShell } from "@/components/AppShell";
import { Panel, StatusPill } from "@/components/RiskUI";
import { DATASETS, REGION } from "@/data/pilot";

export function DataLayersPage() {
  return (
    <AppShell title="Data & Layers" subtitle="Geospatial and environmental inputs to the simulation engine">
      <Panel title="Configured coverage">
        <div className="grid gap-4 text-sm md:grid-cols-4">
          <Item label="Region" value={REGION.region} />
          <Item label="Catchment" value={REGION.area} />
          <Item label="Coverage" value={`${REGION.coverageKm2} km²`} />
          <Item label="Reference system" value={REGION.crs} />
        </div>
      </Panel>

      <Panel title="Dataset inventory" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <th className="px-4 py-2.5 font-medium">Dataset</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Coverage area</th>
              <th className="px-4 py-2.5 font-medium">Source</th>
              <th className="px-4 py-2.5 font-medium">Size</th>
              <th className="px-4 py-2.5 font-medium">Last updated</th>
            </tr>
          </thead>
          <tbody>
            {DATASETS.map((d) => (
              <tr key={d.name} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium">{d.name}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={d.status} />
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{d.coverage}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{d.source}</td>
                <td className="px-4 py-2.5 tabular">{d.size}</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">{d.updated}</td>
              </tr>
            ))}
          </tbody>
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
      <p className="text-[11px] tracking-[0.12em] text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 font-medium">{value}</p>
    </div>
  );
}


