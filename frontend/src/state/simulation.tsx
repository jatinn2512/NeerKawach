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
  progressionFactor,
  type Facility,
  type RiskLevel,
  type Road,
  type Scenario,
  type Zone,
} from "@/data/pilot";
import { floodApi, type ApiStatus, type FloodSummary, type GeoJson, type HealthResponse, type RainfallSources, type RoadImpact, type RouteResponse, type RunRecord, type StudyArea } from "@/api/client";

export type SimStatus = "idle" | "running" | "complete";

export type RoadState = Road & { depthCm: number; risk: RiskLevel };
export type ZoneState = Zone & { depthCm: number; risk: RiskLevel };
export type FacilityState = Facility & {
  risk: RiskLevel;
  accessRoad: RoadState | undefined;
};

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
  dataStatus: "loading" | "ready" | "unavailable" | "error";
  dataError: string | null;
  reload: () => void;
  timestamps: string[];
  selectedTimestamp: string | null;
  setSelectedTimestamp: (timestamp: string) => void;
  routeResults: { baseline: RouteResponse | null; floodAware: RouteResponse | null };
  requestRoute: (request: Parameters<typeof floodApi.routes>[0]) => Promise<void>;
  routeStatus: "loading" | "ready" | "unavailable" | "error";
  routeError: string | null;
};

const SimContext = createContext<SimContextValue | null>(null);

const DEFAULT_SCENARIO = SCENARIOS[2]!;

