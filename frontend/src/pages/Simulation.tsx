import { useNavigate } from "@/utils/router";
import { CheckCircle2, ChevronRight, Loader2, Play, Sliders } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge } from "@/components/RiskUI";
import {
  CITY_OPTIONS,
  REGION_OPTIONS,
  SCENARIOS,
  SIM_STAGES,
  WARD_OPTIONS,
  ZONE_OPTIONS,
} from "@/data/pilot";
import { useSim } from "@/state/simulation";
import { cn } from "@/lib/utils";

export function SimulationPage() {
  const sim = useSim();
  const navigate = useNavigate();
  const wards = WARD_OPTIONS[sim.zoneId] ?? [];

  return (
    <AppShell
      title="Flood Simulation"
      subtitle="Configure inputs and execute the hydrodynamic flood model"
    >
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Panel title="1 · Area selection">
          <p className="mb-4 text-xs text-muted-foreground">
            Geographic datasets (elevation, drainage, roads) are preconfigured
            per supported region. Additional regions can be onboarded by the
            GIS cell.
          </p>
          <div className="space-y-3">
            <Field label="Region">
              <select className="field" defaultValue="pilot-blr-01">
                {REGION_OPTIONS.map((r) => (
                  <option key={r.id} value={r.id} disabled={!r.enabled}>
                    {r.label}
                    {r.enabled ? "" : " — not configured"}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="City / Municipal body">
              <select className="field" defaultValue="blr">
                {CITY_OPTIONS.map((c) => (
                  <option key={c.id} value={c.id} disabled={!c.enabled}>
                    {c.label}
                    {c.enabled ? "" : " — not configured"}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Zone">
              <select
                className="field"
                value={sim.zoneId}
                onChange={(e) => {
                  sim.setZoneId(e.target.value);
                  const first = WARD_OPTIONS[e.target.value]?.[0];
                  if (first) sim.setWardId(first.id);
                }}
              >
                {ZONE_OPTIONS.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Ward / Sub-area">
              <select
                className="field"
                value={sim.wardId}
                onChange={(e) => sim.setWardId(e.target.value)}
              >
                {wards.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Panel>

        <Panel title="2 · Rainfall / storm scenario">
          <div className="space-y-2.5">
            {SCENARIOS.map((s) => {
              const active = sim.scenario.id === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => sim.setScenarioId(s.id)}
                  className={cn(
                    "w-full rounded-md border px-3.5 py-3 text-left transition-colors",
                    active
                      ? "border-primary bg-primary/10"
                      : "border-border bg-panel hover:border-primary/50",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold">{s.name}</p>
                    <RiskBadge risk={s.severity} label={`${s.severity} severity`} />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{s.description}</p>
                  <div className="mt-2 flex gap-4 text-xs tabular">
                    <span>
                      <span className="text-muted-foreground">Intensity </span>
                      {s.intensityMmHr} mm/hr
                    </span>
                    <span>
                      <span className="text-muted-foreground">Duration </span>
                      {s.durationHrs} h
                    </span>
                    <span>
                      <span className="text-muted-foreground">Return period </span>
                      {s.returnPeriod}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          <details className="mt-4 rounded-md border border-border bg-panel px-3.5 py-3">
            <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
              <Sliders className="size-4 text-primary" /> Advanced / custom scenario
              <ChevronRight className="ml-auto size-4 text-muted-foreground" />
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Field label="Intensity (mm/hr)">
                <input className="field" type="number" defaultValue={120} min={0} max={400} />
              </Field>
              <Field label="Duration (hours)">
                <input className="field" type="number" defaultValue={4} min={1} max={24} />
              </Field>
              <Field label="Antecedent soil saturation (%)">
                <input className="field" type="number" defaultValue={68} min={0} max={100} />
              </Field>
              <Field label="Drainage efficiency (%)">
                <input className="field" type="number" defaultValue={72} min={0} max={100} />
              </Field>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              Custom scenarios will be submitted to the simulation engine in a
              future release. Predefined scenarios are recommended for
              operational decisions.
            </p>
          </details>
        </Panel>
      </div>

      <Panel title="3 · Execute model">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="text-sm">
            <p className="font-medium">
              {sim.scenario.name} · {sim.scenario.intensityMmHr} mm/hr ·{" "}
              {sim.scenario.durationHrs} hours
            </p>
            <p className="text-xs text-muted-foreground">
              Target:{" "}
              {ZONE_OPTIONS.find((z) => z.id === sim.zoneId)?.label} ·{" "}
              {wards.find((w) => w.id === sim.wardId)?.label}
            </p>
          </div>
          <button
            onClick={sim.runSimulation}
            disabled={sim.status === "running"}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 text-sm font-bold tracking-wide text-primary-foreground uppercase transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {sim.status === "running" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            Run Flood Simulation
          </button>
        </div>

        {sim.status !== "idle" ? (
          <div className="mt-5 space-y-2 border-t border-border pt-4">
            {SIM_STAGES.map((stageLabel, i) => {
              const done = sim.stage > i;
              const active = sim.status === "running" && sim.stage === i;
              return (
                <div
                  key={stageLabel}
                  className={cn(
                    "flex items-center gap-3 rounded-sm px-3 py-2 text-sm",
                    active ? "bg-primary/10 text-foreground" : "text-muted-foreground",
                  )}
                >
                  {done ? (
                    <CheckCircle2 className="size-4 text-risk-low" />
                  ) : active ? (
                    <Loader2 className="size-4 animate-spin text-primary" />
                  ) : (
                    <span className="size-4 rounded-full border border-border" />
                  )}
                  <span>{stageLabel}</span>
                  <span className="ml-auto text-xs tabular">
                    {done ? "done" : active ? "running" : "queued"}
                  </span>
                </div>
              );
            })}

            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all duration-500"
                style={{ width: `${sim.progress}%` }}
              />
            </div>

            {sim.status === "complete" ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-risk-low/40 bg-risk-low/10 px-3.5 py-3">
                <p className="text-sm">
                  Simulation complete — flood depth grid, road risk classification
                  and map layers generated.
                </p>
                <button
                  onClick={() => void navigate("/map")}
                  className="rounded-md bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                >
                  View flood map
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
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


