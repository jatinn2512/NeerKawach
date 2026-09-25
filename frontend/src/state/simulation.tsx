import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  DRAINAGE,
  FACILITIES,
  ROADS,
  ROUTE_OPTIONS,
  SCENARIOS,
  SIM_STAGES,
  ZONES,
  depthToRisk,
  type Facility,
  type RiskLevel,
  type Road,
  type Scenario,
  type Zone,
} from "@/data/pilot";
import {
  DEMO_API_STATUS,
  DEMO_CURRENT_RAINFALL_STATUS,
  DEMO_HEALTH,
  DEMO_ROUTE_RESULTS,
  DEMO_RUNS,
  DEMO_RAINFALL_SOURCES,
  DEMO_RAINFALL_STATUS,
  DEMO_STUDY_AREA,
  DEMO_SUMMARY,
  DEMO_TIMELINE,
  NEARBY_AREAS,
  generateRouteForPair,
  timelinePoint,
} from "@/data/demo";
import type {
  ApiStatus,
  FloodSummary,
  GeoJson,
  HealthResponse,
  RainfallSources,
  RainfallStatus,
  RoadImpact,
  RouteRequest,
  RouteResponse,
  RunRecord,
  StudyArea,
} from "@/api/client";

export type SimStatus = "idle" | "running" | "complete";
export type RoadState = Road & { depthCm: number; risk: RiskLevel };
export type ZoneState = Zone & { depthCm: number; risk: RiskLevel };
export type FacilityState = Facility & { risk: RiskLevel; accessRoad: RoadState | undefined };

type SelectedFeature =
  | { kind: "road"; id: string }
  | { kind: "zone"; id: string }
  | { kind: "facility"; id: string }
  | null;

type SimContextValue = {
  operator: { name: string; id: string; role: string };
  signedIn: boolean;
  signIn: (name: string) => void;
  signOut: () => void;
  zoneId: string;
  wardId: string;
  setZoneId: (v: string) => void;
  setWardId: (v: string) => void;
  scenario: Scenario;
  setScenarioId: (id: string) => void;
  status: SimStatus;
  stage: number;
  progress: number;
  runSimulation: () => void;
  resetSimulation: () => void;
  time: number;
  setTime: (t: number) => void;
  playing: boolean;
  togglePlay: () => void;
  roads: RoadState[];
  zones: ZoneState[];
  facilities: FacilityState[];
  drainage: typeof DRAINAGE;
  routeShown: boolean;
  showRoutes: () => void;
  hideRoutes: () => void;
  routes: typeof ROUTE_OPTIONS;
  selected: SelectedFeature;
  setSelected: (s: SelectedFeature) => void;
  metrics: {
    maxDepthCm: number;
    affectedZones: number;
    highRiskRoads: number;
    criticalAtRisk: number;
    affectedAreaKm2: number;
    overallRisk: RiskLevel;
    rainfallNow: number;
    accumulatedRainfallMm: number;
    startedAt: string;
    clock: string;
  };
  health: HealthResponse | null;
  apiStatus: ApiStatus | null;
  studyArea: StudyArea | null;
  summary: FloodSummary | null;
  maxDepth: Record<string, unknown> | null;
  extent: GeoJson | null;
  roadImpact: RoadImpact | null;
  runs: RunRecord[];
  rainfallSources: RainfallSources["sources"];
  rainfallStatus: RainfallStatus | null;
  rainfallCurrentStatus: RainfallStatus | null;
  dataStatus: "loading" | "ready" | "unavailable" | "error";
  dataError: string | null;
  reload: () => void;
  timestamps: string[];
  selectedTimestamp: string | null;
  setSelectedTimestamp: (timestamp: string) => void;
  routeResults: { baseline: RouteResponse | null; floodAware: RouteResponse | null };
  requestRoute: (request: RouteRequest) => Promise<void>;
  routeStatus: "loading" | "ready" | "unavailable" | "error";
  routeError: string | null;
};

const SimContext = createContext<SimContextValue | null>(null);
const DEFAULT_SCENARIO = SCENARIOS.find((scenario) => scenario.id === "extreme") ?? SCENARIOS[2]!;
const TIMESTAMPS = DEMO_TIMELINE.map((point) => point.label);

function featureDepth(peakDepthCm: number, onset: number, time: number, scenarioFactor: number) {
  if (time <= onset) return 0;
  const progress = Math.min(1, Math.max(0, (time - onset) / (3 - onset)));
  return Math.round(peakDepthCm * Math.pow(progress, 0.75) * scenarioFactor);
}

function timestampIndex(timestamp: string | null) {
  const index = TIMESTAMPS.indexOf(timestamp ?? "");
  return index >= 0 ? index : 0;
}

