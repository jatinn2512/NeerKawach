import { ChevronDown, ChevronUp, Layers, Map as MapIcon, Pause, Play, Satellite, Search, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { MapSurface } from "@/components/MapSurface";
import { RiskBadge } from "@/components/RiskUI";
import { DEFAULT_LAYERS, type MapLayers } from "@/components/map-layers";
import { RISK_COLOR, RISK_LABEL } from "@/data/pilot";
import { NEARBY_AREAS } from "@/data/demo";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

/* ── Layer definitions with color indicators ── */

const LAYER_LABELS: { key: keyof MapLayers; label: string; color: string; shape: "circle" | "square" }[] = [
  { key: "floodRisk", label: "Flood risk zones", color: "#ff7a45", shape: "square" },
  { key: "floodDepth", label: "Flood depth shading", color: "#3fa9f5", shape: "square" },
  { key: "roads", label: "Roads", color: "#5d7489", shape: "square" },
  { key: "drainage", label: "Drainage network", color: "#4f9fe0", shape: "square" },
  { key: "infrastructure", label: "Critical infrastructure", color: "#38bdf8", shape: "circle" },
  { key: "evacuation", label: "Evacuation centres", color: "#a3e635", shape: "circle" },
];

const DEPTH_LEGEND = [
  { label: "0 – 10 cm", sub: "Low", risk: "low" as const },
  { label: "10 – 30 cm", sub: "Moderate", risk: "moderate" as const },
  { label: "30 – 50 cm", sub: "High", risk: "high" as const },
  { label: "> 50 cm", sub: "Severe", risk: "severe" as const },
];

/* ── Local search index ── */

const SEARCH_LOCATIONS = [
  { label: "Bellandur", lat: 12.9312, lon: 77.6742, zoom: 15 },
  { label: "Bellandur Lake", lat: 12.9310, lon: 77.6780, zoom: 15 },
  { label: "Devarabeesanahalli", lat: 12.9368, lon: 77.6812, zoom: 15 },
  { label: "Kadubeesanahalli", lat: 12.9452, lon: 77.6698, zoom: 15 },
  { label: "Marathahalli", lat: 12.9482, lon: 77.6642, zoom: 15 },
  { label: "Koramangala", lat: 12.9350, lon: 77.6150, zoom: 15 },
  { label: "HSR Layout", lat: 12.9118, lon: 77.6528, zoom: 15 },
  { label: "Sarjapur Road", lat: 12.9078, lon: 77.6712, zoom: 15 },
  { label: "Agara", lat: 12.9242, lon: 77.6412, zoom: 15 },
  { label: "Doddanekundi", lat: 12.9508, lon: 77.6588, zoom: 15 },
  { label: "Ejipura", lat: 12.9380, lon: 77.6250, zoom: 15 },
  { label: "Iblur", lat: 12.9268, lon: 77.6680, zoom: 15 },
  { label: "Kaikondrahalli", lat: 12.9180, lon: 77.6780, zoom: 15 },
];

export function MapPage() {
  const sim = useSim();
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_LAYERS);
  const [layersPanelOpen, setLayersPanelOpen] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [basemap, setBasemap] = useState<"dark" | "satellite">("dark");
  const searchRef = useRef<HTMLInputElement>(null);

  const searchResults = searchQuery.length >= 2
    ? SEARCH_LOCATIONS.filter((loc) => loc.label.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  const handleSearchSelect = useCallback((loc: typeof SEARCH_LOCATIONS[0]) => {
    // Pan map to location via the simulation's setSelected mechanism
    // For now we just pan — the MapSurface handles bounds
    setSearchQuery(loc.label);
    setSearchOpen(false);
    // We'll emit a custom event that FloodMapView listens to
    window.dispatchEvent(new CustomEvent("fo-map-pan", { detail: { lat: loc.lat, lon: loc.lon, zoom: loc.zoom } }));
  }, []);

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
        <MapSurface className="absolute inset-0" layers={layers} padding={[56, 48, 80, 48]} basemap={basemap} />

        {/* ── Floating search bar (top-center) ── */}
        <div className="absolute top-3 left-1/2 z-1000 w-72 -translate-x-1/2">
          <div className="fo-floating flex items-center gap-2 rounded-lg px-3 py-2 shadow-lg">
            <Search className="size-3.5 shrink-0 text-muted-foreground" />
            <input
              ref={searchRef}
              type="text"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setSearchOpen(true); }}
              onFocus={() => setSearchOpen(true)}
              placeholder="Search location..."
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/60"
            />
            {searchQuery && (
              <button onClick={() => { setSearchQuery(""); setSearchOpen(false); }} className="text-muted-foreground hover:text-foreground">
                <X className="size-3" />
              </button>
            )}
          </div>
          {searchOpen && searchResults.length > 0 && (
            <ul className="fo-floating mt-1 max-h-52 overflow-y-auto rounded-lg py-1 shadow-xl">
              {searchResults.map((loc) => (
                <li key={loc.label}>
                  <button
                    onClick={() => handleSearchSelect(loc)}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground/80 hover:bg-white/6"
                  >
                    <Search className="size-3 shrink-0 text-muted-foreground" />
                    {loc.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── Floating Map / Satellite + Layers control group (top-left) ── */}
        <div className="absolute top-3 left-3 z-1000 flex items-center gap-1.5">
          <div className="fo-floating flex items-center overflow-hidden rounded-lg shadow-lg">
            <button
              onClick={() => setBasemap("dark")}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-2 text-xs font-medium transition-colors",
                basemap === "dark" ? "bg-white/10 text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-white/5"
              )}
            >
              <MapIcon className="size-3.5" /> Map
            </button>
            <button
              onClick={() => setBasemap("satellite")}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-2 text-xs font-medium transition-colors",
                basemap === "satellite" ? "bg-white/10 text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-white/5"
              )}
            >
              <Satellite className="size-3.5" /> Satellite
            </button>
          </div>
          <button
            onClick={() => setLayersPanelOpen((v) => !v)}
            className={cn(
              "fo-floating flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-medium shadow-lg transition-colors",
              layersPanelOpen ? "bg-white/10 text-foreground" : "text-foreground/80 hover:bg-white/5"
            )}
          >
            <Layers className="size-3.5 text-primary" /> Layers
          </button>
        </div>

        {/* ── Floating Layer panel ── */}
        {layersPanelOpen && (
          <div className="fo-floating absolute top-14 left-3 z-1000 w-60 rounded-lg p-3 shadow-xl">
            <div className="flex items-center justify-between pb-2">
              <span className="text-xs font-semibold text-foreground/85">Map Layers</span>
              <button onClick={() => setLayersPanelOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="size-3.5" />
              </button>
            </div>
            <div className="space-y-0.5">
              {LAYER_LABELS.map((l) => (
                <label
                  key={l.key}
                  className="flex cursor-pointer items-center gap-2.5 rounded px-2 py-1.5 text-sm hover:bg-white/5"
                >
                  <span
                    className={cn("size-2.5 shrink-0", l.shape === "circle" ? "rounded-full" : "rounded-sm")}
                    style={{ backgroundColor: l.color }}
                  />
                  <span className="flex-1 text-foreground/80">{l.label}</span>
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
        <div className="fo-floating absolute right-3 bottom-20 z-1000 w-40 rounded-lg px-3 py-2 shadow-lg">
          <p className="mb-1.5 text-[11px] font-semibold text-foreground/70">Flood depth</p>
          <ul className="space-y-1">
            {DEPTH_LEGEND.map((d) => (
              <li key={d.risk} className="flex items-center gap-2">
                <span
                  className="size-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: RISK_COLOR[d.risk] }}
                />
                <span className="text-xs text-muted-foreground">{d.label}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* ── Floating feature inspector (top-right) ── */}
        {selected ? (
          <div className="fo-floating absolute top-3 right-3 z-1000 w-72 rounded-lg p-3.5 shadow-xl">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{selected.kind}</p>
                <h3 className="mt-0.5 text-sm font-semibold leading-snug">{selected.name}</h3>
              </div>
              <button onClick={() => sim.setSelected(null)} className="text-muted-foreground hover:text-foreground">
                <X className="size-3.5" />
              </button>
            </div>
            <div className="mt-2.5 flex items-end justify-between rounded-md bg-white/4 px-3 py-2">
              <div>
                <p className="text-[11px] text-muted-foreground">Flood depth</p>
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
          <div className="flex items-center gap-3 px-3 py-2">
            <button
              onClick={sim.togglePlay}
              className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground"
              aria-label={sim.playing ? "Pause timeline" : "Play timeline"}
            >
              {sim.playing ? <Pause className="size-3" /> : <Play className="size-3" />}
            </button>
            <span className="text-xs text-muted-foreground tabular whitespace-nowrap">
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
            <span className="text-xs text-muted-foreground tabular whitespace-nowrap">
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

          {timelineExpanded && (
            <div className="grid grid-cols-3 gap-3 border-t border-white/5 px-3 py-2 text-xs md:grid-cols-6">
              <Stat label="Timestamp" value={sim.selectedTimestamp ?? "—"} />
              <Stat label="Rainfall" value={`${sim.metrics.rainfallNow} mm/hr`} />
              <Stat label="Accumulated" value={`${sim.metrics.accumulatedRainfallMm} mm`} />
              <Stat label="Affected area" value={`${sim.metrics.affectedAreaKm2.toFixed(1)} km²`} />
              <Stat label="Max depth" value={`${sim.metrics.maxDepthCm.toFixed(1)} cm`} />
              <div>
                <p className="text-[11px] text-muted-foreground">Overall risk</p>
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
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular">{value}</p>
    </div>
  );
}
