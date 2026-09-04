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

  const roads = useMemo<RoadState[]>(
    () =>
      ROADS.map((r) => {
        const depth = Math.round(
          r.peakDepthCm * scenario.factor * progressionFactor(time, r.onset),
        );
        return { ...r, depthCm: depth, risk: depthToRisk(depth) };
      }),
    [scenario, time],
  );

  const zones = useMemo<ZoneState[]>(
    () =>
      ZONES.map((z) => {
        const depth = Math.round(
          z.peakDepthCm * scenario.factor * progressionFactor(time, z.onset),
        );
        return { ...z, depthCm: depth, risk: depthToRisk(depth) };
      }),
    [scenario, time],
  );

  const facilities = useMemo<FacilityState[]>(
    () =>
      FACILITIES.map((f) => {
        const accessRoad = roads.find((r) => r.id === f.accessRoadId);
        return { ...f, accessRoad, risk: accessRoad?.risk ?? "low" };
      }),
    [roads],
  );

  const metrics = useMemo(() => {
    const depths = [...roads, ...zones].map((f) => f.depthCm);
    const maxDepthCm = Math.max(0, ...depths);
    const affectedZones = zones.filter((z) => z.risk !== "low").length;
    const highRiskRoads = roads.filter(
      (r) => r.risk === "high" || r.risk === "severe",
    ).length;
    const criticalAtRisk = facilities.filter(
      (f) => f.risk === "high" || f.risk === "severe",
    ).length;
    const affectedAreaKm2 =
      Math.round(
        zones.filter((z) => z.risk !== "low").length * 2.35 * 10,
      ) / 10;
    const rainfallNow =
      time <= 0
        ? 0
        : Math.round(
            scenario.intensityMmHr *
              (time < 1 ? 0.55 : time < 3 ? 1 : 0.6) *
              10,
          ) / 10;
    return {
      maxDepthCm,
      affectedZones,
      highRiskRoads,
      criticalAtRisk,
      affectedAreaKm2,
      overallRisk: depthToRisk(maxDepthCm),
      rainfallNow,
      startedAt: "30 Aug 2026, 16:40 IST",
      clock: fmtClock(time),
    };
  }, [roads, zones, facilities, scenario, time]);

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
    routes: ROUTE_OPTIONS,
    selected,
    setSelected,
    metrics,
  };

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim() {
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim must be used inside SimulationProvider");
  return ctx;
}


