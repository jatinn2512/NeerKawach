// FloodOps — preconfigured pilot geospatial dataset (mock).
// Structured so each export can later be replaced by an API call to the
// real GIS / simulation backend without touching UI components.

export type LatLng = [number, number];

export type RiskLevel = "low" | "moderate" | "high" | "severe";

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
};

export const RISK_COLOR: Record<RiskLevel, string> = {
  low: "#22c55e",
  moderate: "#eab308",
  high: "#f97316",
  severe: "#ef4444",
};

/** Depth (cm) thresholds used by the flood model to classify a location. */
export function depthToRisk(depthCm: number): RiskLevel {
  if (depthCm < 10) return "low";
  if (depthCm < 30) return "moderate";
  if (depthCm < 50) return "high";
  return "severe";
}

export const REGION = {
  id: "pilot-blr-01",
  region: "Pilot Region — Karnataka",
  city: "Bengaluru (BBMP)",
  area: "Bellandur–Koramangala Catchment",
  center: [12.9328, 77.6512] as LatLng,
  zoom: 13,
  coverageKm2: 46.8,
  crs: "EPSG:4326 / UTM 43N",
};

export const REGION_OPTIONS = [
  { id: "pilot-blr-01", label: "Pilot Region — Karnataka", enabled: true },
  { id: "pilot-mh-01", label: "Pilot Region — Maharashtra", enabled: false },
  { id: "pilot-as-01", label: "Pilot Region — Assam", enabled: false },
];

export const CITY_OPTIONS = [
  { id: "blr", label: "Bengaluru (BBMP)", enabled: true },
  { id: "mys", label: "Mysuru (MCC)", enabled: false },
];

export const ZONE_OPTIONS = [
  { id: "zone-a", label: "Zone A — Bellandur" },
  { id: "zone-b", label: "Zone B — Koramangala" },
  { id: "zone-c", label: "Zone C — HSR Layout" },
];

export const WARD_OPTIONS: Record<string, { id: string; label: string }[]> = {
  "zone-a": [
    { id: "w-04", label: "Ward 04 — Bellandur Lake Basin" },
    { id: "w-05", label: "Ward 05 — Kaikondrahalli" },
  ],
  "zone-b": [
    { id: "w-11", label: "Ward 11 — Koramangala 3rd Block" },
    { id: "w-12", label: "Ward 12 — Ejipura" },
  ],
  "zone-c": [
    { id: "w-21", label: "Ward 21 — HSR Sector 2" },
    { id: "w-22", label: "Ward 22 — Agara" },
  ],
};

export type Scenario = {
  id: string;
  name: string;
  intensityMmHr: number;
  durationHrs: number;
  description: string;
  severity: RiskLevel;
  /** Multiplier applied to the modelled peak depth of every feature. */
  factor: number;
  returnPeriod: string;
};

export const SCENARIOS: Scenario[] = [
  {
    id: "moderate",
    name: "Moderate Rainfall",
    intensityMmHr: 35,
    durationHrs: 3,
    description:
      "Sustained monsoon shower within design drainage capacity. Localised ponding at known low points.",
    severity: "moderate",
    factor: 0.42,
    returnPeriod: "1 in 2 years",
  },
  {
    id: "heavy",
    name: "Heavy Rainfall",
    intensityMmHr: 75,
    durationHrs: 4,
    description:
      "Drainage network reaches capacity. Surface flooding expected along arterial corridors and lake overflow channels.",
    severity: "high",
    factor: 0.72,
    returnPeriod: "1 in 10 years",
  },
  {
    id: "extreme",
    name: "Extreme Storm",
    intensityMmHr: 120,
    durationHrs: 4,
    description:
      "Cloudburst-class event exceeding drainage capacity by a wide margin. Rapid accumulation in low-lying wards and lake spillover.",
    severity: "severe",
    factor: 1,
    returnPeriod: "1 in 100 years",
  },
];

/** Progression curve: fraction of peak depth reached at simulation hour t. */
export function progressionFactor(t: number, onset: number, duration = 4) {
  if (t <= onset) return 0;
  const p = (t - onset) / (duration - onset);
  return Math.min(1, Math.max(0, Math.pow(p, 0.75)));
}

export type Zone = {
  id: string;
  name: string;
  ward: string;
  polygon: LatLng[];
  peakDepthCm: number;
  onset: number;
  population: number;
};

