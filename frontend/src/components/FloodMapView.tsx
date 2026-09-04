import "leaflet/dist/leaflet.css";
import {
  MapContainer,
  TileLayer,
  Polygon,
  Polyline,
  CircleMarker,
  Tooltip,
} from "react-leaflet";
import { REGION, RISK_COLOR } from "@/data/pilot";
import { useSim } from "@/state/simulation";

export type { MapLayers } from "./map-layers";

import { DEFAULT_LAYERS, type MapLayers } from "./map-layers";

const FACILITY_COLOR = "#38bdf8";
const EVAC_COLOR = "#a3e635";

export default function FloodMapView({
  layers = DEFAULT_LAYERS,
  interactive = true,
  showRoutes = false,
  zoom,
}: {
  layers?: MapLayers | undefined;
  interactive?: boolean | undefined;
  showRoutes?: boolean | undefined;
  zoom?: number | undefined;
}) {
  const sim = useSim();

  return (
    <MapContainer
      center={REGION.center}
      zoom={zoom ?? REGION.zoom}
      scrollWheelZoom={interactive}
      dragging={interactive}
      zoomControl={interactive}
      doubleClickZoom={interactive}
      className="h-full w-full"
      attributionControl
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; OpenStreetMap &copy; CARTO — pilot basemap'
      />

      {layers.floodRisk &&
        sim.zones.map((z) => (
          <Polygon
            key={z.id}
            positions={z.polygon}
            pathOptions={{
              color: RISK_COLOR[z.risk],
              weight: 1,
              fillColor: RISK_COLOR[z.risk],
              fillOpacity:
                z.depthCm === 0
                  ? 0.06
                  : layers.floodDepth
                    ? Math.min(0.55, 0.12 + z.depthCm / 160)
                    : 0.2,
            }}
            eventHandlers={
              interactive
                ? { click: () => sim.setSelected({ kind: "zone", id: z.id }) }
                : {}
            }
          >
            <Tooltip sticky>
              {z.name} — {z.depthCm} cm
            </Tooltip>
          </Polygon>
        ))}

      {layers.drainage &&
        sim.drainage.map((d) => (
          <Polyline
            key={d.id}
            positions={d.path}
            pathOptions={{ color: "#60a5fa", weight: 2, dashArray: "6 5", opacity: 0.75 }}
          >
            <Tooltip sticky>{d.name}</Tooltip>
          </Polyline>
        ))}

      {layers.roads &&
        sim.roads.map((r) => (
          <Polyline
            key={r.id}
            positions={r.path}
            pathOptions={{
              color: r.depthCm === 0 ? "#64748b" : RISK_COLOR[r.risk],
              weight: r.category === "Arterial" ? 5 : 3.5,
              opacity: 0.95,
            }}
            eventHandlers={
              interactive
                ? { click: () => sim.setSelected({ kind: "road", id: r.id }) }
                : {}
            }
          >
            <Tooltip sticky>
              {r.name} — {r.depthCm} cm
            </Tooltip>
          </Polyline>
        ))}

      {showRoutes &&
        sim.routes.map((route) => (
          <Polyline
            key={route.id}
            positions={route.path}
            pathOptions={{
              color: route.id === "safer" ? "#22d3ee" : "#f87171",
              weight: route.id === "safer" ? 6 : 4,
              opacity: route.id === "safer" ? 0.95 : 0.6,
              dashArray: route.id === "safer" ? undefined : "8 6",
            }}
          >
            <Tooltip sticky>
              {route.label} — {route.distanceKm} km
            </Tooltip>
          </Polyline>
        ))}

      {sim.facilities
        .filter((f) =>
          f.type === "Evacuation Centre" ? layers.evacuation : layers.infrastructure,
        )
        .map((f) => (
          <CircleMarker
            key={f.id}
            center={f.position}
            radius={f.type === "Hospital" || f.type === "Evacuation Centre" ? 7 : 5}
            pathOptions={{
              color: f.type === "Evacuation Centre" ? EVAC_COLOR : FACILITY_COLOR,
              weight: 2,
              fillColor: RISK_COLOR[f.risk],
              fillOpacity: 0.9,
            }}
            eventHandlers={
              interactive
                ? { click: () => sim.setSelected({ kind: "facility", id: f.id }) }
                : {}
            }
          >
            <Tooltip sticky>
              {f.name} — {f.type}
            </Tooltip>
          </CircleMarker>
        ))}
    </MapContainer>
  );
}


