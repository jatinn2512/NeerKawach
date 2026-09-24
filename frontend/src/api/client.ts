const API_BASE = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly payload: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init.headers },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload
      ? JSON.stringify(payload.detail)
      : `HTTP ${response.status}`;
    throw new ApiError(`FloodOps API request failed: ${detail}`, response.status, payload);
  }
  return payload as T;
}

export type HealthResponse = { status: "ok"; service: string; environment: string; message: string };
export type StudyArea = {
  name: string; city: string; state: string; country: string;
  bbox: { min_lat: number; min_lon: number; max_lat: number; max_lon: number };
  crs: string; approximate_area_km2: number; description?: string;
};
export type ApiStatus = {
  api_status: "ok"; project_name: string; study_area: string;
  available_data_products: { p6: boolean; p7: boolean; p8: boolean };
  routing_capability: string; latest_runs: RunRecord[];
};
export type RunRecord = { phase: string; product: string; timestamps: string[]; generated_at_utc?: string };
export type FloodSummary = {
  timestamps: string[];
  maximum_flood_depth?: { value_m: number; timestamp: string };
  [key: string]: unknown;
};
export type FloodTimeseries = {
  timestamp: string | null;
  units: { depth: string; area: string };
  rows: Array<Record<string, string | number | boolean | null>>;
};
export type GeoJson = { type: string; features?: unknown[]; geometry?: unknown; coordinates?: unknown; properties?: Record<string, unknown> };
export type RoadImpact = {
  timestamp: string | null; road_id: string | null; units: Record<string, string>;
  rows: Array<Record<string, string | number | boolean | null>>;
};
export type RainfallSources = { sources: Array<Record<string, unknown>> };
export type RainfallStatus = {
  mode?: string;
  source_requested?: string;
  source_used: string | null;
  source_name?: string | null;
  source_role?: string | null;
  fallback: boolean;
  fallback_reason: string | null;
  quantitative_priority: string[];
  sources: Array<{ source_id: string; status: string; available: boolean; usable?: boolean; product?: string; role?: string; reason?: string }>;
};
export type NowcastStatus = { available: boolean; mode: string; source: string | null; future_radar_nowcast: boolean; message: string };
export type RouteRequest = {
  origin_latitude: number; origin_longitude: number;
  destination_latitude: number; destination_longitude: number;
  simulation_timestamp: string; routing_mode: "baseline" | "flood-aware";
};
export type RouteResponse = {
  status: string; routing_mode: "baseline" | "flood-aware"; route_timestamp: string;
  total_distance_m: number; route_cost: number; maximum_flood_depth_m: number;
  affected_segments: unknown[]; avoided_flooded_segments: unknown[]; geometry: GeoJson; source_phase: string;
  estimated_travel_time_min?: number; route_name?: string; via?: string;
};

export const floodApi = {
  health: () => apiRequest<HealthResponse>("/health"),
  status: () => apiRequest<ApiStatus>("/api/status"),
  studyArea: () => apiRequest<StudyArea>("/api/study-area"),
  floodSummary: () => apiRequest<FloodSummary>("/api/flood/summary"),
  floodTimeseries: (timestamp?: string) => apiRequest<FloodTimeseries>(`/api/flood/timeseries${timestamp ? `?timestamp=${encodeURIComponent(timestamp)}` : ""}`),
  floodExtent: (timestamp?: string) => apiRequest<GeoJson>(`/api/flood/extent${timestamp ? `?timestamp=${encodeURIComponent(timestamp)}` : ""}`),
  maxDepth: () => apiRequest<Record<string, unknown>>("/api/flood/max-depth"),
  roadImpact: (timestamp?: string) => apiRequest<RoadImpact>(`/api/roads/impact${timestamp ? `?timestamp=${encodeURIComponent(timestamp)}` : ""}`),
  routes: (request: RouteRequest) => apiRequest<RouteResponse>("/api/routes", { method: "POST", body: JSON.stringify(request) }),
  runs: () => apiRequest<{ runs: RunRecord[] }>("/api/runs"),
  rainfallSources: () => apiRequest<RainfallSources>("/api/rainfall/sources"),
  rainfallStatus: () => apiRequest<RainfallStatus>("/api/rainfall/status"),
  rainfallCurrent: () => apiRequest<RainfallStatus>("/api/rainfall/current"),
  nowcastStatus: () => apiRequest<NowcastStatus>("/api/nowcast/status"),
};
