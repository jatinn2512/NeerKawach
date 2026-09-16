import { RouteLink, useNavigate } from "@/utils/router";
import {
  Activity,
  AlertTriangle,
  Database,
  FileText,
  Gauge,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  Megaphone,
  Route as RouteIcon,
  Settings,
  ShieldAlert,
  Waves,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { REGION } from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";
import { RiskBadge } from "./RiskUI";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/simulation", label: "Flood Simulation", icon: Gauge },
  { to: "/map", label: "Flood Map", icon: MapIcon },
  { to: "/risk", label: "Risk & Alerts", icon: ShieldAlert },
  { to: "/safer-routes", label: "Safer Routes", icon: RouteIcon },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/data-layers", label: "Data & Layers", icon: Database },
  { to: "/system-status", label: "System Status", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

export function AppShell({
  title,
  subtitle,
  actions,
  children,
  flush = false,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  const sim = useSim();
  const navigate = useNavigate();

  useEffect(() => {
    if (!sim.signedIn) navigate("/");
  }, [sim.signedIn, navigate]);

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 flex w-64 flex-col border-r border-sidebar-border bg-sidebar">
        <div className="flex items-center gap-2.5 border-b border-sidebar-border px-4 py-4">
          <span className="flex size-9 items-center justify-center rounded-md bg-primary/15 text-primary">
            <Waves className="size-5" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-wide text-sidebar-foreground">
              FloodOps
            </p>
            <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
              Flood Decision Support
            </p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.map((item) => (
            <RouteLink
              key={item.to}
              to={item.to}
              className="flex items-center gap-2.5 rounded-sm px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              activeProps={{
                className:
                  "bg-sidebar-accent text-sidebar-accent-foreground font-medium border-l-2 border-primary",
              }}
            >
              <item.icon className="size-4 shrink-0" />
              {item.label}
            </RouteLink>
          ))}

          <div className="mt-3 border-t border-sidebar-border pt-3">
            <p className="px-3 pb-1 text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Secondary
            </p>
            <RouteLink
              to="/public-alerts"
              className="flex items-center gap-2.5 rounded-sm px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              activeProps={{
                className:
                  "bg-sidebar-accent text-sidebar-accent-foreground font-medium border-l-2 border-primary",
              }}
            >
              <Megaphone className="size-4 shrink-0" />
              Public Alerts
            </RouteLink>
          </div>
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <div className="rounded-md bg-sidebar-accent/60 px-3 py-2.5">
            <p className="text-sm font-medium text-sidebar-foreground">
              {sim.operator.name}
            </p>
            <p className="text-[11px] text-muted-foreground">{sim.operator.role}</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground tabular">
              ID {sim.operator.id}
            </p>
          </div>
          <button
            onClick={() => {
              sim.signOut();
              navigate("/");
            }}
            className="mt-2 flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          >
            <LogOut className="size-4" /> Logout
          </button>
        </div>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col pl-64">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-border bg-background/95 px-6 py-3 backdrop-blur">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            <p className="text-xs text-muted-foreground">
              {subtitle ?? `${REGION.area} · ${REGION.city}`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {actions}
            <div className="hidden items-center gap-3 rounded-md border border-border bg-card px-3 py-1.5 lg:flex">
              <AlertTriangle className="size-4 text-risk-high" />
              <div className="leading-tight">
                <p className="text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                  Live risk
                </p>
                <p className="text-xs font-medium tabular">
                  T+{sim.metrics.clock} · max {sim.metrics.maxDepthCm} cm
                </p>
              </div>
              <RiskBadge risk={sim.metrics.overallRisk} />
            </div>
          </div>
        </header>

        <main className={cn("flex-1", flush ? "" : "space-y-4 p-6")}>{children}</main>
      </div>
    </div>
  );
}
