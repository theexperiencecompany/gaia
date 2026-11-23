import { BarChartCondensed } from "@openuidev/react-ui/Charts/BarChartCondensed";
import { HorizontalBarChart } from "@openuidev/react-ui/Charts/HorizontalBarChart";
import { useRef } from "react";
import { useElementWidth } from "../hooks/useElementWidth";
import { labelsFitUnderBars } from "./barLayout";

interface BarsViewProps {
  data: Record<string, string | number>[];
  palette: string[];
  variant: "grouped" | "stacked";
}

// A vertical axis drops labels that overlap, so a narrow figure lays its bars sideways,
// one labelled row per category.
export function BarsView({ data, palette, variant }: BarsViewProps) {
  const frame = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frame);
  const labels = data.map((point) => String(point.category));
  const shared = {
    data,
    categoryKey: "category",
    variant,
    customPalette: palette,
    isAnimationActive: false,
  } as const;
  return (
    <div ref={frame} className="min-w-0">
      {width && !labelsFitUnderBars(width, labels) ? (
        <HorizontalBarChart {...shared} />
      ) : (
        <BarChartCondensed {...shared} />
      )}
    </div>
  );
}
