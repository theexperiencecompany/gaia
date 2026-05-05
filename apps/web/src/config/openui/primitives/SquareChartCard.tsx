import type React from "react";
import type { ChartConfig } from "@/components/ui/chart";
import { ChartContainer } from "@/components/ui/chart";

export interface SquareChartProps {
  config: ChartConfig;
  className?: string;
  /** Side length of the chart in pixels. Defaults to 180. */
  size?: number;
  children: React.ComponentProps<typeof ChartContainer>["children"];
}

/**
 * Square chart wrapper shared by GaugeChart, PieChart, and RadarChart so
 * they render at identical dimensions across the library. Forces a fixed
 * NxN box on the recharts ResponsiveContainer (which otherwise inherits
 * `aspect-video` from `ChartContainer`).
 */
export function SquareChart({
  config,
  className,
  size = 180,
  children,
}: SquareChartProps) {
  return (
    <div
      className="mx-auto"
      style={{ width: `${size}px`, height: `${size}px` }}
    >
      <ChartContainer
        config={config}
        className={`!aspect-square h-full w-full ${className ?? ""}`}
      >
        {children}
      </ChartContainer>
    </div>
  );
}
