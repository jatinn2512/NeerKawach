import { CheckCircle2, Info, Navigation } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { DepthLegend } from "@/components/DepthLegend";
import { MapSurface } from "@/components/MapSurface";
import { Panel, RiskBadge, riskText } from "@/components/RiskUI";
import { NEARBY_AREAS, generateRouteForPair, type NearbyArea } from "@/data/demo";
import { depthToRisk } from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

const selectClass = "mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none focus:border-primary/60";

export function SaferRoutesPage() {
  const sim = useSim();
  const [originId, setOriginId] = useState(NEARBY_AREAS[0]!.id);
  const [destinationId, setDestinationId] = useState(NEARBY_AREAS[3]!.id);
  const [timestamp, setTimestamp] = useState(sim.selectedTimestamp ?? "00:00");
  const [computing, setComputing] = useState(false);
  const canRequest = Boolean(timestamp && originId && destinationId && originId !== destinationId);

  useEffect(() => {
    if (sim.selectedTimestamp) setTimestamp(sim.selectedTimestamp);
  }, [sim.selectedTimestamp]);

  async function find() {
    if (!canRequest) return;
    const origin = NEARBY_AREAS.find((a) => a.id === originId) ?? NEARBY_AREAS[0]!;
    const destination = NEARBY_AREAS.find((a) => a.id === destinationId) ?? NEARBY_AREAS[3]!;
    setComputing(true);

    // Generate deterministic routes for this origin-destination pair
    const baselineResult = generateRouteForPair(origin, destination, "baseline", timestamp);
    const floodAwareResult = generateRouteForPair(origin, destination, "flood-aware", timestamp);

    // Use requestRoute which clears previous routes first (baseline mode triggers clear)
    const baseRequest = {
      origin_latitude: origin.coordinates[0],
      origin_longitude: origin.coordinates[1],
      destination_latitude: destination.coordinates[0],
      destination_longitude: destination.coordinates[1],
      simulation_timestamp: timestamp,
      routing_mode: "baseline" as const,
    };
    // The requestRoute call with "baseline" will clear old routes
    await sim.requestRoute(baseRequest);
    // Then call flood-aware
    await sim.requestRoute({ ...baseRequest, routing_mode: "flood-aware" });

    setComputing(false);
  }

  const safer = sim.routeResults.floodAware;
  const direct = sim.routeResults.baseline;
  const originArea = NEARBY_AREAS.find((a) => a.id === originId);
  const destArea = NEARBY_AREAS.find((a) => a.id === destinationId);

  const depthCell = (depthM: number | undefined) => {
    if (depthM == null) return "—";
    const cm = depthM * 100;
    return <span className={riskText[depthToRisk(cm)]}>{cm.toFixed(1)} cm</span>;
  };

  return (
    <AppShell fill title="Safer Routes" subtitle="Flood-aware routing for the active Bellandur event">
      <div className="grid gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-3 xl:min-h-0 xl:overflow-y-auto">
          {/* Route request form */}
          <div className="rounded-lg border border-white/4 bg-card px-4 py-3">
            <h2 className="text-sm font-semibold">Route request</h2>
            <div className="mt-3 space-y-3">
              <label className="block">
                <span className="text-xs text-muted-foreground">Origin</span>
                <select value={originId} onChange={(e) => setOriginId(e.target.value)} className={selectClass}>
                  {NEARBY_AREAS.map((a) => (
                    <option key={a.id} value={a.id} disabled={a.id === destinationId}>{a.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-muted-foreground">Destination</span>
                <select value={destinationId} onChange={(e) => setDestinationId(e.target.value)} className={selectClass}>
                  {NEARBY_AREAS.map((a) => (
                    <option key={a.id} value={a.id} disabled={a.id === originId}>{a.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-muted-foreground">Flood timeline</span>
                <select value={timestamp} onChange={(e) => setTimestamp(e.target.value)} className={selectClass}>
                  {sim.timestamps.map((v) => (
                    <option key={v} value={v}>T+{v}</option>
                  ))}
                </select>
              </label>
              <button
                onClick={find}
                disabled={computing || !canRequest}
                className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
              >
                <Navigation className="size-4" />
                {computing ? "Evaluating road risk…" : "Find Safe Route"}
              </button>
            </div>
          </div>

          {/* Route result */}
          {safer || direct ? (
            <div className="rounded-lg border border-white/4 bg-card px-4 py-3">
              <div className="flex items-center justify-between">
                <h2 className={cn("flex items-center gap-2 text-sm font-semibold", safer && "text-status-ok")}>
                  {safer ? <><CheckCircle2 className="size-4" /> Safe route ready</> : "Evaluating routes…"}
                </h2>
                {safer && <RiskBadge risk="moderate" label="Lower risk" />}
              </div>

              {/* Route summary */}
              {(originArea || destArea) && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {originArea?.label ?? "Origin"} → {destArea?.label ?? "Destination"}
                </p>
              )}

              <table className="mt-2 w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="pb-1.5 text-left font-normal" />
                    <th className="pb-1.5 text-right font-medium text-primary">Flood-aware</th>
                    <th className="pb-1.5 text-right font-medium">Direct</th>
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
                  <p className="mt-2 text-xs text-muted-foreground">{safer.via ?? "Via flood-aware corridor"}</p>
                  {safer.avoided_flooded_segments.length > 0 && (
                    <div className="mt-3 border-t border-border pt-2">
                      <p className="text-xs text-muted-foreground">Avoided high-risk segments</p>
                      <ul className="mt-1.5 space-y-1 text-xs">
                        {safer.avoided_flooded_segments.map((seg) => (
                          <li key={String(seg)} className="flex items-center gap-2">
                            <span className="size-1.5 shrink-0 rounded-full bg-risk-severe" />
                            {String(seg)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          ) : (
            <div className="rounded-lg border border-white/4 bg-card px-4 py-3">
              <h2 className="text-sm font-semibold">Result</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Choose an origin, destination and flood timeline to compare the direct and flood-aware corridors.
              </p>
            </div>
          )}

          {safer && (
            <p className="flex items-start gap-2 px-1 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0 text-primary" />
              Flood-aware route avoids the highest-risk segments in the selected flood state. Confirm passability with field teams before dispatch.
            </p>
          )}
        </div>

        {/* Map panel */}
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
      <td className="py-1.5 text-muted-foreground">{label}</td>
      <td className="py-1.5 text-right font-semibold">{safer}</td>
      <td className="py-1.5 text-right text-muted-foreground">{direct}</td>
    </tr>
  );
}
