import { lazy, Suspense } from "react";
import { cn } from "@/lib/utils";
import type { MapLayers } from "./map-layers";
import { useSim } from "@/state/simulation";

const FloodMapView = lazy(() => import("./FloodMapView"));

function MapSkeleton() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-panel">
      <p className="text-xs tracking-[0.2em] text-muted-foreground uppercase">
        Loading geospatial layers…
      </p>
    </div>
  );
}

export function MapSurface({
  className,
  layers,
  interactive = true,
  showRoutes = false,
  zoom,
}: {
  className?: string | undefined;
  layers?: MapLayers | undefined;
  interactive?: boolean | undefined;
  showRoutes?: boolean | undefined;
  zoom?: number | undefined;
}) {
  const sim = useSim();
  if (!sim.studyArea) {
    return <div className={cn("flex items-center justify-center bg-panel p-6 text-center text-xs text-muted-foreground", className)}>
      {sim.dataStatus === "loading" ? "Loading study-area metadata…" : "Study-area metadata unavailable. Start the backend and retry."}
    </div>;
  }
  return (
    <div className={cn("relative overflow-hidden bg-panel", className)}>
      <Suspense fallback={<MapSkeleton />}>
          <FloodMapView
            layers={layers}
            interactive={interactive}
            showRoutes={showRoutes}
            zoom={zoom}
          />
      </Suspense>
      {sim.dataStatus === "unavailable" ? <div className="absolute inset-x-3 top-3 z-[1000] rounded-md border border-status-warn/40 bg-card/95 px-3 py-2 text-xs text-status-warn shadow-lg">Validated flood geometry is unavailable; no flood layer is being shown.</div> : null}
      {sim.dataStatus === "error" ? <div className="absolute inset-x-3 top-3 z-[1000] rounded-md border border-status-down/40 bg-card/95 px-3 py-2 text-xs text-status-down shadow-lg">{sim.dataError}</div> : null}
    </div>
  );
}

