import { Info, Navigation } from "lucide-react";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { Panel, RiskBadge } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

export function SaferRoutesPage() {
  const sim = useSim();
  const [origin, setOrigin] = useState({ latitude: "", longitude: "" });
  const [destination, setDestination] = useState({ latitude: "", longitude: "" });
  const [timestamp, setTimestamp] = useState(sim.selectedTimestamp ?? "");
  const [computing, setComputing] = useState(false);
  const canRequest = Boolean(timestamp && origin.latitude && origin.longitude && destination.latitude && destination.longitude);

  async function find() {
    if (!canRequest) return;
    setComputing(true);
    const request = {
      origin_latitude: Number(origin.latitude), origin_longitude: Number(origin.longitude),
      destination_latitude: Number(destination.latitude), destination_longitude: Number(destination.longitude),
      simulation_timestamp: timestamp, routing_mode: "baseline" as const,
    };
    await sim.requestRoute(request);
    await sim.requestRoute({ ...request, routing_mode: "flood-aware" });
    setComputing(false);
  }

  const safer = sim.routeResults.floodAware;
  const direct = sim.routeResults.baseline;
  const routeCard = (route: typeof safer, title: string) => route ? <Panel title={title}>
    <dl className="space-y-2 text-sm">
      <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Distance</dt><dd className="font-medium tabular">{(route.total_distance_m / 1000).toFixed(2)} km</dd></div>
      <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Maximum flood depth</dt><dd className="font-medium tabular">{(route.maximum_flood_depth_m * 100).toFixed(1)} cm</dd></div>
      <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Affected segments</dt><dd className="font-medium tabular">{route.affected_segments.length}</dd></div>
      <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Source</dt><dd className="font-medium">{route.source_phase}</dd></div>
    </dl>
  </Panel> : null;

  return (
    <AppShell title="Safer Routes" subtitle="Lower-risk routing based on simulated flood depth">
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <Panel title="Route request">
            <div className="space-y-3">
              <CoordinateFields label="Origin" value={origin} onChange={setOrigin} />
              <CoordinateFields label="Destination" value={destination} onChange={setDestination} />
              <label className="block"><span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">Validated timestamp</span><select value={timestamp} onChange={(e) => setTimestamp(e.target.value)} className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"><option value="">Select timestamp</option>{sim.timestamps.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              <button
                onClick={find}
                disabled={computing || !canRequest || sim.apiStatus?.available_data_products.p8 !== true}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary py-3 text-sm font-bold tracking-wide text-primary-foreground uppercase hover:bg-primary/90 disabled:opacity-60"
              >
                <Navigation className="size-4" />
                {computing ? "Evaluating road risk…" : "Find Safer Route"}
              </button>
            </div>
          </Panel>

          {safer || direct ? (
            <>
              {routeCard(safer, "Flood-aware route")}
              {routeCard(direct, "Baseline route")}

              <div className="flex items-start gap-2 rounded-md border border-border bg-panel p-3 text-xs text-muted-foreground">
                <Info className="mt-0.5 size-4 shrink-0 text-primary" />
                <p>
                  Route results are returned by the validated P8 routing implementation. They are advisory and must be verified by field teams before dispatch.
                </p>
              </div>
            </>
          ) : (
            <Panel title="Result">
              <p className="text-sm text-muted-foreground">
                Enter coordinates and a validated timestamp, then request both routing modes from P9.
              </p>
            </Panel>
          )}
          {sim.routeError ? <p className="rounded-md border border-status-down/40 bg-status-down/10 p-3 text-xs text-status-down">{sim.routeError}</p> : null}
          {sim.routeStatus === "unavailable" ? <p className="rounded-md border border-status-warn/40 bg-status-warn/10 p-3 text-xs text-status-warn">Validated P8 routing is unavailable.</p> : null}
        </div>

        <Panel title="Route overlay" bodyClassName="p-0">
          <MapSurface className="h-[640px]" showRoutes={sim.routeShown} zoom={13} />
        </Panel>
      </div>
    </AppShell>
  );
}

function CoordinateFields({ label, value, onChange }: { label: string; value: { latitude: string; longitude: string }; onChange: (value: { latitude: string; longitude: string }) => void }) {
  return <fieldset className="grid grid-cols-2 gap-2"><legend className="col-span-2 text-[11px] tracking-[0.1em] text-muted-foreground uppercase">{label}</legend><input required type="number" step="any" placeholder="Latitude" value={value.latitude} onChange={(e) => onChange({ ...value, latitude: e.target.value })} className="rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none" /><input required type="number" step="any" placeholder="Longitude" value={value.longitude} onChange={(e) => onChange({ ...value, longitude: e.target.value })} className="rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none" /></fieldset>;
}


