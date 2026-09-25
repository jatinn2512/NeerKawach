import { ArrowRight, CheckCircle2, CloudRain, Loader2, Play } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { SIM_STAGES } from "@/data/pilot";
import { DEMO_TIMELINE } from "@/data/demo";
import { useNavigate } from "@/utils/router";

export function SimulationPage() {
  const sim = useSim();
  const navigate = useNavigate();
  const currentStage = Math.min(sim.stage, SIM_STAGES.length - 1);

  return (
    <AppShell
      title="Flood Simulation"
      subtitle="Bellandur, Bengaluru · deterministic extreme rainfall event"
      actions={
        <button
          onClick={sim.runSimulation}
          disabled={sim.status === "running"}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
        >
          {sim.status === "running" ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          {sim.status === "running" ? "Processing…" : "Run Simulation"}
        </button>
      }
    >
      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel title="Rainfall event">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary"><CloudRain className="size-5" /></span>
            <div>
              <p className="font-semibold">Extreme monsoon storm</p>
              <p className="mt-1 text-sm text-muted-foreground">Heavy rainfall across the Bellandur–Koramangala catchment, with drainage surcharge expected after T+01:00.</p>
            </div>
            <RiskBadge risk="severe" label="Extreme event" className="ml-auto" />
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Data label="Peak intensity" value="118 mm/hr" />
            <Data label="Accumulated" value={`${sim.metrics.accumulatedRainfallMm} mm`} />
            <Data label="Duration" value="3 hours" />
            <Data label="Study area" value="46.8 km²" />
          </div>
        </Panel>

        <Panel title="Simulation status">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-lg font-semibold">{sim.status === "running" ? SIM_STAGES[currentStage] : sim.status === "complete" ? "Simulation Complete" : "Ready to run"}</p>
              <p className="mt-1 text-xs text-muted-foreground">{sim.status === "running" ? "Processing terrain, rainfall and road accessibility layers" : sim.status === "complete" ? "Flood result is ready for timeline playback" : "Start the run to generate the flood-depth map"}</p>
            </div>
            <StatusPill status={sim.status === "running" ? "Processing" : sim.status === "complete" ? "Available" : "Draft"} />
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all duration-300" style={{ width: `${sim.progress}%` }} /></div>
          <p className="mt-2 text-right text-xs text-muted-foreground tabular">{sim.progress}%</p>
        </Panel>
      </div>

      <Panel title="Processing sequence">
        <ol className="grid gap-x-6 gap-y-3 md:grid-cols-2 xl:grid-cols-4">
          {SIM_STAGES.map((stage, index) => {
            const complete = sim.stage > index;
            const active = sim.status === "running" && sim.stage === index;
            return (
              <li key={stage} className="flex items-center gap-2.5 text-sm">
                {complete ? <CheckCircle2 className="size-4 text-status-ok" /> : active ? <Loader2 className="size-4 animate-spin text-primary" /> : <span className="flex size-4 items-center justify-center rounded-full border border-border text-[10px] text-muted-foreground">{index + 1}</span>}
                <span className={active ? "font-medium text-primary" : complete ? "text-foreground" : "text-muted-foreground"}>{stage}</span>
              </li>
            );
          })}
        </ol>
      </Panel>

      <Panel title="Flood progression preview" action={sim.status === "complete" ? <button onClick={() => navigate("/map")} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">View flood map <ArrowRight className="size-3.5" /></button> : null}>
        <div className="grid gap-2 md:grid-cols-7">
          {DEMO_TIMELINE.map((point) => {
            const active = point.label === sim.selectedTimestamp;
            return <button key={point.label} onClick={() => sim.setSelectedTimestamp(point.label)} className={`rounded-md p-2.5 text-left transition-colors ${active ? "bg-primary/12 ring-1 ring-primary/60" : "bg-panel hover:bg-accent"}`}><p className="text-xs font-semibold tabular">{point.label}</p><p className="mt-2 text-sm font-medium tabular">{point.rainfallMmHr} <span className="text-[10px] text-muted-foreground">mm/hr</span></p><p className="mt-1 text-xs text-muted-foreground tabular">{point.maxDepthCm} cm depth</p></button>;
          })}
        </div>
      </Panel>
    </AppShell>
  );
}

function Data({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md bg-panel p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-sm font-semibold tabular">{value}</p></div>;
}
