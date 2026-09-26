import "leaflet/dist/leaflet.css";
import { Fragment, useEffect, useMemo, useRef } from "react";
import { latLngBounds, type FitBoundsOptions, type LatLngBounds } from "leaflet";
import {
  AttributionControl,
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  Polygon,
  Polyline,
  ScaleControl,
  TileLayer,
  Tooltip,
  useMap,
  ZoomControl,
} from "react-leaflet";
import { RISK_COLOR, type LatLng } from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { geoJsonLines, organicPolygon, scaleRing } from "./map-geometry";

export type { MapLayers } from "./map-layers";

import { DEFAULT_LAYERS, type MapLayers } from "./map-layers";

/** Fit padding in pixels, CSS order: top, right, bottom, left. */
export type MapPadding = [number, number, number, number];

const DEFAULT_PADDING: MapPadding = [24, 24, 24, 24];
const FACILITY_COLOR = "#38bdf8";
const EVAC_COLOR = "#a3e635";
const ROUTE_COLOR = "#22d3ee";
const DIRECT_COLOR = "#ff5a67";
const CASING = "#06121e";
const DRY_ROAD = "#5d7489";
const DRAIN_COLOR = "#4f9fe0";

// Esri's Canvas tiles need no API key. Failed tiles fall back to a transparent
// pixel so an offline recording shows the plain map background, not broken images.
const ESRI_CANVAS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const ESRI_IMAGERY = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const BLANK_TILE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

const shapeCache = new WeakMap<LatLng[], { outer: LatLng[]; core: LatLng[] }>();
function zoneShape(id: string, polygon: LatLng[]) {
  let shape = shapeCache.get(polygon);
  if (!shape) {
    const outer = organicPolygon(polygon, id);
    shape = { outer, core: scaleRing(outer, 0.58) };
    shapeCache.set(polygon, shape);
  }
  return shape;
}

function fitOptions(padding: MapPadding): FitBoundsOptions {
  return { paddingTopLeft: [padding[3], padding[0]], paddingBottomRight: [padding[1], padding[2]] };
}

/** Keeps the view framed on the target and repaints tiles when the container resizes. */
function ViewController({ bounds, padding, animate }: { bounds: LatLngBounds; padding: MapPadding; animate: boolean }) {
  const map = useMap();
  const key = bounds.toBBoxString();
  const latest = useRef({ bounds, padding });
  latest.current = { bounds, padding };
  const previousKey = useRef(key);

  useEffect(() => {
    if (previousKey.current === key) return;
    previousKey.current = key;
    const { bounds: target, padding: pad } = latest.current;
    if (animate) map.flyToBounds(target, { ...fitOptions(pad), duration: 0.9 });
    else map.fitBounds(target, fitOptions(pad));
  }, [map, key, animate]);

  useEffect(() => {
    let lastSize = "";
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const size = `${Math.round(entry.contentRect.width)}x${Math.round(entry.contentRect.height)}`;
      if (size === lastSize) return;
      lastSize = size;
      map.invalidateSize({ pan: false });
      map.fitBounds(latest.current.bounds, fitOptions(latest.current.padding));
    });
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);

  return null;
}

/** Listens for 'fo-map-pan' custom events from the search bar and flies to the location. */
function MapPanHandler() {
  const map = useMap();
  useEffect(() => {
    const handler = (e: Event) => {
      const { lat, lon, zoom } = (e as CustomEvent).detail;
      if (lat != null && lon != null) map.flyTo([lat, lon], zoom ?? 15, { duration: 0.8 });
    };
    window.addEventListener("fo-map-pan", handler);
    return () => window.removeEventListener("fo-map-pan", handler);
  }, [map]);
  return null;
}

