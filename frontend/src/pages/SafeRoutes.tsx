import { CheckCircle2, Info, Navigation } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { DepthLegend } from "@/components/DepthLegend";
import { MapSurface } from "@/components/MapSurface";
import { Panel, RiskBadge, riskText } from "@/components/RiskUI";
import { DEMO_DESTINATIONS, DEMO_ORIGINS } from "@/data/demo";
import { depthToRisk } from "@/data/pilot";
import { useSim } from "@/state/simulation";

const selectClass = "mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none focus:border-primary/60";

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
  const depthCell = (depthM: number | undefined) => {
    if (depthM == null) return "—";
    const cm = depthM * 100;
    return <span className={riskText[depthToRisk(cm)]}>{cm.toFixed(1)} cm</span>;
  };

  return (
    <AppShell fill title="Safer Routes" subtitle="Flood-aware routing for the active Bellandur event">
      <div className="grid gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4 xl:min-h-0 xl:overflow-y-auto">
          <Panel title="Route request">
            <div className="space-y-3">
              <label className="block"><span className="text-xs text-muted-foreground">Origin</span><select value={originId} onChange={(event) => setOriginId(event.target.value)} className={selectClass}>{DEMO_ORIGINS.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
              <label className="block"><span className="text-xs text-muted-foreground">Destination</span><select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} className={selectClass}>{DEMO_DESTINATIONS.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
              <label className="block"><span className="text-xs text-muted-foreground">Flood timeline</span><select value={timestamp} onChange={(event) => setTimestamp(event.target.value)} className={selectClass}>{sim.timestamps.map((value) => <option key={value} value={value}>T+{value}</option>)}</select></label>
              <button onClick={find} disabled={computing || !canRequest} className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"><Navigation className="size-4" />{computing ? "Evaluating road risk…" : "Find Safe Route"}</button>
            </div>
          </Panel>

          {safer || direct ? (
            <Panel
              title={safer ? <span className="flex items-center gap-2 text-status-ok"><CheckCircle2 className="size-4" /> Safe route ready</span> : "Evaluating routes…"}
              action={safer ? <RiskBadge risk="moderate" label="Lower risk" /> : null}
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="pb-2 text-left font-normal" />
                    <th className="pb-2 text-right font-medium text-primary">Flood-aware</th>
                    <th className="pb-2 text-right font-medium">Direct</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  <Row label="Distance" safer={safer ? `${(safer.total_distance_m / 1000).toFixed(2)} km` : "—"} direct={direct ? `${(direct.total_distance_m / 1000).toFixed(2)} km` : "—"} />
                  <Row label="Travel time" safer={`${safer?.estimated_travel_time_min ?? "—"} min`} direct={`${direct?.estimated_travel_time_min ?? "—"} min`} />
                  <Row label="Max flood depth" safer={depthCell(safer?.maximum_flood_depth_m)} direct={depthCell(direct?.maximum_flood_depth_m)} />
                  <Row
                    label="Flooded segments"
                    safer={safer ? `avoids ${safer.avoided_flooded_segments.length}` : "—"}
                    direct={direct ? <span className="text-risk-severe">{direct.affected_segments.length} affected</span> : "—"}
                  />
                </tbody>
              </table>
              {safer ? (
                <>
                  <p className="mt-3 text-xs text-muted-foreground">
                    {safer.via ?? "Via flood-aware corridor"}
                  </p>
                  {safer.avoided_flooded_segments.length ? (
                    <div className="mt-4 border-t border-border pt-3">
                      <p className="text-xs text-muted-foreground">Avoided high-risk segments</p>
                      <ul className="mt-2 space-y-1.5 text-sm">
                        {safer.avoided_flooded_segments.map((segment) => (
                          <li key={String(segment)} className="flex items-center gap-2">
                            <span className="size-1.5 shrink-0 rounded-full bg-risk-severe" />
                            {String(segment)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : null}
            </Panel>
          ) : (
            <Panel title="Result">
              <p className="text-sm text-muted-foreground">Choose an origin, destination and flood timeline to compare the direct and flood-aware corridors.</p>
            </Panel>
          )}
          {safer ? (
            <p className="flex items-start gap-2 px-1 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0 text-primary" />
              Flood-aware route avoids the highest-risk segments in the selected flood state. Confirm passability with field teams before dispatch.
            </p>
          ) : null}
        </div>

        <Panel
          className="flex min-h-140 flex-col overflow-hidden"
          title="Route overlay"
          action={
            <span className="flex items-center gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="h-1 w-5 rounded-full bg-[#22d3ee]" /> Flood-aware route</span>
              <span className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-[#ff5a67]" /> Direct route</span>
            </span>
          }
          bodyClassName="relative min-h-0 flex-1 p-0"
        >
          <MapSurface className="absolute inset-0" showRoutes={sim.routeShown} focus="route" padding={[64, 56, 48, 56]} />
          <DepthLegend className="absolute top-3 left-14 z-1000" />
        </Panel>
      </div>
    </AppShell>
  );
}

function Row({ label, safer, direct }: { label: string; safer: ReactNode; direct: ReactNode }) {
  return (
    <tr className="border-t border-border/70">
      <td className="py-2 text-muted-foreground">{label}</td>
      <td className="py-2 text-right font-semibold">{safer}</td>
      <td className="py-2 text-right text-muted-foreground">{direct}</td>
    </tr>
  );
}
