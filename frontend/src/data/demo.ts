import type {
  ApiStatus,
  GeoJson,
  HealthResponse,
  RainfallStatus,
  RouteResponse,
  RunRecord,
  StudyArea,
} from "@/api/client";
import {
  REGION,
  ROUTE_OPTIONS,
  RISK_LABEL,
  depthToRisk,
  type LatLng,
  type RiskLevel,
} from "./pilot";

export type DemoAlert = {
  id: string;
  title: string;
  detail: string;
  risk: RiskLevel;
};

export type DemoTimelinePoint = {
  label: string;
  rainfallMmHr: number;
  accumulatedRainfallMm: number;
  progression: number;
  maxDepthCm: number;
  affectedAreaKm2: number;
  affectedZones: number;
  affectedRoads: number;
  criticalAtRisk: number;
  alerts: DemoAlert[];
};

export const DEMO_TIMELINE: DemoTimelinePoint[] = [
  {
    label: "00:00",
    rainfallMmHr: 42,
    accumulatedRainfallMm: 0,
    progression: 0,
    maxDepthCm: 0,
    affectedAreaKm2: 0,
    affectedZones: 0,
    affectedRoads: 0,
    criticalAtRisk: 0,
    alerts: [{ id: "rain-start", title: "Heavy rainfall detected", detail: "Storm cell entering the Bellandur catchment.", risk: "moderate" }],
  },
  {
    label: "00:30",
    rainfallMmHr: 68,
    accumulatedRainfallMm: 18,
    progression: 0.18,
    maxDepthCm: 12,
    affectedAreaKm2: 0.9,
    affectedZones: 1,
    affectedRoads: 1,
    criticalAtRisk: 0,
    alerts: [
      { id: "rain-heavy", title: "Heavy rainfall detected", detail: "Rainfall intensity is above the local drainage design threshold.", risk: "moderate" },
      { id: "drainage-warning", title: "Drainage capacity warning", detail: "Primary storm drain is approaching surcharge in Ward 04.", risk: "moderate" },
    ],
  },
  {
    label: "01:00",
    rainfallMmHr: 92,
    accumulatedRainfallMm: 46,
    progression: 0.34,
    maxDepthCm: 28,
    affectedAreaKm2: 2.6,
    affectedZones: 2,
    affectedRoads: 2,
    criticalAtRisk: 1,
    alerts: [
      { id: "drainage-warning", title: "Drainage capacity warning", detail: "Runoff is exceeding conveyance capacity near Bellandur Lake Basin.", risk: "moderate" },
      { id: "road-hazard", title: "Road hazard detected", detail: "Water depth is rising on the Bellandur stretch of Outer Ring Road.", risk: "high" },
    ],
  },
  {
    label: "01:30",
    rainfallMmHr: 118,
    accumulatedRainfallMm: 82,
    progression: 0.5,
    maxDepthCm: 46,
    affectedAreaKm2: 5.1,
    affectedZones: 4,
    affectedRoads: 4,
    criticalAtRisk: 2,
    alerts: [
      { id: "depth-high", title: "High flood depth", detail: "Flood depth has crossed 30 cm in low-lying road segments.", risk: "high" },
      { id: "route-recalc", title: "Route recalculation required", detail: "The direct corridor now intersects high-risk segments.", risk: "high" },
    ],
  },
  {
    label: "02:00",
    rainfallMmHr: 105,
    accumulatedRainfallMm: 126,
    progression: 0.7,
    maxDepthCm: 65,
    affectedAreaKm2: 7.4,
    affectedZones: 5,
    affectedRoads: 6,
    criticalAtRisk: 3,
    alerts: [
      { id: "depth-severe", title: "Severe flood depth", detail: "Water depth exceeds 50 cm around the Bellandur basin.", risk: "severe" },
      { id: "road-closure", title: "Road hazard detected", detail: "Iblur Junction Ramp is not suitable for vehicle access.", risk: "severe" },
      { id: "route-recalc-2", title: "Route recalculation required", detail: "Use the flood-aware route to avoid closed segments.", risk: "high" },
    ],
  },
  {
    label: "02:30",
    rainfallMmHr: 86,
    accumulatedRainfallMm: 162,
    progression: 0.86,
    maxDepthCm: 79,
    affectedAreaKm2: 9.5,
    affectedZones: 6,
    affectedRoads: 8,
    criticalAtRisk: 4,
    alerts: [
      { id: "spillover", title: "Bellandur lake spillover channel active", detail: "Rapid accumulation is spreading through the Ward 04 low-lying basin.", risk: "severe" },
      { id: "route-recalc-3", title: "Route recalculation required", detail: "Flood-aware route avoids 5 high-risk segments.", risk: "high" },
    ],
  },
  {
    label: "03:00",
    rainfallMmHr: 62,
    accumulatedRainfallMm: 190,
    progression: 1,
    maxDepthCm: 92,
    affectedAreaKm2: 11.7,
    affectedZones: 7,
    affectedRoads: 10,
    criticalAtRisk: 5,
    alerts: [
      { id: "peak-depth", title: "Peak flood extent reached", detail: "Maximum modeled depth is 92 cm in Bellandur Lake Basin.", risk: "severe" },
      { id: "route-recalc-4", title: "Route recalculation required", detail: "Keep direct route closed; dispatch via the flood-aware corridor.", risk: "high" },
    ],
  },
];

