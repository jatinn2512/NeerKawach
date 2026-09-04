import { AppShell } from "@/components/AppShell";
import { Metric, Panel, StatusPill } from "@/components/RiskUI";
import { SIM_HISTORY, SYSTEM_SERVICES } from "@/data/pilot";

export function SystemStatusPage() {
  return (
    <AppShell title="System Status" subtitle="Platform health and recent activity">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Platform state" value="Operational" tone="low" />
        <Metric label="Rainfall data age" value="4 min" />
        <Metric label="Runs (last 24h)" value={SIM_HISTORY.length} />
        <Metric label="Avg. run time" value="2.4 s" />
      </div>

      <Panel title="Services" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <th className="px-4 py-2.5 font-medium">Service</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {SYSTEM_SERVICES.map((s) => (
              <tr key={s.name} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium">{s.name}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={s.status} />
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{s.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Recent simulation runs" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] tracking-[0.12em] text-muted-foreground uppercase">
              <th className="px-4 py-2.5 font-medium">Run ID</th>
              <th className="px-4 py-2.5 font-medium">Scenario</th>
              <th className="px-4 py-2.5 font-medium">Operator</th>
              <th className="px-4 py-2.5 font-medium">Started</th>
              <th className="px-4 py-2.5 font-medium">Duration</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {SIM_HISTORY.map((r) => (
              <tr key={r.id} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium tabular">{r.id}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{r.scenario}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{r.operator}</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">{r.started}</td>
                <td className="px-4 py-2.5 tabular">{r.duration}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={r.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </AppShell>
  );
}


