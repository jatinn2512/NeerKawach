import { useEffect } from "react";
import { SimulationProvider, useSim } from "@/state/simulation";
import { navigate, usePathname } from "@/utils/router";
import { LoginPage } from "@/pages/Login";
import { DashboardPage } from "@/pages/Dashboard";
import { SimulationPage } from "@/pages/Simulation";
import { MapPage } from "@/pages/FloodMap";
import { RiskPage } from "@/pages/RiskAlerts";
import { SaferRoutesPage } from "@/pages/SafeRoutes";
import { ReportsPage } from "@/pages/Reports";
import { DataLayersPage } from "@/pages/DataLayers";
import { SystemStatusPage } from "@/pages/SystemStatus";
import { SettingsPage } from "@/pages/Settings";
import { PublicAlertsPage } from "@/pages/PublicAlerts";
import { HomePage } from "@/pages/Home";

function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">The requested Neer Kawach route does not exist.</p>
        <button className="mt-6 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground" onClick={() => navigate("/dashboard")}>Go to dashboard</button>
      </div>
    </div>
  );
}

function RouterView() {
  const path = usePathname();
  const sim = useSim();
  const isPublicPath = path === "/" || path === "/login";

  useEffect(() => {
    if (!sim.signedIn && !isPublicPath) navigate("/");
  }, [path, sim.signedIn, isPublicPath]);

  if (!sim.signedIn) return path === "/login" ? <LoginPage /> : <HomePage />;
  switch (path) {
    case "/": return <HomePage />;
    case "/login": return <DashboardPage />;
    case "/dashboard": return <DashboardPage />;
    case "/simulation": return <SimulationPage />;
    case "/map": return <MapPage />;
    case "/risk": return <RiskPage />;
    case "/safer-routes": return <SaferRoutesPage />;
    case "/reports": return <ReportsPage />;
    case "/data-layers": return <DataLayersPage />;
    case "/system-status": return <SystemStatusPage />;
    case "/settings": return <SettingsPage />;
    case "/public-alerts": return <PublicAlertsPage />;
    default: return <NotFound />;
  }
}

export default function App() {
  return <SimulationProvider><RouterView /></SimulationProvider>;
}