function fmtClock(t: number) {
  const h = Math.floor(t);
  const m = Math.round((t - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function formatSimClock(t: number) {
  return fmtClock(t);
}

export function SimulationProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(false);
  const [operatorName, setOperatorName] = useState("R. Nandakumar");
  const [zoneId, setZoneId] = useState("zone-a");
  const [wardId, setWardId] = useState("w-04");
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO.id);
  const [status, setStatus] = useState<SimStatus>("complete");
  const [stage, setStage] = useState(SIM_STAGES.length);
  const [time, setTime] = useState(2.5);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<SelectedFeature>(null);
  const [routeShown, setRouteShown] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [apiStatus, setApiStatus] = useState<ApiStatus | null>(null);
  const [studyArea, setStudyArea] = useState<StudyArea | null>(null);
  const [summary, setSummary] = useState<FloodSummary | null>(null);
  const [maxDepth, setMaxDepth] = useState<Record<string, unknown> | null>(null);
  const [extent, setExtent] = useState<GeoJson | null>(null);
  const [roadImpact, setRoadImpact] = useState<RoadImpact | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [rainfallSources, setRainfallSources] = useState<RainfallSources["sources"]>([]);
  const [timestamps, setTimestamps] = useState<string[]>([]);
  const [timeseriesRows, setTimeseriesRows] = useState<Array<Record<string, string | number | boolean | null>>>([]);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string | null>(null);
  const [dataStatus, setDataStatus] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [dataError, setDataError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [routeResults, setRouteResults] = useState<{ baseline: RouteResponse | null; floodAware: RouteResponse | null }>({ baseline: null, floodAware: null });
  const [routeStatus, setRouteStatus] = useState<"loading" | "ready" | "unavailable" | "error">("ready");
  const [routeError, setRouteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDataStatus("loading");
    setDataError(null);
    void Promise.allSettled([
      floodApi.health(), floodApi.status(), floodApi.studyArea(), floodApi.floodSummary(), floodApi.maxDepth(),
      floodApi.floodTimeseries(), floodApi.floodExtent(), floodApi.roadImpact(), floodApi.runs(), floodApi.rainfallSources(),
    ]).then((results) => {
      if (cancelled) return;
      const [healthResult, statusResult, areaResult, summaryResult, maxDepthResult, timeseriesResult, extentResult, roadsResult, runsResult, rainfallResult] = results;
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (statusResult.status === "fulfilled") setApiStatus(statusResult.value);
      if (areaResult.status === "fulfilled") setStudyArea(areaResult.value);
      if (summaryResult.status === "fulfilled") { setSummary(summaryResult.value); setTimestamps(summaryResult.value.timestamps); }
      if (maxDepthResult.status === "fulfilled") setMaxDepth(maxDepthResult.value);
      if (timeseriesResult.status === "fulfilled") {
        setTimeseriesRows(timeseriesResult.value.rows);
        if (!summaryResult || summaryResult.status === "rejected") setTimestamps(timeseriesResult.value.rows.map((row) => row.timestamp).filter((v): v is string => typeof v === "string"));
      }
      if (extentResult.status === "fulfilled") setExtent(extentResult.value);
      if (roadsResult.status === "fulfilled") setRoadImpact(roadsResult.value);
      if (runsResult.status === "fulfilled") setRuns(runsResult.value.runs);
      if (rainfallResult.status === "fulfilled") setRainfallSources(rainfallResult.value.sources);
      const requiredFailed = [healthResult, statusResult, areaResult].some((result) => result.status === "rejected");
      const productsUnavailable = [summaryResult, maxDepthResult, timeseriesResult, extentResult, roadsResult].some((result) => result.status === "rejected" && result.reason?.status === 503);
      if (requiredFailed) { setDataStatus("error"); setDataError("The FloodOps API could not be reached. Check the backend URL and retry."); }
      else if (productsUnavailable || summaryResult.status === "rejected") { setDataStatus("unavailable"); setDataError("Validated flood products are not available in this environment."); }
      else setDataStatus("ready");
    });
    return () => { cancelled = true; };
  }, [reloadKey]);

  useEffect(() => {
    if (!selectedTimestamp && timestamps[0]) setSelectedTimestamp(timestamps[0]);
    if (selectedTimestamp && !timestamps.includes(selectedTimestamp)) setSelectedTimestamp(timestamps[0] ?? null);
  }, [timestamps, selectedTimestamp]);

  useEffect(() => {
    if (!selectedTimestamp) return;
    let cancelled = false;
    void Promise.allSettled([floodApi.floodExtent(selectedTimestamp), floodApi.roadImpact(selectedTimestamp)]).then(([extentResult, roadsResult]) => {
      if (cancelled) return;
      if (extentResult.status === "fulfilled") setExtent(extentResult.value);
      if (roadsResult.status === "fulfilled") setRoadImpact(roadsResult.value);
    });
    return () => { cancelled = true; };
  }, [selectedTimestamp]);

  const scenario = useMemo(
    () => SCENARIOS.find((s) => s.id === scenarioId) ?? DEFAULT_SCENARIO,
    [scenarioId],
  );

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(() => clearTimers, []);

  const runSimulation = useCallback(() => {
    clearTimers();
    setStatus("running");
    setStage(0);
    setPlaying(false);
    setSelected(null);
    SIM_STAGES.forEach((_, i) => {
      timers.current.push(
        setTimeout(() => setStage(i + 1), 700 * (i + 1)),
      );
    });
    timers.current.push(
      setTimeout(() => {
        setStatus("complete");
        setTime(2.5);
      }, 700 * SIM_STAGES.length + 500),
    );
  }, []);

  const resetSimulation = useCallback(() => {
    clearTimers();
    setStatus("idle");
    setStage(0);
    setTime(0);
    setPlaying(false);
  }, []);

  // Timeline playback
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setTime((t) => {
        const next = Math.round((t + 0.25) * 100) / 100;
        if (next >= 4) {
          setPlaying(false);
          return 4;
        }
        return next;
      });
    }, 550);
    return () => clearInterval(id);
  }, [playing]);

  // P10 never derives replacement road or zone values in the browser. The
  // authoritative values come from the P9 product endpoints below.
  const roads = useMemo<RoadState[]>(() => [], []);

  const zones = useMemo<ZoneState[]>(() => [], []);

  const facilities = useMemo<FacilityState[]>(() => [], []);

  const metrics = useMemo(() => {
    const row = timeseriesRows.find((item) => item.timestamp === selectedTimestamp);
    const depth = Number(row?.maximum_flood_depth_m);
    const area = Number(row?.inundated_area_m2);
    const maxDepthPayload = maxDepth?.maximum_flood_depth as { value_m?: unknown } | undefined;
    const summaryDepth = Number(summary?.maximum_flood_depth?.value_m ?? maxDepthPayload?.value_m);
    const maxDepthM = Number.isFinite(depth) ? depth : Number.isFinite(summaryDepth) ? summaryDepth : 0;
    const affected = (roadImpact?.rows ?? []).filter((item) => item.affected === true || item.affected === "True" || item.affected === "true");
    const risk = maxDepthM < 0.1 ? "low" : maxDepthM < 0.3 ? "moderate" : maxDepthM < 0.5 ? "high" : "severe";
    return {
      maxDepthCm: maxDepthM * 100,
      affectedZones: 0,
      highRiskRoads: affected.length,
      criticalAtRisk: 0,
      affectedAreaKm2: Number.isFinite(area) ? area / 1_000_000 : 0,
      overallRisk: risk as RiskLevel,
      rainfallNow: 0,
      startedAt: selectedTimestamp ?? "—",
      clock: selectedTimestamp ? new Date(selectedTimestamp).toISOString().slice(11, 16) : "—",
    };
  }, [maxDepth, roadImpact, selectedTimestamp, summary, timeseriesRows]);

  const requestRoute = useCallback(async (request: Parameters<typeof floodApi.routes>[0]) => {
    setRouteStatus("loading");
    setRouteError(null);
    try {
      const result = await floodApi.routes(request);
      setRouteResults((current) => ({
        ...current,
        [request.routing_mode === "baseline" ? "baseline" : "floodAware"]: result,
      }));
      setRouteStatus("ready");
      setRouteShown(true);
    } catch (error) {
      const statusCode = error && typeof error === "object" && "status" in error ? (error as { status?: number }).status : undefined;
      setRouteStatus(statusCode === 503 ? "unavailable" : "error");
      setRouteError(error instanceof Error ? error.message : "Route request failed.");
    }
  }, []);

  const value: SimContextValue = {
    operator: {
      name: operatorName,
      id: "OPR-KA-0142",
      role: "Disaster Management Operator",
    },
    signedIn,
    signIn: (name) => {
      setOperatorName(name || "R. Nandakumar");
      setSignedIn(true);
    },
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
    togglePlay: () => setPlaying((p) => !p),
    roads,
    zones,
    facilities,
    drainage: DRAINAGE,
    routeShown,
    showRoutes: () => setRouteShown(true),
    hideRoutes: () => setRouteShown(false),
    routes: [] as typeof ROUTE_OPTIONS,
    selected,
    setSelected,
    metrics,
    health,
    apiStatus,
    studyArea,
    summary,
    maxDepth,
    extent,
    roadImpact,
    runs,
    rainfallSources,
    dataStatus,
    dataError,
    reload: () => setReloadKey((value) => value + 1),
    timestamps,
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
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim must be used inside SimulationProvider");
  return ctx;
}


