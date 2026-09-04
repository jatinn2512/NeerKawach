import { lazy, Suspense } from "react";
import { cn } from "@/lib/utils";
import type { MapLayers } from "./map-layers";

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
    </div>
  );
}

