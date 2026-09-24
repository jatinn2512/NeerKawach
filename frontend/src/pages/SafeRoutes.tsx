import { CheckCircle2, Info, Navigation } from "lucide-react";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { DEMO_DESTINATIONS, DEMO_ORIGINS } from "@/data/demo";
import { useSim } from "@/state/simulation";

export function SaferRoutesPage() {
  const sim = useSim();
  const [originId, setOriginId] = useState(DEMO_ORIGINS[1]?.id ?? DEMO_ORIGINS[0]!.id);
  const [destinationId, setDestinationId] = useState(DEMO_DESTINATIONS[0]!.id);
  const [timestamp, setTimestamp] = useState(sim.selectedTimestamp ?? "00:00");
  const [computing, setComputing] = useState(false);
  const canRequest = Boolean(timestamp && originId && destinationId && originId !== destinationId);

  useEffect(() => {
    if (sim.selectedTimestamp) setTimestamp(sim.selectedTimestamp);
  }, [sim.selectedTimestamp]);

  async function find() {
    if (!canRequest) return;
    const origin = DEMO_ORIGINS.find((place) => place.id === originId) ?? DEMO_ORIGINS[0]!;
    const destination = DEMO_DESTINATIONS.find((place) => place.id === destinationId) ?? DEMO_DESTINATIONS[0]!;
    setComputing(true);
    const request = {
      origin_latitude: origin.coordinates[0],
      origin_longitude: origin.coordinates[1],
      destination_latitude: destination.coordinates[0],
      destination_longitude: destination.coordinates[1],
      simulation_timestamp: timestamp,
      routing_mode: "baseline" as const,
    };
    await sim.requestRoute(request);
    await sim.requestRoute({ ...request, routing_mode: "flood-aware" });
    setComputing(false);
  }

  const safer = sim.routeResults.floodAware;
  const direct = sim.routeResults.baseline;

  return (
    <AppShell title="Safer Routes" subtitle="Flood-aware routing for the active Bellandur event">
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <Panel title="Route request">
            <div className="space-y-3">
              <label className="block"><span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">Origin</span><select value={originId} onChange={(event) => setOriginId(event.target.value)} className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none">{DEMO_ORIGINS.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
              <label className="block"><span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">Destination</span><select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none">{DEMO_DESTINATIONS.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
              <label className="block"><span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">Flood timeline</span><select value={timestamp} onChange={(event) => setTimestamp(event.target.value)} className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none">{sim.timestamps.map((value) => <option key={value} value={value}>T+{value}</option>)}</select></label>
              <button onClick={find} disabled={computing || !canRequest} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary py-3 text-sm font-bold tracking-wide text-primary-foreground uppercase hover:bg-primary/90 disabled:opacity-60"><Navigation className="size-4" />{computing ? "Evaluating road risk…" : "Find Safe Route"}</button>
            </div>
          </Panel>

          {safer ? <Panel title="Recommended route"><div className="flex items-center gap-2 text-sm font-semibold text-status-ok"><CheckCircle2 className="size-4" /> Safe route ready <RiskBadge risk="moderate" label="Lower risk" className="ml-auto" /></div><dl className="mt-4 space-y-2 text-sm"><Row label="Distance" value={`${(safer.total_distance_m / 1000).toFixed(2)} km`} /><Row label="Estimated travel time" value={`${safer.estimated_travel_time_min ?? "—"} min`} /><Row label="Maximum flood depth" value={`${(safer.maximum_flood_depth_m * 100).toFixed(1)} cm`} /><Row label="Avoids flooded segments" value={`${safer.avoided_flooded_segments.length} high-risk segments`} /><Row label="Via" value={safer.via ?? "Flood-aware corridor"} /></dl></Panel> : null}
          {direct ? <Panel title="Direct route comparison"><dl className="space-y-2 text-sm"><Row label="Distance" value={`${(direct.total_distance_m / 1000).toFixed(2)} km`} /><Row label="Estimated travel time" value={`${direct.estimated_travel_time_min ?? "—"} min`} /><Row label="Maximum flood depth" value={`${(direct.maximum_flood_depth_m * 100).toFixed(1)} cm`} /><Row label="Affected segments" value={`${direct.affected_segments.length}`} /></dl><div className="mt-3"><StatusPill status="High risk corridor" /></div></Panel> : null}
          {!safer && !direct ? <Panel title="Result"><p className="text-sm text-muted-foreground">Choose an origin, destination and flood timeline to compare the direct and flood-aware corridors.</p></Panel> : null}
          {safer ? <div className="flex items-start gap-2 rounded-md border border-border bg-panel p-3 text-xs text-muted-foreground"><Info className="mt-0.5 size-4 shrink-0 text-primary" /><p>Flood-aware route avoids the highest-risk segments in the selected flood state. Confirm passability with field teams before dispatch.</p></div> : null}
        </div>

        <Panel title="Route overlay" bodyClassName="p-0"><MapSurface className="h-[640px]" showRoutes={sim.routeShown} zoom={13} /></Panel>
      </div>
    </AppShell>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3 border-b border-border/60 pb-2 last:border-0"><dt className="text-muted-foreground">{label}</dt><dd className="text-right font-medium tabular">{value}</dd></div>;
}
