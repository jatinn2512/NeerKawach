import { RISK_COLOR, type RiskLevel } from "@/data/pilot";

export { RISK_COLOR };

export function riskColor(risk: RiskLevel) {
  return RISK_COLOR[risk];
}