export const ZONES: Zone[] = [
  {
    id: "z1",
    name: "Bellandur Lake Basin",
    ward: "Ward 04",
    polygon: [
      [12.9345, 77.6685],
      [12.9372, 77.6805],
      [12.9268, 77.6852],
      [12.9215, 77.6742],
      [12.9268, 77.6664],
    ],
    peakDepthCm: 92,
    onset: 0.4,
    population: 41200,
  },
  {
    id: "z2",
    name: "Ejipura Low-Lying Belt",
    ward: "Ward 12",
    polygon: [
      [12.9412, 77.6208],
      [12.9438, 77.6318],
      [12.9342, 77.6352],
      [12.9312, 77.6242],
    ],
    peakDepthCm: 74,
    onset: 0.8,
    population: 33800,
  },
  {
    id: "z3",
    name: "Koramangala 3rd Block",
    ward: "Ward 11",
    polygon: [
      [12.9382, 77.6088],
      [12.9405, 77.6202],
      [12.9302, 77.6238],
      [12.9282, 77.6122],
    ],
    peakDepthCm: 58,
    onset: 1.1,
    population: 28400,
  },
  {
    id: "z4",
    name: "Agara Lake Fringe",
    ward: "Ward 22",
    polygon: [
      [12.9268, 77.6352],
      [12.9295, 77.6462],
      [12.9198, 77.6498],
      [12.9172, 77.6392],
    ],
    peakDepthCm: 66,
    onset: 0.9,
    population: 19700,
  },
  {
    id: "z5",
    name: "HSR Sector 2 Grid",
    ward: "Ward 21",
    polygon: [
      [12.9182, 77.6402],
      [12.9208, 77.6522],
      [12.9098, 77.6558],
      [12.9072, 77.6438],
    ],
    peakDepthCm: 44,
    onset: 1.4,
    population: 36100,
  },
  {
    id: "z6",
    name: "Kaikondrahalli Channel",
    ward: "Ward 05",
    polygon: [
      [12.9218, 77.6712],
      [12.9242, 77.6828],
      [12.9138, 77.6862],
      [12.9112, 77.6748],
    ],
    peakDepthCm: 52,
    onset: 1.6,
    population: 15400,
  },
  {
    id: "z7",
    name: "Sarjapur Junction Ridge",
    ward: "Ward 04",
    polygon: [
      [12.9482, 77.6512],
      [12.9508, 77.6628],
      [12.9402, 77.6662],
      [12.9378, 77.6548],
    ],
    peakDepthCm: 24,
    onset: 2.2,
    population: 22600,
  },
];

export type Road = {
  id: string;
  name: string;
  path: LatLng[];
  peakDepthCm: number;
  onset: number;
  lengthKm: number;
  category: "Arterial" | "Sub-arterial" | "Collector" | "Access";
};

export const ROADS: Road[] = [
  {
    id: "r1",
    name: "Outer Ring Road (Bellandur Stretch)",
    path: [
      [12.9452, 77.6598],
      [12.9368, 77.6712],
      [12.9282, 77.6798],
    ],
    peakDepthCm: 88,
    onset: 0.5,
    lengthKm: 3.4,
    category: "Arterial",
  },
  {
    id: "r2",
    name: "Sarjapur Main Road",
    path: [
      [12.9302, 77.6242],
      [12.9268, 77.6438],
      [12.9232, 77.6642],
    ],
    peakDepthCm: 68,
    onset: 0.7,
    lengthKm: 4.6,
    category: "Arterial",
  },
  {
    id: "r3",
    name: "Hosur Road (Ejipura Link)",
    path: [
      [12.9438, 77.6112],
      [12.9352, 77.6188],
      [12.9268, 77.6248],
    ],
    peakDepthCm: 54,
    onset: 1,
    lengthKm: 2.8,
    category: "Arterial",
  },
  {
    id: "r4",
    name: "Hospital Access Road (St. John's Link)",
    path: [
      [12.9312, 77.6202],
      [12.9288, 77.6268],
      [12.9262, 77.6318],
    ],
    peakDepthCm: 46,
    onset: 1.1,
    lengthKm: 1.5,
    category: "Collector",
  },
  {
    id: "r5",
    name: "80 Feet Road, Koramangala",
    path: [
      [12.9382, 77.6122],
      [12.9338, 77.6188],
      [12.9298, 77.6242],
    ],
    peakDepthCm: 38,
    onset: 1.3,
    lengthKm: 2.1,
    category: "Sub-arterial",
  },
  {
    id: "r6",
    name: "Agara–Iblur Connector",
    path: [
      [12.9242, 77.6412],
      [12.9218, 77.6522],
      [12.9236, 77.6628],
    ],
    peakDepthCm: 62,
    onset: 0.9,
    lengthKm: 2.6,
    category: "Sub-arterial",
  },
  {
    id: "r7",
    name: "HSR 27th Main",
    path: [
      [12.9162, 77.6432],
      [12.9128, 77.6512],
      [12.9108, 77.6588],
    ],
    peakDepthCm: 34,
    onset: 1.5,
    lengthKm: 2.2,
    category: "Collector",
  },
  {
    id: "r8",
    name: "Kaikondrahalli Lake Road",
    path: [
      [12.9198, 77.6742],
      [12.9162, 77.6812],
    ],
    peakDepthCm: 48,
    onset: 1.4,
    lengthKm: 1.3,
    category: "Collector",
  },
  {
    id: "r9",
    name: "Ejipura Main Road",
    path: [
      [12.9412, 77.6238],
      [12.9362, 77.6292],
      [12.9332, 77.6338],
    ],
    peakDepthCm: 58,
    onset: 0.9,
    lengthKm: 1.8,
    category: "Collector",
  },
  {
    id: "r10",
    name: "Iblur Junction Ramp",
    path: [
      [12.9282, 77.6652],
      [12.9248, 77.6712],
    ],
    peakDepthCm: 72,
    onset: 0.6,
    lengthKm: 0.9,
    category: "Access",
  },
  {
    id: "r11",
    name: "Marathahalli Bridge Approach",
    path: [
      [12.9482, 77.6642],
      [12.9432, 77.6718],
    ],
    peakDepthCm: 26,
    onset: 2,
    lengthKm: 1.2,
    category: "Arterial",
  },
  {
    id: "r12",
    name: "Haralur Ridge Road",
    path: [
      [12.9108, 77.6612],
      [12.9078, 77.6712],
    ],
    peakDepthCm: 14,
    onset: 2.6,
    lengthKm: 1.6,
    category: "Collector",
  },
];

