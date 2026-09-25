import { ChevronDown, ChevronUp, Layers, Pause, Play, X } from "lucide-react";
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
  { label: "0 – 10 cm", sub: "Low / no significant flooding", risk: "low" as const },
  { label: "10 – 30 cm", sub: "Moderate — passable with caution", risk: "moderate" as const },
  { label: "30 – 50 cm", sub: "High — light vehicles at risk", risk: "high" as const },
  { label: "> 50 cm", sub: "Severe — impassable / evacuate", risk: "severe" as const },
];

export function MapPage() {
  const sim = useSim();
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const [layersPanelOpen, setLayersPanelOpen] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);

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
      <div className="relative h-full w-full">
        {/* ── Full-bleed map ── */}
        <MapSurface className="absolute inset-0" layers={layers} padding={[48, 48, 80, 48]} />

        {/* ── Floating Layer toggle ── */}
        <button
          onClick={() => setLayersPanelOpen((v) => !v)}
          className="fo-floating absolute top-3 left-3 z-1000 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-foreground/90 shadow-lg transition-colors hover:bg-white/8"
          aria-label="Toggle layer controls"
        >
          <Layers className="size-4 text-primary" />
          Layers
        </button>

        {/* ── Floating Layer panel ── */}
        {layersPanelOpen && (
          <div className="fo-floating absolute top-12 left-3 z-1000 w-56 rounded-lg p-3 shadow-xl">
            <div className="flex items-center justify-between pb-2">
              <span className="text-xs font-semibold text-foreground/85">Map Layers</span>
              <button onClick={() => setLayersPanelOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="size-3.5" />
              </button>
            </div>
            <div className="space-y-1">
              {LAYER_LABELS.map((l) => (
                <label
                  key={l.key}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded px-2 py-1.5 text-xs hover:bg-white/5"
                >
                  <span className="text-foreground/80">{l.label}</span>
                  <input
                    type="checkbox"
                    checked={layers[l.key]}
                    onChange={(e) =>
                      setLayers((prev) => ({ ...prev, [l.key]: e.target.checked }))
                    }
                    className="size-3.5 accent-[var(--primary)]"
                  />
                </label>
              ))}
            </div>
          </div>
        )}

        {/* ── Floating Depth Legend (bottom-right) ── */}
        <div className="fo-floating absolute right-3 bottom-20 z-1000 w-44 rounded-lg px-3 py-2.5 shadow-lg">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-foreground/70">Flood depth</p>
          <ul className="space-y-1.5">
            {DEPTH_LEGEND.map((d) => (
              <li key={d.risk} className="flex items-center gap-2">
                <span
                  className="size-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: RISK_COLOR[d.risk] }}
                />
                <span className="text-[11px] text-muted-foreground">{d.label}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* ── Floating feature inspector (top-right) ── */}
        {selected ? (
          <div className="fo-floating absolute top-3 right-3 z-1000 w-72 rounded-lg p-3.5 shadow-xl">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{selected.kind}</p>
                <h3 className="mt-0.5 text-sm font-semibold leading-snug">{selected.name}</h3>
              </div>
              <button onClick={() => sim.setSelected(null)} className="text-muted-foreground hover:text-foreground">
                <X className="size-3.5" />
              </button>
            </div>
            <div className="mt-2.5 flex items-end justify-between rounded-md bg-white/4 px-3 py-2">
              <div>
                <p className="text-[10px] text-muted-foreground">Flood depth</p>
                <p className="text-xl font-semibold tabular">{selected.depth} cm</p>
              </div>
              <RiskBadge risk={selected.risk} />
            </div>
            <dl className="mt-2.5 space-y-1.5 text-xs">
              {selected.rows.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="text-right font-medium tabular">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : (
          <div className="fo-floating absolute top-3 right-3 z-1000 max-w-56 rounded-lg px-3 py-2 text-xs text-muted-foreground shadow-lg">
            Click any road, flood zone or facility on the map to inspect depth and risk.
          </div>
        )}

        {/* ── Floating timeline bar (bottom) ── */}
        <div className="fo-floating absolute right-3 bottom-3 left-3 z-1000 rounded-lg shadow-xl">
          {/* Compact bar */}
          <div className="flex items-center gap-3 px-3 py-2">
            <button
              onClick={sim.togglePlay}
              className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground"
              aria-label={sim.playing ? "Pause timeline" : "Play timeline"}
            >
              {sim.playing ? <Pause className="size-3" /> : <Play className="size-3" />}
            </button>
            <span className="text-[11px] text-muted-foreground tabular whitespace-nowrap">
              {sim.timestamps[0] ?? "00:00"}
            </span>
            <input
              type="range"
              min={0}
              max={Math.max(0, sim.timestamps.length - 1)}
              step={1}
              value={Math.max(0, sim.timestamps.indexOf(sim.selectedTimestamp ?? ""))}
              onChange={(e) => {
                const timestamp = sim.timestamps[Number(e.target.value)];
                if (timestamp) sim.setSelectedTimestamp(timestamp);
              }}
              className="h-1 flex-1 accent-[var(--primary)]"
              aria-label="Simulation timeline"
            />
            <span className="text-[11px] text-muted-foreground tabular whitespace-nowrap">
              {sim.timestamps.at(-1) ?? "03:00"}
            </span>
            <span className="rounded bg-white/6 px-2 py-0.5 text-xs font-medium tabular">
              T+{sim.selectedTimestamp ?? "00:00"}
            </span>
            <button
              onClick={() => setTimelineExpanded((v) => !v)}
              className="text-muted-foreground hover:text-foreground"
              aria-label={timelineExpanded ? "Collapse stats" : "Expand stats"}
            >
              {timelineExpanded ? <ChevronDown className="size-3.5" /> : <ChevronUp className="size-3.5" />}
            </button>
          </div>

          {/* Expanded stats row */}
          {timelineExpanded && (
            <div className="grid grid-cols-3 gap-3 border-t border-white/5 px-3 py-2 text-xs md:grid-cols-6">
              <Stat label="Timestamp" value={sim.selectedTimestamp ?? "—"} />
              <Stat label="Rainfall" value={`${sim.metrics.rainfallNow} mm/hr`} />
              <Stat label="Accumulated" value={`${sim.metrics.accumulatedRainfallMm} mm`} />
              <Stat label="Affected area" value={`${sim.metrics.affectedAreaKm2.toFixed(1)} km²`} />
              <Stat label="Max depth" value={`${sim.metrics.maxDepthCm.toFixed(1)} cm`} />
              <div>
                <p className="text-[10px] text-muted-foreground">Overall risk</p>
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
          )}
        </div>
      </div>
    </AppShell>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular">{value}</p>
    </div>
  );
}
