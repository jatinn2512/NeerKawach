import { Info, Navigation } from "lucide-react";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { Panel, RiskBadge } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

export function SaferRoutesPage() {
  const sim = useSim();
  const [from, setFrom] = useState("f1");
  const [to, setTo] = useState("f6");
  const [computing, setComputing] = useState(false);

  const safer = sim.routes.find((r) => r.id === "safer")!;
  const direct = sim.routes.find((r) => r.id === "direct")!;

  function find() {
    setComputing(true);
    setTimeout(() => {
      setComputing(false);
      sim.showRoutes();
    }, 900);
  }

  return (
    <AppShell title="Safer Routes" subtitle="Lower-risk routing based on simulated flood depth">
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <Panel title="Route request">
            <div className="space-y-3">
              <label className="block">
                <span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">From</span>
                <select
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"
                >
                  {sim.facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[11px] tracking-[0.1em] text-muted-foreground uppercase">To</span>
                <select
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"
                >
                  {sim.facilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                onClick={find}
                disabled={computing}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary py-3 text-sm font-bold tracking-wide text-primary-foreground uppercase hover:bg-primary/90 disabled:opacity-60"
              >
                <Navigation className="size-4" />
                {computing ? "Evaluating road risk…" : "Find Safer Route"}
              </button>
            </div>
          </Panel>

          {sim.routeShown ? (
            <>
              {[safer, direct].map((r) => (
                <Panel
                  key={r.id}
                  title={r.label}
                  className={cn(r.id === "safer" && "border-primary/50")}
                >
                  <p className="text-xs text-muted-foreground">{r.via}</p>
                  <dl className="mt-3 space-y-2 text-sm">
                    {[
                      ["Estimated distance", `${r.distanceKm} km`],
                      ["Estimated travel time", `${r.travelMin} min`],
                      ["High-risk segments", `${r.highRiskSegments}`],
                      ["Max flood depth on route", `${r.maxDepthCm} cm`],
                    ].map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">{k}</dt>
                        <dd className="font-medium tabular">{v}</dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-3">
                    <RiskBadge risk={r.risk} />
                  </div>
                </Panel>
              ))}

              <div className="flex items-start gap-2 rounded-md border border-border bg-panel p-3 text-xs text-muted-foreground">
                <Info className="mt-0.5 size-4 shrink-0 text-primary" />
                <p>
                  The lower-risk route is derived from simulated flood depth per
                  road segment. It is an advisory decision-support output and is
                  not guaranteed to be passable — verify with field teams before
                  dispatch.
                </p>
              </div>
            </>
          ) : (
            <Panel title="Result">
              <p className="text-sm text-muted-foreground">
                Select an origin and destination, then run the routing engine to
                compare the direct corridor with the lower-risk alternative.
              </p>
            </Panel>
          )}
        </div>

        <Panel title="Route overlay" bodyClassName="p-0">
          <MapSurface className="h-[640px]" showRoutes={sim.routeShown} zoom={13} />
        </Panel>
      </div>
    </AppShell>
  );
}