export const DEMO_STUDY_AREA: StudyArea = {
  name: REGION.area,
  city: REGION.city,
  state: "Karnataka",
  country: "India",
  bbox: { min_lat: 12.905, min_lon: 77.60, max_lat: 12.955, max_lon: 77.69 },
  crs: REGION.crs,
  approximate_area_km2: REGION.coverageKm2,
  description: "Bellandur–Koramangala catchment pilot study area.",
};

export const DEMO_HEALTH: HealthResponse = {
  status: "ok",
  service: "FloodOps API",
  environment: "pilot",
  message: "FloodOps services operational",
};

export const DEMO_API_STATUS: ApiStatus = {
  api_status: "ok",
  project_name: "FloodOps",
  study_area: REGION.area,
  available_data_products: { p6: true, p7: true, p8: true },
  routing_capability: "Flood-aware routing available",
  latest_runs: [],
};

export const DEMO_RUNS: RunRecord[] = [
  { phase: "P6", product: "Coupled drainage outputs", timestamps: DEMO_TIMELINE.map((point) => point.label), generated_at_utc: "2026-09-24 06:30 UTC" },
  { phase: "P7", product: "Flood extent and road impact", timestamps: DEMO_TIMELINE.map((point) => point.label), generated_at_utc: "2026-09-24 06:34 UTC" },
  { phase: "P8", product: "Flood-aware safe route", timestamps: ["03:00"], generated_at_utc: "2026-09-24 06:35 UTC" },
];

export const DEMO_RAINFALL_SOURCES: Array<Record<string, unknown>> = [
  { source_id: "mosdac_insat_3dr", source_name: "MOSDAC INSAT-3DR", product: "3RIMG_L2B_IMC", role: "historical", status: "available", available: true, detail: "Historical satellite rainfall product" },
  { source_id: "open_meteo", source_name: "Open-Meteo", product: "Precipitation forecast", role: "current_forecast", status: "available", available: true, detail: "Current and forecast precipitation; model-based, not radar" },
  { source_id: "dwr", source_name: "DWR", product: "Reserved", role: "quantitative_nowcast", status: "unavailable", available: false, detail: "Unavailable / reserved for future integration" },
  { source_id: "rainviewer", source_name: "RainViewer", product: "Radar observation metadata", role: "radar_metadata", status: "metadata_only", available: true, detail: "Observation metadata only; not a quantitative 0–3 hour nowcast" },
];

export const DEMO_RAINFALL_STATUS: RainfallStatus = {
  mode: "historical",
  source_requested: "mosdac_insat_3dr",
  source_used: "mosdac_insat_3dr",
  source_name: "MOSDAC INSAT-3DR",
  source_role: "historical",
  fallback: false,
  fallback_reason: null,
  quantitative_priority: ["mosdac_insat_3dr"],
  sources: [
    { source_id: "mosdac_insat_3dr", status: "available", available: true, usable: true, product: "3RIMG_L2B_IMC", role: "historical", reason: "Historical satellite rainfall" },
    { source_id: "dwr", status: "unavailable", available: false, usable: false, product: "Reserved", role: "quantitative_nowcast", reason: "Unavailable / reserved" },
  ],
};

export const DEMO_CURRENT_RAINFALL_STATUS: RainfallStatus = {
  mode: "current_forecast",
  source_requested: "open_meteo",
  source_used: "open_meteo",
  source_name: "Open-Meteo",
  source_role: "model_forecast",
  fallback: false,
  fallback_reason: null,
  quantitative_priority: ["open_meteo"],
  sources: [
    { source_id: "open_meteo", status: "available", available: true, usable: true, product: "Precipitation forecast", role: "model_forecast", reason: "Current and forecast precipitation" },
    { source_id: "rainviewer", status: "metadata_only", available: true, usable: false, product: "Radar observation metadata", role: "radar_metadata", reason: "Metadata only; not a quantitative nowcast" },
  ],
};