export const DRAINAGE: { id: string; name: string; path: LatLng[] }[] = [
  {
    id: "d1",
    name: "Bellandur Primary Storm Drain",
    path: [
      [12.9412, 77.6288],
      [12.9348, 77.6462],
      [12.9302, 77.6688],
      [12.9282, 77.6812],
    ],
  },
  {
    id: "d2",
    name: "Koramangala Valley Drain",
    path: [
      [12.9448, 77.6108],
      [12.9362, 77.6212],
      [12.9282, 77.6352],
    ],
  },
  {
    id: "d3",
    name: "Agara–Somasundarapalya Secondary Drain",
    path: [
      [12.9212, 77.6412],
      [12.9152, 77.6528],
      [12.9118, 77.6648],
    ],
  },
];

export type Facility = {
  id: string;
  name: string;
  type:
    | "Hospital"
    | "School"
    | "Police Station"
    | "Fire Station"
    | "Evacuation Centre"
    | "Government Facility";
  position: LatLng;
  accessRoadId: string;
  capacity?: string;
};

export const FACILITIES: Facility[] = [
  {
    id: "f1",
    name: "St. John's Medical Centre",
    type: "Hospital",
    position: [12.9286, 77.6272],
    accessRoadId: "r4",
    capacity: "740 beds",
  },
  {
    id: "f2",
    name: "Bellandur Community Hospital",
    type: "Hospital",
    position: [12.9312, 77.6742],
    accessRoadId: "r1",
    capacity: "180 beds",
  },
  {
    id: "f3",
    name: "Koramangala Govt. High School",
    type: "School",
    position: [12.9348, 77.6162],
    accessRoadId: "r5",
    capacity: "1,200 students",
  },
  {
    id: "f4",
    name: "HSR Layout Police Station",
    type: "Police Station",
    position: [12.9142, 77.6472],
    accessRoadId: "r7",
  },
  {
    id: "f5",
    name: "Bellandur Fire & Rescue Station",
    type: "Fire Station",
    position: [12.9268, 77.6688],
    accessRoadId: "r10",
  },
  {
    id: "f6",
    name: "Evacuation Centre B — HSR Indoor Stadium",
    type: "Evacuation Centre",
    position: [12.9118, 77.6528],
    accessRoadId: "r7",
    capacity: "2,400 persons",
  },
  {
    id: "f7",
    name: "Evacuation Centre A — Ejipura Ward Hall",
    type: "Evacuation Centre",
    position: [12.9392, 77.6262],
    accessRoadId: "r9",
    capacity: "900 persons",
  },
  {
    id: "f8",
    name: "BBMP Zonal Office, Koramangala",
    type: "Government Facility",
    position: [12.9372, 77.6198],
    accessRoadId: "r5",
  },
  {
    id: "f9",
    name: "Sarjapur Ridge Relief Camp",
    type: "Evacuation Centre",
    position: [12.9452, 77.6588],
    accessRoadId: "r11",
    capacity: "1,500 persons",
  },
];

