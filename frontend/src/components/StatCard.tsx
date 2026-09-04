import type { ComponentProps } from "react";
import { Metric } from "./RiskUI";

export function StatCard(props: ComponentProps<typeof Metric>) {
  return <Metric {...props} />;
}
