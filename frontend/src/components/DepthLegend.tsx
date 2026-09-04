import { RISK_COLOR, type RiskLevel } from "@/data/pilot";

const entries: [RiskLevel, string][] = [["low", "0 – 10 cm"], ["moderate", "10 – 30 cm"], ["high", "30 – 50 cm"], ["severe", "> 50 cm"]];

export function DepthLegend() {
  return <ul className="space-y-2 text-xs">{entries.map(([risk, label]) => <li key={risk} className="flex items-center gap-2"><span className="size-3 rounded-sm" style={{ backgroundColor: RISK_COLOR[risk] }} /><span className="text-muted-foreground">{label}</span></li>)}</ul>;
}