export function formatSimClock(time: number) {
  const hours = Math.floor(time);
  const minutes = Math.round((time - hours) * 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function SimulationProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(false);
  const [operatorName, setOperatorName] = useState("R. Nandakumar");
  const [zoneId, setZoneId] = useState("zone-a");
  const [wardId, setWardId] = useState("w-04");
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO.id);
  const [status, setStatus] = useState<SimStatus>("idle");
  const [stage, setStage] = useState(0);
  const [time, setTimeState] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<SelectedFeature>(null);
  const [routeShown, setRouteShown] = useState(false);
  const [selectedTimestamp, setSelectedTimestampState] = useState<string | null>(TIMESTAMPS[0]);
  const [routeResults, setRouteResults] = useState<{ baseline: RouteResponse | null; floodAware: RouteResponse | null }>({ baseline: null, floodAware: null });
  const [routeStatus, setRouteStatus] = useState<"loading" | "ready" | "unavailable" | "error">("ready");
  const [routeError, setRouteError] = useState<string | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const scenario = useMemo(
    () => SCENARIOS.find((candidate) => candidate.id === scenarioId) ?? DEFAULT_SCENARIO,
    [scenarioId],
  );
  const timeline = timelinePoint(selectedTimestamp);

  const clearTimers = useCallback(() => {
    timers.current.forEach((timer) => clearTimeout(timer));
    timers.current = [];
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const setSelectedTimestamp = useCallback((timestamp: string) => {
    if (!TIMESTAMPS.includes(timestamp)) return;
    setSelectedTimestampState(timestamp);
    setTimeState(timestampIndex(timestamp) / 2);
  }, []);

  const setTime = useCallback((nextTime: number) => {
    const clamped = Math.min(3, Math.max(0, nextTime));
    const index = Math.min(TIMESTAMPS.length - 1, Math.max(0, Math.round(clamped * 2)));
    setTimeState(index / 2);
    setSelectedTimestampState(TIMESTAMPS[index] ?? TIMESTAMPS[0]);
  }, []);

  const runSimulation = useCallback(() => {
    clearTimers();
    setStatus("running");
    setStage(0);
    setTime(0);
    setPlaying(false);
    setSelected(null);
    setRouteShown(false);
    setRouteResults({ baseline: null, floodAware: null });
    const stageDurationMs = 380;
    SIM_STAGES.forEach((_, index) => {
      timers.current.push(setTimeout(() => setStage(index + 1), stageDurationMs * (index + 1)));
    });
    timers.current.push(setTimeout(() => {
      setStatus("complete");
      setTime(1.5);
    }, stageDurationMs * SIM_STAGES.length + 450));
  }, [clearTimers, setTime]);

  const resetSimulation = useCallback(() => {
    clearTimers();
    setStatus("idle");
    setStage(0);
    setTime(0);
    setPlaying(false);
    setRouteShown(false);
    setRouteResults({ baseline: null, floodAware: null });
  }, [clearTimers, setTime]);

  useEffect(() => {
    if (!playing || status === "running") return;
    const timer = setInterval(() => {
      setTimeState((current) => {
        const nextIndex = Math.min(TIMESTAMPS.length - 1, Math.round(current * 2) + 1);
        if (nextIndex >= TIMESTAMPS.length - 1) setPlaying(false);
        setSelectedTimestampState(TIMESTAMPS[nextIndex] ?? TIMESTAMPS.at(-1) ?? "03:00");
        return nextIndex / 2;
      });
    }, 700);
    return () => clearInterval(timer);
  }, [playing, status]);

  const roads = useMemo<RoadState[]>(
    () => ROADS.map((road) => {
      const depthCm = featureDepth(road.peakDepthCm, road.onset, time, scenario.factor);
      return { ...road, depthCm, risk: depthToRisk(depthCm) };
    }),
    [scenario.factor, time],
  );

  const zones = useMemo<ZoneState[]>(
    () => ZONES.map((zone) => {
      const depthCm = featureDepth(zone.peakDepthCm, zone.onset, time, scenario.factor);
      return { ...zone, depthCm, risk: depthToRisk(depthCm) };
    }),
    [scenario.factor, time],
  );

  const facilities = useMemo<FacilityState[]>(
    () => FACILITIES.map((facility) => {
      const accessRoad = roads.find((road) => road.id === facility.accessRoadId);
      return { ...facility, accessRoad, risk: accessRoad?.risk ?? "low" };
    }),
    [roads],
  );

  const roadImpact = useMemo<RoadImpact>(() => ({
    timestamp: selectedTimestamp,
    road_id: null,
    units: { depth: "m", length: "km" },
    rows: roads.map((road) => ({
      road_id: road.name,
      max_intersecting_depth_m: road.depthCm / 100,
      risk_class: road.risk,
      affected: road.depthCm >= 10,
      length_km: road.lengthKm,
    })),
  }), [roads, selectedTimestamp]);

  const metrics = useMemo(() => {
    const affectedZones = zones.filter((zone) => zone.depthCm >= 10).length;
    const affectedRoads = roads.filter((road) => road.depthCm >= 10).length;
    const criticalAtRisk = facilities.filter((facility) => facility.risk === "high" || facility.risk === "severe").length;
    return {
      maxDepthCm: Math.round(timeline.maxDepthCm * scenario.factor * 10) / 10,
      affectedZones,
      highRiskRoads: affectedRoads,
      criticalAtRisk,
      affectedAreaKm2: Math.round(timeline.affectedAreaKm2 * scenario.factor * 100) / 100,
      overallRisk: depthToRisk(timeline.maxDepthCm * scenario.factor),
      rainfallNow: timeline.rainfallMmHr,
      accumulatedRainfallMm: timeline.accumulatedRainfallMm,
      startedAt: "00:00",
      clock: timeline.label,
    };
  }, [facilities, roads, scenario.factor, timeline, zones]);

  /** Clear all displayed routes — call before loading a different origin/dest pair. */
  const clearRoutes = useCallback(() => {
    setRouteResults({ baseline: null, floodAware: null });
    setRouteShown(false);
  }, []);

  const requestRoute = useCallback(async (request: RouteRequest) => {
    // On baseline request (which is always first), wipe old routes so no stale
    // geometry is visible while the new pair loads.
    if (request.routing_mode === "baseline") {
      clearRoutes();
    }
    setRouteStatus("loading");
    setRouteError(null);
    await new Promise<void>((resolve) => setTimeout(resolve, 250));

    // Try to match the request coords to a NEARBY_AREAS entry for dynamic routes
    const findArea = (lat: number, lon: number) =>
      NEARBY_AREAS.find((a) => Math.abs(a.coordinates[0] - lat) < 0.002 && Math.abs(a.coordinates[1] - lon) < 0.002);
    const originArea = findArea(request.origin_latitude, request.origin_longitude);
    const destArea = findArea(request.destination_latitude, request.destination_longitude);

    const result = originArea && destArea
      ? generateRouteForPair(originArea, destArea, request.routing_mode, request.simulation_timestamp)
      : { ...DEMO_ROUTE_RESULTS[request.routing_mode], route_timestamp: request.simulation_timestamp };

    setRouteResults((current) => ({
      ...current,
      [request.routing_mode === "baseline" ? "baseline" : "floodAware"]: result,
    }));
    setRouteStatus("ready");
    setRouteShown(true);
  }, [clearRoutes]);

  const value: SimContextValue = {
    operator: { name: operatorName, id: "OPR-KA-0142", role: "Disaster Management Operator" },
    signedIn,
    signIn: (name) => { setOperatorName(name || "R. Nandakumar"); setSignedIn(true); },
    signOut: () => setSignedIn(false),
    zoneId,
    wardId,
    setZoneId,
    setWardId,
    scenario,
    setScenarioId,
    status,
    stage,
    progress: Math.round((stage / SIM_STAGES.length) * 100),
    runSimulation,
    resetSimulation,
    time,
    setTime,
    playing,
    togglePlay: () => setPlaying((current) => !current),
    roads,
    zones,
    facilities,
    drainage: DRAINAGE,
    routeShown,
    showRoutes: () => setRouteShown(true),
    hideRoutes: () => setRouteShown(false),
    routes: [],
    selected,
    setSelected,
    metrics,
    health: DEMO_HEALTH,
    apiStatus: DEMO_API_STATUS,
    studyArea: DEMO_STUDY_AREA,
    summary: DEMO_SUMMARY,
    maxDepth: { maximum_flood_depth: { value_m: DEMO_TIMELINE.at(-1)!.maxDepthCm / 100, timestamp: DEMO_TIMELINE.at(-1)!.label } },
    extent: null,
    roadImpact,
    runs: DEMO_RUNS,
    rainfallSources: DEMO_RAINFALL_SOURCES,
    rainfallStatus: DEMO_RAINFALL_STATUS,
    rainfallCurrentStatus: DEMO_CURRENT_RAINFALL_STATUS,
    dataStatus: "ready",
    dataError: null,
    reload: () => undefined,
    timestamps: TIMESTAMPS,
    selectedTimestamp,
    setSelectedTimestamp,
    routeResults,
    requestRoute,
    routeStatus,
    routeError,
  };

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim() {
  const context = useContext(SimContext);
  if (!context) throw new Error("useSim must be used inside SimulationProvider");
  return context;
}
