import { RouteLink, useNavigate } from "@/utils/router";
import {
  Activity,
  AlertTriangle,
  ChevronLeft,
  Database,
  FileText,
  Gauge,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  Megaphone,
  Menu,
  Route as RouteIcon,
  Settings,
  ShieldAlert,
  Waves,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";
import { RiskBadge, riskText } from "./RiskUI";

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

// Module-level so collapse state survives navigation between pages.
let _sidebarCollapsed = false;

export function AppShell({
  title,
  subtitle,
  actions,
  children,
  flush = false,
  fill = false,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  /** Edge-to-edge content sized to exactly one viewport (full-bleed map pages). */
  flush?: boolean;
  /** Padded content that fills one viewport on wide screens; children may use xl:flex-1. */
  fill?: boolean;
}) {
  const sim = useSim();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(_sidebarCollapsed);

  // Persist across navigations
  useEffect(() => { _sidebarCollapsed = collapsed; }, [collapsed]);

  useEffect(() => {
    if (!sim.signedIn) navigate("/");
  }, [sim.signedIn, navigate]);

  const sidebarW = collapsed ? "w-16" : "w-64";
  const contentPl = collapsed ? "pl-16" : "pl-64";

  return (
    <div className="fo-app-shell flex min-h-screen bg-background">
      <aside className={cn(
        "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-250 ease-in-out",
        sidebarW,
      )}>
        {/* Brand row */}
        <div className="flex items-center gap-2.5 border-b border-sidebar-border px-3 py-4">
          {collapsed ? (
            <button
              onClick={() => setCollapsed(false)}
              className="flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
              aria-label="Expand sidebar"
            >
              <Menu className="size-5" />
            </button>
          ) : (
            <>
              <span className="flex size-9 items-center justify-center rounded-md bg-primary/15 text-primary">
                <Waves className="size-5" />
              </span>
              <div className="min-w-0 flex-1 leading-tight">
                <p className="text-sm font-semibold tracking-wide text-sidebar-foreground">
                  Neer Kawach
                </p>
                <p className="text-[11px] text-muted-foreground">
                  Flood decision support
                </p>
              </div>
              <button
                onClick={() => setCollapsed(true)}
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
                aria-label="Collapse sidebar"
              >
                <ChevronLeft className="size-4" />
              </button>
            </>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-0.5 overflow-y-auto overflow-x-hidden p-2">
          {NAV.map((item) => (
            <RouteLink
              key={item.to}
              to={item.to}
              className={cn(
                "flex items-center gap-2.5 rounded-sm px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground whitespace-nowrap",
                collapsed && "justify-center px-0",
              )}
              activeProps={{
                className:
                  "bg-sidebar-accent text-sidebar-accent-foreground font-medium border-l-2 border-primary",
              }}
            >
              <item.icon className="size-4 shrink-0" />
              {!collapsed && item.label}
            </RouteLink>
          ))}

          <div className="mt-3 border-t border-sidebar-border pt-3">
            {!collapsed && (
              <p className="px-3 pb-1 text-[11px] text-muted-foreground">
                Secondary
              </p>
            )}
            <RouteLink
              to="/public-alerts"
              className={cn(
                "flex items-center gap-2.5 rounded-sm px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground whitespace-nowrap",
                collapsed && "justify-center px-0",
              )}
              activeProps={{
                className:
                  "bg-sidebar-accent text-sidebar-accent-foreground font-medium border-l-2 border-primary",
              }}
            >
              <Megaphone className="size-4 shrink-0" />
              {!collapsed && "Public Alerts"}
            </RouteLink>
          </div>
        </nav>

        {/* Operator */}
        <div className={cn("border-t border-sidebar-border p-3", collapsed && "p-2")}>
          {!collapsed ? (
            <>
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
            </>
          ) : (
            <button
              onClick={() => {
                sim.signOut();
                navigate("/");
              }}
              className="flex w-full items-center justify-center rounded-sm py-2 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              aria-label="Logout"
            >
              <LogOut className="size-4" />
            </button>
          )}
        </div>
      </aside>

      <div className={cn("flex min-h-screen flex-1 flex-col transition-[padding-left] duration-250 ease-in-out", contentPl, flush && "h-screen", fill && "xl:h-screen")}>
        <header className="fo-app-header sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-border bg-background/95 px-6 py-3 backdrop-blur">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            <p className="text-xs text-muted-foreground">
              {subtitle ?? (sim.studyArea ? `${sim.studyArea.name} · ${sim.studyArea.city}` : "Study area metadata unavailable")}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {actions}
            <div className="hidden items-center gap-3 border-l border-white/6 pl-4 lg:flex">
              <AlertTriangle className={cn("size-4", sim.summary ? riskText[sim.metrics.overallRisk] : "text-muted-foreground")} />
              <div className="leading-tight">
                <p className="text-[11px] text-muted-foreground">Live risk</p>
                <p className="text-xs font-medium tabular">
                  {sim.summary ? `T+${sim.metrics.clock} · max ${sim.metrics.maxDepthCm.toFixed(1)} cm` : "Validated flood data unavailable"}
                </p>
              </div>
              {sim.summary ? <RiskBadge risk={sim.metrics.overallRisk} /> : <span className="text-[11px] text-muted-foreground">Unavailable</span>}
            </div>
          </div>
        </header>

        <main className={cn("flex-1", flush ? "min-h-0" : fill ? "flex flex-col gap-4 p-6 xl:min-h-0" : "space-y-4 p-6")}>{children}</main>
      </div>
    </div>
  );
}