/* ─── Nearby areas around Bellandur for safe-route selection ─── */

export type NearbyArea = {
  id: string;
  label: string;
  coordinates: LatLng;
};

export const NEARBY_AREAS: NearbyArea[] = [
  { id: "bellandur",           label: "Bellandur",             coordinates: [12.9312, 77.6742] },
  { id: "devarabeesanahalli",  label: "Devarabeesanahalli",    coordinates: [12.9368, 77.6812] },
  { id: "kadubeesanahalli",    label: "Kadubeesanahalli",      coordinates: [12.9452, 77.6698] },
  { id: "marathahalli",        label: "Marathahalli",          coordinates: [12.9482, 77.6642] },
  { id: "doddanekundi",        label: "Doddanekundi",          coordinates: [12.9508, 77.6588] },
  { id: "agara",               label: "Agara",                 coordinates: [12.9242, 77.6412] },
  { id: "hsr-layout",          label: "HSR Layout",            coordinates: [12.9118, 77.6528] },
  { id: "sarjapur",            label: "Sarjapur",              coordinates: [12.9078, 77.6712] },
];

// Keep old exports for backward compatibility but mark as deprecated.
export const DEMO_ORIGINS = NEARBY_AREAS;
export const DEMO_DESTINATIONS = NEARBY_AREAS;

/* ─── Deterministic route generation from origin/destination pair ─── */

/** Simple seeded hash so the same (origin,dest) pair always produces the same route. */
function pairSeed(a: string, b: string) {
  let h = 0;
  for (const c of `${a}→${b}`) h = (Math.imul(31, h) + c.charCodeAt(0)) | 0;
  return Math.abs(h);
}

function interpolate(a: LatLng, b: LatLng, steps: number, seed: number): LatLng[] {
  const pts: LatLng[] = [a];
  for (let i = 1; i <= steps; i++) {
    const t = i / (steps + 1);
    const jitter = ((seed * (i + 7)) % 97) / 97 * 0.006 - 0.003;
    pts.push([a[0] + (b[0] - a[0]) * t + jitter, a[1] + (b[1] - a[1]) * t - jitter * 0.6]);
  }
  pts.push(b);
  return pts;
}

function routeGeometry(path: LatLng[]): GeoJson {
  return { type: "Feature", geometry: { type: "LineString", coordinates: path.map(([latitude, longitude]) => [longitude, latitude]) }, properties: {} };
}

/** Produces a deterministic route response for any area pair. */
export function generateRouteForPair(
  origin: NearbyArea,
  destination: NearbyArea,
  mode: "baseline" | "flood-aware",
  timestamp: string,
): RouteResponse {
  const seed = pairSeed(origin.id, destination.id);
  const floodAware = mode === "flood-aware";

  // Deterministic numeric properties from the seed
  const baseDist = 2.8 + (seed % 60) / 10;    // 2.8 – 8.7 km
  const distKm = floodAware ? baseDist * 1.2 + 0.8 : baseDist;
  const travelMin = Math.round(floodAware ? distKm * 3.1 : distKm * 2.7);
  const maxDepthM = floodAware ? 0.04 + (seed % 20) / 100 : 0.25 + (seed % 50) / 100;
  const affectedCount = floodAware ? 1 : 2 + (seed % 4);
  const avoidedSegments = floodAware
    ? ["Outer Ring Road Bellandur Stretch", "Agara–Iblur Connector", "Iblur Junction Ramp"].slice(0, 1 + seed % 3)
    : [];

  // Generate a path with slight variation for flood-aware vs baseline
  const saferOffset: LatLng = floodAware ? [0.003, -0.004] : [0, 0];
  const pathOrigin: LatLng = origin.coordinates;
  const pathDest: LatLng = destination.coordinates;
  const midpoint: LatLng = [
    (pathOrigin[0] + pathDest[0]) / 2 + saferOffset[0],
    (pathOrigin[1] + pathDest[1]) / 2 + saferOffset[1],
  ];

  const path: LatLng[] = [
    pathOrigin,
    ...interpolate(pathOrigin, midpoint, 1, seed + (floodAware ? 42 : 0)).slice(1, -1),
    midpoint,
    ...interpolate(midpoint, pathDest, 1, seed + (floodAware ? 99 : 17)).slice(1, -1),
    pathDest,
  ];

  const via = floodAware
    ? `Via elevated corridor avoiding ${avoidedSegments.length} flooded segment${avoidedSegments.length > 1 ? "s" : ""}`
    : `Direct route via ${origin.label}–${destination.label} corridor`;

  return {
    status: "complete",
    routing_mode: mode,
    route_timestamp: timestamp,
    total_distance_m: Math.round(distKm * 1000),
    route_cost: distKm,
    maximum_flood_depth_m: Math.round(maxDepthM * 100) / 100,
    affected_segments: Array.from({ length: affectedCount }, (_, i) => `${mode}-segment-${i + 1}`),
    avoided_flooded_segments: avoidedSegments,
    geometry: routeGeometry(path),
    source_phase: "P8 flood-safe routing",
    estimated_travel_time_min: travelMin,
    route_name: floodAware ? "Safer Route" : "Direct Route",
    via,
  };
}