export default function FloodMapView({
  layers = DEFAULT_LAYERS,
  interactive = true,
  showRoutes = false,
  focus = "area",
  padding = DEFAULT_PADDING,
  basemap = "dark",
}: {
  layers?: MapLayers | undefined;
  interactive?: boolean | undefined;
  showRoutes?: boolean | undefined;
  focus?: "area" | "route" | undefined;
  padding?: MapPadding | undefined;
  basemap?: "dark" | "satellite" | undefined;
}) {
  const sim = useSim();
  const bbox = sim.studyArea?.bbox;

  const areaBounds = useMemo(
    () => bbox
      ? latLngBounds([bbox.min_lat, bbox.min_lon], [bbox.max_lat, bbox.max_lon])
      : latLngBounds(sim.zones.flatMap((zone) => zone.polygon)),
    [bbox, sim.zones],
  );
  const saferLines = useMemo(() => geoJsonLines(sim.routeResults.floodAware?.geometry), [sim.routeResults.floodAware]);
  const directLines = useMemo(() => geoJsonLines(sim.routeResults.baseline?.geometry), [sim.routeResults.baseline]);
  const routeFocused = focus === "route" && saferLines.length > 0;
  const target = routeFocused ? latLngBounds([...saferLines.flat(), ...directLines.flat()]) : areaBounds;
  // Flood context steps back while a recommended route is on screen.
  const dim = routeFocused ? 0.55 : 1;

  const routeStart = saferLines[0]?.[0];
  const routeEnd = saferLines.at(-1)?.at(-1);
  const siteName = (point: LatLng | undefined, fallback: string) => {
    if (!point) return fallback;
    const site = sim.facilities.find((f) => Math.abs(f.position[0] - point[0]) < 0.0005 && Math.abs(f.position[1] - point[1]) < 0.0005);
    return site?.name ?? fallback;
  };

  const select = (kind: "road" | "zone" | "facility", id: string) =>
    interactive ? { click: () => sim.setSelected({ kind, id }) } : {};

  const wetRoads = layers.roads ? sim.roads.filter((road) => road.depthCm > 0) : [];

  return (
    <MapContainer
      bounds={target}
      boundsOptions={fitOptions(padding)}
      minZoom={11}
      maxZoom={18}
      scrollWheelZoom={interactive}
      dragging={interactive}
      zoomControl={false}
      doubleClickZoom={interactive}
      touchZoom={interactive}
      boxZoom={interactive}
      keyboard={interactive}
      attributionControl={false}
      className="h-full w-full"
    >
      {interactive && <ZoomControl position="topleft" />}
      <ViewController bounds={target} padding={padding} animate={routeFocused} />
      <MapPanHandler />
      {basemap === "satellite" ? (
        <TileLayer
          key="satellite"
          url={ESRI_IMAGERY}
          attribution="Imagery &copy; Esri, Maxar, Earthstar Geographics"
          maxNativeZoom={18}
          maxZoom={19}
          errorTileUrl={BLANK_TILE}
        />
      ) : (
        <TileLayer
          key="dark"
          className="fo-basemap"
          url={`${ESRI_CANVAS}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`}
          attribution="Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
          maxNativeZoom={16}
          maxZoom={18}
          errorTileUrl={BLANK_TILE}
        />
      )}
      <AttributionControl position="bottomright" prefix='<a href="https://leafletjs.com" target="_blank" rel="noreferrer">Leaflet</a>' />
      <ScaleControl position="bottomleft" imperial={false} />

      <Pane name="fo-flood" style={{ zIndex: 410 }}>
        {sim.extent ? (
          <GeoJSON data={sim.extent as never} style={{ color: "#3fa9f5", weight: 1, opacity: 0.6, fillOpacity: 0.22 }} />
        ) : null}
        {layers.floodRisk &&
          sim.zones.filter((z) => z.depthCm > 0).map((z) => {
            const { outer, core } = zoneShape(z.id, z.polygon);
            const color = RISK_COLOR[z.risk];
            const intensity = Math.min(1, z.depthCm / 90);
            return (
              <Fragment key={z.id}>
                <Polygon
                  positions={outer}
                  pathOptions={{
                    color,
                    weight: 1,
                    opacity: 0.5 * dim,
                    fillColor: color,
                    fillOpacity: (layers.floodDepth ? 0.1 + 0.14 * intensity : 0.16) * dim,
                  }}
                  eventHandlers={select("zone", z.id)}
                >
                  <Tooltip sticky>{z.name} — {z.depthCm} cm</Tooltip>
                </Polygon>
                {layers.floodDepth && z.depthCm >= 10 ? (
                  <Polygon
                    positions={core}
                    interactive={false}
                    pathOptions={{ stroke: false, fillColor: color, fillOpacity: (0.12 + 0.22 * intensity) * dim }}
                  />
                ) : null}
              </Fragment>
            );
          })}
      </Pane>

      <Pane name="fo-network" style={{ zIndex: 420 }}>
        {layers.drainage &&
          sim.drainage.map((d) => (
            <Polyline
              key={d.id}
              positions={d.path}
              pathOptions={{ color: DRAIN_COLOR, weight: 2, dashArray: "5 6", opacity: 0.8 * dim, lineCap: "round" }}
            >
              <Tooltip sticky>{d.name}</Tooltip>
            </Polyline>
          ))}
        {/* Casings first so a flooded road never paints over a crossing road. */}
        {wetRoads.map((r) => (
          <Polyline
            key={`${r.id}-casing`}
            positions={r.path}
            interactive={false}
            pathOptions={{ color: CASING, weight: (r.category === "Arterial" ? 4.5 : 3) + 3, opacity: 0.8 * dim, lineCap: "round", lineJoin: "round" }}
          />
        ))}
        {layers.roads &&
          sim.roads.map((r) => {
            const wet = r.depthCm > 0;
            const weight = r.category === "Arterial" ? 4.5 : 3;
            return (
              <Polyline
                key={r.id}
                positions={r.path}
                pathOptions={{
                  color: wet ? RISK_COLOR[r.risk] : DRY_ROAD,
                  weight: wet ? weight : weight - 1,
                  opacity: (wet ? 0.95 : 0.7) * dim,
                  lineCap: "round",
                  lineJoin: "round",
                }}
                eventHandlers={select("road", r.id)}
              >
                <Tooltip sticky>{r.name} — {r.depthCm} cm</Tooltip>
              </Polyline>
            );
          })}
      </Pane>

      <Pane name="fo-labels" style={{ zIndex: 430, pointerEvents: "none" }}>
        <TileLayer
          url={`${ESRI_CANVAS}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`}
          maxNativeZoom={16}
          maxZoom={18}
          opacity={0.7}
          errorTileUrl={BLANK_TILE}
        />
      </Pane>

      <Pane name="fo-routes" style={{ zIndex: 440 }}>
        {directLines.length ? (
          <>
            <Polyline positions={directLines} interactive={false} pathOptions={{ color: CASING, weight: 7, opacity: 0.7, lineCap: "round", lineJoin: "round" }} />
            <Polyline positions={directLines} pathOptions={{ color: DIRECT_COLOR, weight: 3.5, opacity: 0.9, dashArray: "8 7", lineJoin: "round" }}>
              <Tooltip sticky>Direct route — crosses flooded segments</Tooltip>
            </Polyline>
          </>
        ) : null}
        {saferLines.length ? (
          <>
            <Polyline positions={saferLines} interactive={false} pathOptions={{ color: CASING, weight: 11, opacity: 0.9, lineCap: "round", lineJoin: "round" }} />
            <Polyline positions={saferLines} pathOptions={{ color: ROUTE_COLOR, weight: 5.5, opacity: 1, lineCap: "round", lineJoin: "round" }}>
              <Tooltip sticky>Flood-aware route</Tooltip>
            </Polyline>
          </>
        ) : null}
        {showRoutes &&
          sim.routes.map((route) => (
            <Polyline
              key={route.id}
              positions={route.path}
              pathOptions={{
                color: route.id === "safer" ? ROUTE_COLOR : DIRECT_COLOR,
                weight: route.id === "safer" ? 5.5 : 3.5,
                opacity: route.id === "safer" ? 1 : 0.85,
                dashArray: route.id === "safer" ? undefined : "8 7",
                lineCap: "round",
                lineJoin: "round",
              }}
            >
              <Tooltip sticky>{route.label} — {route.distanceKm} km</Tooltip>
            </Polyline>
          ))}
      </Pane>

      <Pane name="fo-sites" style={{ zIndex: 450 }}>
        {sim.facilities
          .filter((f) => (f.type === "Evacuation Centre" ? layers.evacuation : layers.infrastructure))
          .map((f) => {
            const radius = f.type === "Hospital" || f.type === "Evacuation Centre" ? 6.5 : 5;
            return (
              <Fragment key={f.id}>
                <CircleMarker center={f.position} radius={radius + 2.5} interactive={false} pathOptions={{ stroke: false, fillColor: CASING, fillOpacity: 0.75 * dim }} />
                <CircleMarker
                  center={f.position}
                  radius={radius}
                  pathOptions={{
                    color: f.type === "Evacuation Centre" ? EVAC_COLOR : FACILITY_COLOR,
                    weight: 2,
                    opacity: dim,
                    fillColor: RISK_COLOR[f.risk],
                    fillOpacity: 0.95 * dim,
                  }}
                  eventHandlers={select("facility", f.id)}
                >
                  <Tooltip sticky>{f.name} — {f.type}</Tooltip>
                </CircleMarker>
              </Fragment>
            );
          })}
        {routeStart && routeEnd ? (
          <>
            <CircleMarker center={routeStart} radius={7} pathOptions={{ color: ROUTE_COLOR, weight: 3, fillColor: CASING, fillOpacity: 1 }}>
              <Tooltip direction="top" offset={[0, -8]} permanent={routeFocused}>{siteName(routeStart, "Origin")}</Tooltip>
            </CircleMarker>
            <CircleMarker center={routeEnd} radius={8} pathOptions={{ color: "#f2fbff", weight: 2.5, fillColor: ROUTE_COLOR, fillOpacity: 1 }}>
              <Tooltip direction="bottom" offset={[0, 8]} permanent={routeFocused}>{siteName(routeEnd, "Destination")}</Tooltip>
            </CircleMarker>
          </>
        ) : null}
      </Pane>
    </MapContainer>
  );
}
