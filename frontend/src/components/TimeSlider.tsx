import { Pause, Play } from "lucide-react";
import { useSim } from "@/state/simulation";

export function TimeSlider() {
  const sim = useSim();
  return <div className="flex items-center gap-4 rounded-md border border-border bg-card p-4">
    <button className="flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground" onClick={sim.togglePlay} aria-label={sim.playing ? "Pause progression" : "Play progression"}>
      {sim.playing ? <Pause className="size-4" /> : <Play className="size-4" />}
    </button>
    <span className="text-xs text-muted-foreground tabular">00:00</span>
    <input className="h-1.5 flex-1 accent-[var(--primary)]" type="range" min="0" max="3" step="0.5" value={sim.time} onChange={(e) => sim.setTime(Number(e.target.value))} aria-label="Simulation timeline" />
    <span className="text-xs text-muted-foreground tabular">03:00</span>
  </div>;
}