export type RouteOption = {
  id: string;
  label: "Safer Route" | "Direct Route";
  path: LatLng[];
  distanceKm: number;
  travelMin: number;
  highRiskSegments: number;
  maxDepthCm: number;
  risk: RiskLevel;
  via: string;
};

/** Precomputed lower-risk vs direct corridor between the two demo facilities. */
export const ROUTE_OPTIONS: RouteOption[] = [
  {
    id: "safer",
    label: "Safer Route",
    path: [
      [12.9286, 77.6272],
      [12.9232, 77.6318],
      [12.9168, 77.6402],
      [12.9128, 77.6482],
      [12.9118, 77.6528],
    ],
    distanceKm: 6.8,
    travelMin: 21,
    highRiskSegments: 1,
    maxDepthCm: 18,
    risk: "moderate",
    via: "Via Somasundarapalya Ridge & HSR 27th Main",
  },
  {
    id: "direct",
    label: "Direct Route",
    path: [
      [12.9286, 77.6272],
      [12.9262, 77.6412],
      [12.9218, 77.6522],
      [12.9152, 77.6552],
      [12.9118, 77.6528],
    ],
    distanceKm: 5.2,
    travelMin: 14,
    highRiskSegments: 5,
    maxDepthCm: 62,
    risk: "severe",
    via: "Via Agara–Iblur Connector",
  },
];

export const DATASETS = [
  {
    name: "Digital Elevation Model (1 m LiDAR)",
    status: "Loaded" as const,
    updated: "2026-07-18",
    coverage: "46.8 km² — Full pilot catchment",
    source: "NRSC / State Survey",
    size: "2.4 GB",
  },
  {
    name: "Road Network (OSM + BBMP)",
    status: "Loaded" as const,
    updated: "2026-08-02",
    coverage: "1,284 km of road centrelines",
    source: "BBMP Roads Division",
    size: "184 MB",
  },
  {
    name: "Storm Drainage Network",
    status: "Loaded" as const,
    updated: "2026-06-29",
    coverage: "312 km primary + secondary drains",
    source: "BBMP SWD Division",
    size: "96 MB",
  },
  {
    name: "Building Footprints",
    status: "Available" as const,
    updated: "2026-05-11",
    coverage: "218,400 structures",
    source: "Municipal GIS Cell",
    size: "1.1 GB",
  },
  {
    name: "Critical Infrastructure Registry",
    status: "Loaded" as const,
    updated: "2026-08-21",
    coverage: "412 facilities tagged",
    source: "District Disaster Management Authority",
    size: "18 MB",
  },
  {
    name: "Rainfall & Radar Feed",
    status: "Available" as const,
    updated: "2026-08-30 16:45",
    coverage: "Gauge network (12 stations) + radar grid",
    source: "IMD Bengaluru",
    size: "Streaming",
  },
];

export const SYSTEM_SERVICES = [
  { name: "Spatial Database (PostGIS)", status: "Operational" as const, detail: "12 ms avg query · 99.98% uptime" },
  { name: "GIS Data Services", status: "Operational" as const, detail: "6 layers loaded · cache warm" },
  { name: "Simulation Engine (Hydrodynamic)", status: "Processing" as const, detail: "1 run active · queue empty" },
  { name: "Application API", status: "Operational" as const, detail: "48 ms p95 · 0 errors (1h)" },
  { name: "Map Tile Services", status: "Operational" as const, detail: "Basemap + overlay tiles healthy" },
  { name: "Rainfall Feed Ingest", status: "Warning" as const, detail: "1 gauge station reporting late (BLR-07)" },
];

export const SIM_HISTORY = [
  { id: "SIM-2026-0412", scenario: "Heavy Rainfall (60 mm/hr)", operator: "K. Rajesh", started: "Today, 09:12", duration: "2.4 s", status: "Completed" as const },
  { id: "SIM-2026-0411", scenario: "Extreme Storm (95 mm/hr)", operator: "K. Rajesh", started: "Today, 08:47", duration: "3.1 s", status: "Completed" as const },
  { id: "SIM-2026-0410", scenario: "Moderate Rainfall (35 mm/hr)", operator: "S. Menon", started: "Today, 07:30", duration: "1.9 s", status: "Completed" as const },
  { id: "SIM-2026-0409", scenario: "Cloudburst (120 mm/hr)", operator: "A. Nair", started: "Yesterday, 22:04", duration: "—", status: "Failed" as const },
];

export const SIM_STAGES = [
  "Preparing geographic data",
  "Processing rainfall input",
  "Running drainage / flood model",
  "Generating flood-depth results",
  "Processing road risk classification",
  "Generating map layers",
];


