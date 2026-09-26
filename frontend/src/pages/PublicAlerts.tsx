import { Megaphone, MessageSquare, Phone, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { Panel, RiskBadge, StatusPill } from "@/components/RiskUI";
import { useSim } from "@/state/simulation";
import { RISK_LABEL } from "@/data/pilot";
import { dispatchAlert, type SmsDispatchResult } from "@/data/demo";
import { cn } from "@/lib/utils";

const SEVERITY_OPTIONS = ["Low", "Moderate", "High", "Severe"] as const;
const AREA_OPTIONS = [
  "Bellandur Ward",
  "Koramangala 3rd Block",
  "HSR Layout Sector 1",
  "Agara Lake Fringe",
  "Ejipura Low-Lying Belt",
];

export function PublicAlertsPage() {
  const sim = useSim();
  const m = sim.metrics;
  const [area, setArea] = useState(AREA_OPTIONS[0]);
  const [severity, setSeverity] = useState<typeof SEVERITY_OPTIONS[number]>("High");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState(
    "Flood warning: heavy rainfall has caused flooding in your area. Avoid affected roads and follow instructions from local authorities.",
  );
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState<SmsDispatchResult | null>(null);
  const [dispatchHistory, setDispatchHistory] = useState<SmsDispatchResult[]>([]);

  const canDispatch = confirmed && message.trim().length >= 20 && !dispatching;

  async function handleDispatch() {
    if (!canDispatch) return;
    setDispatching(true);
    setDispatchResult(null);
    try {
      const result = await dispatchAlert({ area, severity, message });
      setDispatchResult(result);
      setDispatchHistory((prev) => [result, ...prev]);
      setConfirmed(false);
    } finally {
      setDispatching(false);
    }
  }

  return (
    <AppShell
      title="Public Alerts"
      subtitle="Draft warnings for affected wards — dispatch requires operator confirmation"
    >
      {/* Disclaimer banner */}
      <div className="flex items-start gap-2.5 rounded-md border-l-2 border-risk-moderate bg-risk-moderate/8 p-3 text-xs">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-risk-moderate" />
        <p>
          This is a prototype interface. Alerts are dispatched through a local presentation
          adapter — no external SMS provider is configured. In production, dispatch would use
          an SMS gateway (Twilio, MSG91, etc.) requiring a second authorised approval.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        {/* Draft alert form */}
        <div className="rounded-lg border border-white/4 bg-card">
          <header className="flex items-center justify-between gap-3 border-b border-white/4 px-4 py-3">
            <h2 className="text-sm font-semibold">Compose alert</h2>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Phone className="size-3 text-primary" />
              <span>SMS channel</span>
            </div>
          </header>

          <div className="space-y-4 px-4 py-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs text-muted-foreground">Target area</span>
                <select
                  value={area}
                  onChange={(e) => setArea(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none focus:border-primary/60"
                >
                  {AREA_OPTIONS.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="text-xs text-muted-foreground">Severity</span>
                <select
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value as typeof SEVERITY_OPTIONS[number])}
                  className="mt-1.5 w-full rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none focus:border-primary/60"
                >
                  {SEVERITY_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
            </div>

            <label className="block">
              <span className="text-xs text-muted-foreground">Message to public</span>
              <textarea
                value={message}
                maxLength={480}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                className="mt-1.5 w-full resize-none rounded-md border border-input bg-panel px-3 py-2 text-sm outline-none focus:border-primary/60"
              />
              <span className="mt-1 block text-right text-xs text-muted-foreground tabular">
                {message.length}/480
              </span>
            </label>

            {/* Message preview */}
            <div className="rounded-md border border-white/5 bg-panel/50 p-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <MessageSquare className="size-3.5 text-primary" />
                SMS preview
              </div>
              <p className="mt-2 text-xs leading-relaxed text-foreground/80">
                [{severity.toUpperCase()}] Neer Kawach — {area}: {message.slice(0, 160)}{message.length > 160 ? "…" : ""}
              </p>
            </div>

            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="mt-0.5 size-4"
              />
              <span className="text-foreground/80">
                I confirm this warning has been reviewed against the current
                simulation results and is approved for dispatch.
              </span>
            </label>

            <button
              disabled={!canDispatch}
              onClick={handleDispatch}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-md py-2.5 text-sm font-semibold transition-all",
                dispatching
                  ? "bg-primary/60 text-primary-foreground"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
                !canDispatch && "opacity-50 cursor-not-allowed",
              )}
            >
              <Megaphone className="size-4" />
              {dispatching ? "Dispatching…" : "Dispatch Alert via SMS"}
            </button>
          </div>

          {/* Dispatch result */}
          {dispatchResult && (
            <div className="border-t border-white/4 px-4 py-3">
              <div className={cn(
                "flex items-center gap-2 text-sm font-semibold",
                dispatchResult.status === "accepted" ? "text-status-ok" : "text-risk-severe",
              )}>
                <span className="size-2 rounded-full bg-current" />
                {dispatchResult.status === "accepted" ? "Dispatch accepted" : "Dispatch failed"}
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Alert ID</dt>
                  <dd className="font-medium tabular">{dispatchResult.id}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Channel</dt>
                  <dd className="font-medium uppercase">{dispatchResult.channel}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Recipients</dt>
                  <dd className="font-semibold text-primary tabular">{dispatchResult.recipientCount}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Time</dt>
                  <dd className="font-medium tabular">{dispatchResult.timestamp}</dd>
                </div>
              </dl>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {dispatchResult.providerNote}
              </p>
            </div>
          )}
        </div>

        {/* Simulation context sidebar */}
        <div className="space-y-4">
          <Panel title="Simulation context">
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

          {/* Dispatch history */}
          {dispatchHistory.length > 0 && (
            <Panel title="Dispatch history">
              <ul className="space-y-2">
                {dispatchHistory.map((d) => (
                  <li key={d.id} className="flex items-center justify-between rounded-md bg-panel/50 px-3 py-2 text-xs">
                    <div>
                      <p className="font-medium tabular">{d.id}</p>
                      <p className="text-muted-foreground">{d.area} · {d.severity}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-status-ok font-medium">{d.recipientCount} recipients</p>
                      <p className="text-muted-foreground">{d.timestamp}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </AppShell>
  );
}
