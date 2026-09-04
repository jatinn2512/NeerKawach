// Browser-safe layer config shared by SSR routes and the Leaflet map component.
export type MapLayers = {
  floodRisk: boolean;
  floodDepth: boolean;
  roads: boolean;
  drainage: boolean;
  infrastructure: boolean;
  evacuation: boolean;
};

export const DEFAULT_LAYERS: MapLayers = {
  floodRisk: true,
  floodDepth: true,
  roads: true,
  drainage: false,
  infrastructure: true,
  evacuation: true,
};