export const DEMO_ROUTE_RESULTS: Record<"baseline" | "flood-aware", RouteResponse> = {
  baseline: {
    status: "complete",
    routing_mode: "baseline",
    route_timestamp: "03:00",
    total_distance_m: ROUTE_OPTIONS[1].distanceKm * 1000,
    route_cost: ROUTE_OPTIONS[1].distanceKm,
    maximum_flood_depth_m: ROUTE_OPTIONS[1].maxDepthCm / 100,
    affected_segments: Array.from({ length: ROUTE_OPTIONS[1].highRiskSegments }, (_, index) => `direct-segment-${index + 1}`),
    avoided_flooded_segments: [],
    geometry: routeGeometry(ROUTE_OPTIONS[1].path),
    source_phase: "P8 flood-safe routing",
    estimated_travel_time_min: ROUTE_OPTIONS[1].travelMin,
    route_name: ROUTE_OPTIONS[1].label,
    via: ROUTE_OPTIONS[1].via,
  },
  "flood-aware": {
    status: "complete",
    routing_mode: "flood-aware",
    route_timestamp: "03:00",
    total_distance_m: ROUTE_OPTIONS[0].distanceKm * 1000,
    route_cost: ROUTE_OPTIONS[0].distanceKm,
    maximum_flood_depth_m: ROUTE_OPTIONS[0].maxDepthCm / 100,
    affected_segments: Array.from({ length: ROUTE_OPTIONS[0].highRiskSegments }, (_, index) => `safer-segment-${index + 1}`),
    avoided_flooded_segments: ["Outer Ring Road Bellandur Stretch", "Agara–Iblur Connector", "Iblur Junction Ramp"],
    geometry: routeGeometry(ROUTE_OPTIONS[0].path),
    source_phase: "P8 flood-safe routing",
    estimated_travel_time_min: ROUTE_OPTIONS[0].travelMin,
    route_name: ROUTE_OPTIONS[0].label,
    via: ROUTE_OPTIONS[0].via,
  },
};

export function timelinePoint(timestamp: string | null | undefined) {
  return DEMO_TIMELINE.find((point) => point.label === timestamp) ?? DEMO_TIMELINE[0];
}

export function timelineRisk(timestamp: string | null | undefined) {
  return depthToRisk(timelinePoint(timestamp).maxDepthCm);
}

export const DEMO_SUMMARY = {
  timestamps: DEMO_TIMELINE.map((point) => point.label),
  maximum_flood_depth: { value_m: DEMO_TIMELINE.at(-1)!.maxDepthCm / 100, timestamp: DEMO_TIMELINE.at(-1)!.label },
};

/* ─── SMS dispatch abstraction ─── */

export type SmsDispatchResult = {
  id: string;
  status: "accepted" | "failed";
  channel: "sms";
  recipientCount: number;
  area: string;
  severity: string;
  timestamp: string;
  providerNote: string;
};

/**
 * Dispatch abstraction — currently uses a local presentation adapter.
 * Replace the body with Twilio/MSG91/etc. to connect a real provider.
 */
export async function dispatchAlert(opts: {
  area: string;
  severity: string;
  message: string;
}): Promise<SmsDispatchResult> {
  // Simulate network latency
  await new Promise((r) => setTimeout(r, 900 + Math.random() * 600));

  // Deterministic recipient count based on area string
  let h = 0;
  for (const c of opts.area) h = (Math.imul(31, h) + c.charCodeAt(0)) | 0;
  const recipientCount = 120 + (Math.abs(h) % 180);

  return {
    id: `ALT-${new Date().getFullYear()}-${String(100 + Math.floor(Math.random() * 900))}`,
    status: "accepted",
    channel: "sms",
    recipientCount,
    area: opts.area,
    severity: opts.severity,
    timestamp: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
    providerNote: "Local presentation adapter — no external SMS provider configured.",
  };
}
