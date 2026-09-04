import { AlertTriangle } from "lucide-react";
import { useSim } from "@/state/simulation";
import { RiskBadge, Panel } from "./RiskUI";

export function TopRisks() {
  const { roads } = useSim();
  const risks = roads.filter((road) => road.risk !== "low").sort((a, b) => b.depthCm - a.depthCm).slice(0, 5);
  return <Panel title="Top risks"><ul className="space-y-2">{risks.map((road) => <li key={road.id} className="flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2 text-sm"><AlertTriangle className="size-4 text-risk-high" /><span className="flex-1">{road.name}</span><RiskBadge risk={road.risk} /></li>)}</ul></Panel>;
}
