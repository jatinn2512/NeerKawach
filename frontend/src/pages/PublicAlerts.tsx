import { Megaphone, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { RISK_LABEL } from "@/data/pilot";

const SENT = [
  { id: "ALT-2026-118", area: "Bellandur Ward", level: "High", issued: "Today, 09:20", status: "Sent" },
  { id: "ALT-2026-117", area: "Koramangala 3rd Block", level: "Moderate", issued: "Today, 08:05", status: "Sent" },
  { id: "ALT-2026-116", area: "HSR Layout Sector 1", level: "Moderate", issued: "Yesterday, 21:10", status: "Expired" },
];

export function PublicAlertsPage() {
  const sim = useSim();
  const m = sim.metrics;
  const [area, setArea] = useState(sim.studyArea?.name ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState(
    "Flood warning: validated flood-product context is required before drafting a public message. Avoid affected roads and follow instructions from local authorities.",
  );

  return (
    <AppShell
      title="Public Alerts"
      subtitle="Draft warnings for affected wards — dispatch requires operator confirmation"
    >
      <div className="flex items-start gap-2 rounded-md border-l-2 border-risk-moderate bg-risk-moderate/8 p-3 text-xs">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-risk-moderate" />
        <p>
          This is a prototype interface. Alerts drafted here are not transmitted
          to any public channel. In production, dispatch would require a second
          authorised approval and integration with the state warning gateway.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Panel title="Draft alert">
          <div className="space-y-4">
            <label className="block">
              <span className="text-xs text-muted-foreground">
                Target area
              </span>
              <select
                value={area}
                onChange={(e) => setArea(e.target.value)}
                className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"
              >
                <option value={sim.studyArea?.name ?? "Unavailable"}>{sim.studyArea?.name ?? "Unavailable"}</option>
              </select>
            </label>

            <label className="block">
              <span className="text-xs text-muted-foreground">
                Message to public
              </span>
              <textarea
                value={message}
                maxLength={480}
                onChange={(e) => setMessage(e.target.value)}
                rows={6}
                className="mt-1.5 w-full resize-none rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none"
              />
              <span className="mt-1 block text-right text-xs text-muted-foreground tabular">
                {message.length}/480
              </span>
            </label>

            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="mt-0.5 size-4"
              />
              <span>
                I confirm this warning has been reviewed against the current
                simulation results and is approved for dispatch.
              </span>
            </label>

            <button
              disabled={!confirmed || message.trim().length < 20 || !sim.summary}
              onClick={() =>
                toast.success("Alert queued for dispatch", {
                  description: `${area} · ${RISK_LABEL[m.overallRisk]} risk warning (prototype — not transmitted).`,
                })
              }
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Megaphone className="size-4" /> Dispatch Alert
            </button>
          </div>
        </Panel>

        <Panel title="Context from active simulation">
          <dl className="space-y-2 text-sm">
            {[
              ["Replay timestamp", sim.selectedTimestamp ?? "Unavailable"],
              ["Simulation time", m.clock],
              ["Max depth", sim.summary ? `${m.maxDepthCm.toFixed(1)} cm` : "Unavailable"],
              ["Affected area", sim.summary ? `${m.affectedAreaKm2.toFixed(3)} km²` : "Unavailable"],
              ["Affected roads", sim.roadImpact ? `${m.highRiskRoads}` : "Unavailable"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-border/60 pb-1.5 last:border-0">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="font-medium tabular">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-3">
            {sim.summary ? <RiskBadge risk={m.overallRisk} /> : <StatusPill status="Unavailable" />}
          </div>
        </Panel>
      </div>

      <Panel title="Alert history" bodyClassName="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">Alert ID</th>
              <th className="px-4 py-2.5 font-medium">Area</th>
              <th className="px-4 py-2.5 font-medium">Level</th>
              <th className="px-4 py-2.5 font-medium">Issued</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {([] as typeof SENT).map((a) => (
              <tr key={a.id} className="border-b border-border/60 last:border-0">
                <td className="px-4 py-2.5 font-medium tabular">{a.id}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{a.area}</td>
                <td className="px-4 py-2.5">{a.level}</td>
                <td className="px-4 py-2.5 text-muted-foreground tabular">{a.issued}</td>
                <td className="px-4 py-2.5">
                  <StatusPill status={a.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </AppShell>
  );
}


