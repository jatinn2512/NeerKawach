import { Layers, Pause, Play, X } from "lucide-react";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { RiskBadge } from "@/components/RiskUI";
import { DEFAULT_LAYERS, type MapLayers } from "@/components/map-layers";
import { RISK_COLOR, RISK_LABEL } from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

const LAYER_LABELS: { key: keyof MapLayers; label: string }[] = [
  { key: "floodRisk", label: "Flood risk zones" },
  { key: "floodDepth", label: "Flood depth shading" },
  { key: "roads", label: "Roads" },
  { key: "drainage", label: "Drainage network" },
  { key: "infrastructure", label: "Critical infrastructure" },
  { key: "evacuation", label: "Evacuation centres" },
];

const DEPTH_LEGEND = [
  { label: "0 – 10 cm · Low / no significant flooding", risk: "low" as const },
  { label: "10 – 30 cm · Moderate — passable with caution", risk: "moderate" as const },
  { label: "30 – 50 cm · High — light vehicles at risk", risk: "high" as const },
  { label: "> 50 cm · Severe — impassable / evacuate", risk: "severe" as const },
];

export function MapPage() {
  const sim = useSim();
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);

  const selected = (() => {
    if (!sim.selected) return null;
    if (sim.selected.kind === "road") {
      const r = sim.roads.find((x) => x.id === sim.selected!.id);
      return r
        ? {
            kind: "Road segment",
            name: r.name,
            depth: r.depthCm,
            risk: r.risk,
            rows: [
              ["Category", r.category],
              ["Length", `${r.lengthKm} km`],
              ["Status", r.risk === "severe" ? "Impassable — closed" : r.risk === "high" ? "High risk — restricted" : "Open"],
              ["Peak depth expected", `${Math.round(r.peakDepthCm * sim.scenario.factor)} cm at T+03:00`],
              ["Estimated time to peak", r.depthCm > 0 ? `T+0${Math.min(3, Math.ceil(r.onset + 1))}:30` : "—"],
            ] as [string, string][],
          }
        : null;
    }
    if (sim.selected.kind === "zone") {
      const z = sim.zones.find((x) => x.id === sim.selected!.id);
      return z
        ? {
            kind: "Flood zone",
            name: z.name,
            depth: z.depthCm,
            risk: z.risk,
            rows: [
              ["Ward", z.ward],
              ["Population exposed", z.population.toLocaleString("en-IN")],
              ["Onset", `T+0${Math.floor(z.onset)}:${String(Math.round((z.onset % 1) * 60)).padStart(2, "0")}`],
              ["Peak depth expected", `${Math.round(z.peakDepthCm * sim.scenario.factor)} cm`],
            ] as [string, string][],
          }
        : null;
    }
    const f = sim.facilities.find((x) => x.id === sim.selected!.id);
    return f
      ? {
          kind: f.type,
          name: f.name,
          depth: f.accessRoad?.depthCm ?? 0,
          risk: f.risk,
          rows: [
            ["Access road", f.accessRoad?.name ?? "—"],
            ["Access status", f.risk === "severe" ? "Blocked" : f.risk === "high" ? "At risk" : "Available"],
            ["Capacity", f.capacity ?? "—"],
          ] as [string, string][],
        }
      : null;
  })();

  return (
    <AppShell
      title="Interactive Flood Map"
      subtitle={`Bellandur, Bengaluru · 0–3 hour flood progression · T+${sim.selectedTimestamp ?? "00:00"}`}
      flush
    >
      <div className="relative flex h-full">
        <div className="w-72 shrink-0 overflow-y-auto border-r border-white/5 bg-card p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Layers className="size-4 text-muted-foreground" /> Map layers
          </h2>
          <div className="mt-3 space-y-1.5">
            {LAYER_LABELS.map((l) => (
              <label
                key={l.key}
                className="flex cursor-pointer items-center justify-between gap-3 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
              >
                {l.label}
                <input
                  type="checkbox"
                  checked={layers[l.key]}
                  onChange={(e) =>
                    setLayers((prev) => ({ ...prev, [l.key]: e.target.checked }))
                  }
                  className="size-4 accent-[var(--primary)]"
                />
              </label>
            ))}
          </div>

          <h2 className="mt-6 text-sm font-semibold">
            Flood depth legend
          </h2>
          <ul className="mt-3 space-y-2 text-xs">
            {DEPTH_LEGEND.map((d) => (
              <li key={d.risk} className="flex items-start gap-2">
                <span
                  className="mt-0.5 size-3 shrink-0 rounded-sm"
                  style={{ backgroundColor: RISK_COLOR[d.risk] }}
                />
                <span className="text-muted-foreground">{d.label}</span>
              </li>
            ))}
            <li className="flex items-start gap-2 pt-1">
              <span className="mt-0.5 h-1 w-3 shrink-0 rounded-sm bg-[#60a5fa]" />
              <span className="text-muted-foreground">Storm drainage network</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 size-3 shrink-0 rounded-full border-2 border-[#a3e635]" />
              <span className="text-muted-foreground">Evacuation centre</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 size-3 shrink-0 rounded-full border-2 border-[#38bdf8]" />
              <span className="text-muted-foreground">Critical infrastructure</span>
            </li>
          </ul>

          <p className="mt-6 border-t border-border pt-4 text-xs leading-relaxed text-muted-foreground">
            Colours represent simulated flood depth categories produced by the
            hydrodynamic model for the selected scenario — not observed
            conditions.
          </p>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          <MapSurface className="absolute inset-0" layers={layers} padding={[40, 40, 40, 40]} />

          {selected ? (
            <div className="absolute top-4 right-4 z-1000 w-80 rounded-lg bg-card/95 p-4 shadow-2xl backdrop-blur">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs text-muted-foreground">
                    {selected.kind}
                  </p>
                  <h3 className="text-sm font-semibold">{selected.name}</h3>
                </div>
                <button
                  onClick={() => sim.setSelected(null)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              </div>

              <div className="mt-3 flex items-end justify-between rounded-md bg-panel px-3 py-2.5">
                <div>
                  <p className="text-xs text-muted-foreground">
                    Flood depth
                  </p>
                  <p className="text-2xl font-semibold tabular">{selected.depth} cm</p>
                </div>
                <RiskBadge risk={selected.risk} />
              </div>

              <dl className="mt-3 space-y-2 text-xs">
                {selected.rows.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="text-right font-medium tabular">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : (
            <div className="absolute top-4 right-4 z-1000 w-64 rounded-md bg-card/85 px-3.5 py-2.5 text-xs text-muted-foreground shadow-lg backdrop-blur">
              Click any road, flood zone or facility on the map to inspect
              simulated depth and risk.
            </div>
          )}
        </div>

          <div className="shrink-0 border-t border-white/5 bg-card px-5 py-3">
            <div className="flex items-center gap-3">
              <button onClick={sim.togglePlay} className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground" aria-label={sim.playing ? "Pause timeline" : "Play timeline"}>{sim.playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}</button>
              <span className="text-xs text-muted-foreground tabular">Flood progression</span>
              <span className="text-xs text-muted-foreground tabular">{sim.timestamps[0] ?? "00:00"}</span>
              <input
                type="range"
                min={0}
                max={Math.max(0, sim.timestamps.length - 1)}
                step={1}
                value={Math.max(0, sim.timestamps.indexOf(sim.selectedTimestamp ?? ""))}
                onChange={(e) => { const timestamp = sim.timestamps[Number(e.target.value)]; if (timestamp) sim.setSelectedTimestamp(timestamp); }}
                className="h-1.5 flex-1 accent-[var(--primary)]"
                aria-label="Simulation timeline"
              />
              <span className="text-xs text-muted-foreground tabular">{sim.timestamps.at(-1) ?? "03:00"}</span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-6">
              <Stat label="Replay timestamp" value={sim.selectedTimestamp ?? "Unavailable"} />
              <Stat label="Rainfall intensity" value={`${sim.metrics.rainfallNow} mm/hr`} />
              <Stat label="Accumulated rainfall" value={`${sim.metrics.accumulatedRainfallMm} mm`} />
              <Stat label="Affected area" value={`${sim.metrics.affectedAreaKm2.toFixed(1)} km²`} />
              <Stat label="Max flood depth" value={`${sim.metrics.maxDepthCm.toFixed(1)} cm`} />
              <div>
                <p className="text-xs text-muted-foreground">
                  Overall risk
                </p>
                <p
                  className={cn(
                    "mt-0.5 text-sm font-semibold",
                    {
                      low: "text-risk-low",
                      moderate: "text-risk-moderate",
                      high: "text-risk-high",
                      severe: "text-risk-severe",
                    }[sim.metrics.overallRisk],
                  )}
                >
                  {sim.summary ? RISK_LABEL[sim.metrics.overallRisk] : "Unavailable"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular">{value}</p>
    </div>
  );
}


