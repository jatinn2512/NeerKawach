import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { Panel } from "@/components/RiskUI";
import { CITY_OPTIONS, REGION_OPTIONS } from "@/data/pilot";

export function SettingsPage() {
  const [units, setUnits] = useState("cm");
  const [threshold, setThreshold] = useState(30);
  const [autoPlay, setAutoPlay] = useState(true);
  const [labels, setLabels] = useState(true);

  return (
    <AppShell title="Settings" subtitle="Operator and console preferences">
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Operator profile">
          <dl className="space-y-2 text-sm">
            {[
              ["Name", "K. Rajesh"],
              ["Operator ID", "DDMA-BLR-0142"],
              ["Role", "Flood Operations Officer"],
              ["Department", "District Disaster Management Authority"],
              ["Access level", "Simulation + Reporting"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-border/60 pb-1.5 last:border-0">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>

        <Panel title="Defaults">
          <div className="space-y-3">
            <Field label="Default region">
              <select className="w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none">
                {REGION_OPTIONS.map((r) => (
                  <option key={r.id}>{r.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Default city">
              <select className="w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none">
                {CITY_OPTIONS.map((c) => (
                  <option key={c.id}>{c.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Depth units">
              <select
                value={units}
                onChange={(e) => setUnits(e.target.value)}
                className="w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"
              >
                <option value="cm">Centimetres (cm)</option>
                <option value="m">Metres (m)</option>
              </select>
            </Field>
          </div>
        </Panel>

        <Panel title="Alert thresholds">
          <Field label={`High-risk depth threshold — ${threshold} cm`}>
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </Field>
          <p className="mt-2 text-xs text-muted-foreground">
            Road segments exceeding this simulated depth are flagged as high risk
            on the map, in the risk panel and in generated reports.
          </p>
        </Panel>

        <Panel title="Map preferences">
          <div className="space-y-3">
            <Toggle
              label="Auto-play timeline after a simulation completes"
              checked={autoPlay}
              onChange={setAutoPlay}
            />
            <Toggle label="Show facility labels on the map" checked={labels} onChange={setLabels} />
          </div>
        </Panel>
      </div>

      <div>
        <button
          onClick={() => toast.success("Preferences saved")}
          className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Save Preferences
        </button>
      </div>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-primary"
      />
    </label>
  );
}


