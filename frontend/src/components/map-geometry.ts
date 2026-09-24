// Display-only geometry helpers for the Leaflet map. They change how features
// are drawn, never the modelled values (depth, risk, distance) behind them.
import type { GeoJson } from "@/api/client";
import type { LatLng } from "@/data/pilot";

/** Small deterministic PRNG so a zone keeps the same outline across renders. */
function seededRandom(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Turns a coarse zone polygon into a softer inundation-style outline:
 * edges get slight deterministic irregularity, then Chaikin smoothing rounds
 * the corners. The shape stays within roughly the original footprint.
 */
export function organicPolygon(points: LatLng[], seed: string, wobble = 0.12, iterations = 3): LatLng[] {
  if (points.length < 3) return points;
  const random = seededRandom(seed);
  let ring: LatLng[] = [];
  points.forEach((a, i) => {
    const b = points[(i + 1) % points.length]!;
    const dLat = b[0] - a[0];
    const dLon = b[1] - a[1];
    ring.push(a);
    for (const t of [1 / 3, 2 / 3]) {
      const offset = (random() - 0.5) * 2 * wobble;
      ring.push([a[0] + dLat * t - dLon * offset, a[1] + dLon * t + dLat * offset]);
    }
  });
  for (let n = 0; n < iterations; n++) {
    ring = ring.flatMap((p, i) => {
      const q = ring[(i + 1) % ring.length]!;
      return [
        [0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]],
        [0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]],
      ] as LatLng[];
    });
  }
  return ring;
}

/** Shrinks a ring toward its vertex centroid (used for the deeper core band). */
export function scaleRing(ring: LatLng[], factor: number): LatLng[] {
  const lat = ring.reduce((sum, p) => sum + p[0], 0) / ring.length;
  const lon = ring.reduce((sum, p) => sum + p[1], 0) / ring.length;
  return ring.map(([a, b]) => [lat + (a - lat) * factor, lon + (b - lon) * factor]);
}

/** Collects every LineString in a GeoJSON object as Leaflet [lat, lon] paths. */
export function geoJsonLines(geo: GeoJson | null | undefined): LatLng[][] {
  const lines: LatLng[][] = [];
  const visit = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    const value = node as { type?: string; geometry?: unknown; features?: unknown[]; coordinates?: unknown };
    if (value.type === "Feature") return visit(value.geometry);
    if (value.type === "FeatureCollection") return value.features?.forEach(visit);
    const toPath = (coords: unknown) => (coords as number[][]).map(([lon, lat]) => [lat, lon] as LatLng);
    if (value.type === "LineString" && Array.isArray(value.coordinates)) lines.push(toPath(value.coordinates));
    if (value.type === "MultiLineString" && Array.isArray(value.coordinates)) value.coordinates.forEach((c) => lines.push(toPath(c)));
  };
  visit(geo);
  return lines.filter((line) => line.length > 1);
}
