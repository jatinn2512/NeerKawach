import { useNavigate } from "@/utils/router";
import { CheckCircle2, Loader2, Play } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

export function SimulationPage() {
  const sim = useSim();
  const navigate = useNavigate();
  const replayAvailable = sim.timestamps.length > 0;

  return (
    <AppShell
      title="Flood Simulation"
      subtitle="Replay validated P7 outputs published by the backend"
    >
      <Panel title="Validated replay data">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="text-sm">
            <p className="font-medium">{sim.studyArea?.name ?? "Study area metadata unavailable"}</p>
            <p className="text-xs text-muted-foreground">
              {sim.summary ? `${sim.timestamps.length} validated timestamps available` : "No validated flood replay is currently available."}
            </p>
          </div>
          <button
            onClick={() => sim.reload()}
            disabled={sim.dataStatus === "loading"}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-bold tracking-wide text-primary-foreground uppercase transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {sim.dataStatus === "loading" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : <Play className="size-4" />}
            {sim.dataStatus === "loading" ? "Loading products" : "Refresh products"}
          </button>
        </div>
        <div className={cn("mt-5 border-t border-border pt-4", replayAvailable ? "" : "text-sm text-muted-foreground")}>
          {replayAvailable ? <p>Choose a timestamp from the flood map time slider to inspect the validated products.</p> : <p>{sim.dataError ?? "Validated replay data is unavailable."}</p>}
          {replayAvailable ? <button onClick={() => void navigate("/map")} className="mt-3 rounded-md bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground">View flood map</button> : null}
        </div>
      </Panel>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] font-medium tracking-[0.1em] text-muted-foreground uppercase">
        {label}
      </span>
      <div className="mt-1.5 [&_.field]:w-full [&_.field]:rounded-md [&_.field]:border [&_.field]:border-input [&_.field]:bg-panel [&_.field]:px-3 [&_.field]:py-2 [&_.field]:text-sm [&_.field]:outline-none">
        {children}
      </div>
    </label>
  );
}


