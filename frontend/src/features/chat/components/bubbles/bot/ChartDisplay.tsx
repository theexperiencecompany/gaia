import { Tab, Tabs } from "@heroui/tabs";
import type React from "react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import {
  Cancel01Icon,
  ChartIcon,
  Download01Icon,
  Image02Icon,
  MaximizeScreenIcon,
} from "@/icons";

interface ChartData {
  id: string;
  url: string;
  text: string;
  type?: string;
  title?: string;
  description?: string;
  chart_data?: {
    type: string;
    title: string;
    x_label: string;
    y_label: string;
    x_unit?: string | null;
    y_unit?: string | null;
    elements: Array<{
      label: string;
      value: number;
      group: string;
    }>;
  };
}

interface ChartDisplayProps {
  charts: ChartData[];
}

// Chart configuration
const createChartConfig = (yLabel: string): ChartConfig => ({
  value: {
    label: yLabel || "Value",
    color: "hsl(var(--chart-1))",
  },
});

// Transform data for recharts
const transformChartData = (
  elements: Array<{ label: string; value: number; group: string }>,
) =>
  elements.map((element) => ({
    name: element.label,
    value: element.value,
    group: element.group,
  }));

// Interactive chart renderer
const InteractiveChart: React.FC<{ chart: ChartData }> = ({ chart }) => {
  if (!chart.chart_data) return null;

  const { chart_data } = chart;
  const chartConfig = createChartConfig(chart_data.y_label);
  const data = transformChartData(chart_data.elements);

  const renderChart = () => {
    const commonProps = { data, config: chartConfig, className: "h-64 w-full" };

    switch (chart_data.type) {
      case "bar":
        return (
          <ChartContainer {...commonProps}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Bar dataKey="value" fill="var(--color-value)" />
            </BarChart>
          </ChartContainer>
        );
      case "line":
        return (
          <ChartContainer {...commonProps}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <ChartTooltip content={<ChartTooltipContent />} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--color-value)"
              />
            </LineChart>
          </ChartContainer>
        );
      case "pie":
        return (
          <ChartContainer {...commonProps}>
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={80}
                fill="var(--color-value)"
              />
              <ChartTooltip content={<ChartTooltipContent />} />
            </PieChart>
          </ChartContainer>
        );
      default:
        return (
          <div className="flex h-64 w-full items-center justify-center rounded-lg bg-zinc-900">
            <p className="text-sm text-zinc-500">Unsupported chart type</p>
          </div>
        );
    }
  };

  return <div className="w-full">{renderChart()}</div>;
};

// Static chart component
const StaticChartItem: React.FC<{
  chart: ChartData;
  onFullscreen: () => void;
  onDownload: () => void;
}> = ({ chart, onFullscreen, onDownload }) => (
  <div className="group relative space-y-2 rounded-lg p-3 transition-colors">
    {chart.title && (
      <h3 className="text-sm font-medium text-zinc-200">{chart.title}</h3>
    )}

    <div className="relative">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={chart.url}
        alt={chart.text}
        className="h-auto w-full cursor-pointer rounded-lg transition-opacity hover:opacity-90"
        onClick={onFullscreen}
      />

      {/* Action buttons */}
      <div className="absolute top-2 right-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={onFullscreen}
          className="rounded-lg bg-black/50 p-1.5 text-white backdrop-blur-sm transition-colors hover:bg-black/70"
          title="View fullscreen"
        >
          <MaximizeScreenIcon className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onDownload}
          className="rounded-lg bg-black/50 p-1.5 text-white backdrop-blur-sm transition-colors hover:bg-black/70"
          title="Download"
        >
          <Download01Icon className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  </div>
);

// Dynamic chart component
const DynamicChartItem: React.FC<{
  chart: ChartData;
  onFullscreen: () => void;
}> = ({ chart, onFullscreen }) => (
  <div className="group relative m-1 mb-5 space-y-2 rounded-lg p-3 outline-1 outline-zinc-600 backdrop-blur-sm transition-colors">
    {chart.title && (
      <h3 className="text-sm font-medium text-zinc-200">{chart.title}</h3>
    )}

    <div className="relative">
      <InteractiveChart chart={chart} />

      {/* Action buttons */}
      <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={onFullscreen}
          className="rounded-lg bg-black/50 p-1.5 text-white backdrop-blur-sm transition-colors hover:bg-black/70"
          title="View fullscreen"
        >
          <MaximizeScreenIcon className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    {chart.description && (
      <p className="line-clamp-2 text-xs text-zinc-400">{chart.description}</p>
    )}
  </div>
);

// Modal component
const ChartModal: React.FC<{
  chart: ChartData;
  onClose: () => void;
  onDownload: (chart: ChartData) => void;
}> = ({ chart, onClose, onDownload }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
    <div className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-2xl bg-zinc-900 shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
        <div>
          <h3 className="font-medium text-zinc-100">
            {chart.title || chart.text}
          </h3>
          {chart.description && (
            <p className="mt-1 text-sm text-zinc-400">{chart.description}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onDownload(chart)}
            className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
            title="Download"
          >
            <Download01Icon className="h-4 w-4" />
          </button>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
            title="Close"
          >
            <Cancel01Icon className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="p-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={chart.url}
          alt={chart.text}
          className="h-auto w-full rounded-lg"
        />
      </div>
    </div>
  </div>
);

// Main component
const ChartDisplay: React.FC<ChartDisplayProps> = ({ charts }) => {
  const [selectedChart, setSelectedChart] = useState<ChartData | null>(null);
  const [viewMode, setViewMode] = useState<"static" | "dynamic">("static");

  if (!charts || charts.length === 0) {
    return null;
  }

  const staticCharts = charts.filter(
    (chart) => chart.url && chart.url.trim() !== "",
  ); // Only charts with valid URLs
  const dynamicCharts = charts.filter((chart) => chart.chart_data); // Only charts with interactive data
  const hasAnyInteractiveData = dynamicCharts.length > 0;

  const handleDownload = async (chart: ChartData) => {
    try {
      const response = await fetch(chart.url);
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${chart.title || chart.text || "chart"}.png`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error("Failed to download chart:", error);
    }
  };

  return (
    <>
      <div>
        {hasAnyInteractiveData ? (
          <>
            <Tabs
              selectedKey={viewMode}
              onSelectionChange={(key) =>
                setViewMode(key as "static" | "dynamic")
              }
              variant="light"
              classNames={{ tabList: "w-full" }}
              className="mb-3 w-full"
              aria-label="Chart view options"
            >
              <Tab
                key="static"
                title={
                  <div className="flex items-center gap-2">
                    <Image02Icon className="h-5 w-5" />
                    Static
                    <div className="flex aspect-square min-h-3 min-w-3 items-center justify-center rounded-full bg-primary/90 p-1.5 text-sm font-medium text-black">
                      {staticCharts.length}
                    </div>
                  </div>
                }
              />
              <Tab
                key="dynamic"
                title={
                  <div className="flex items-center gap-2">
                    <ChartIcon className="h-5 w-5" />
                    Dynamic
                    <div className="flex aspect-square min-h-3 min-w-3 items-center justify-center rounded-full bg-primary/90 p-1.5 text-sm font-medium text-black">
                      {dynamicCharts.length}
                    </div>
                  </div>
                }
              />
            </Tabs>

            <div className="space-y-2">
              {viewMode === "static"
                ? // Show only charts with valid URLs
                  staticCharts.map((chart) => (
                    <StaticChartItem
                      key={chart.id}
                      chart={chart}
                      onFullscreen={() => setSelectedChart(chart)}
                      onDownload={() => handleDownload(chart)}
                    />
                  ))
                : // Show only dynamic charts
                  dynamicCharts.map((chart) => (
                    <DynamicChartItem
                      key={chart.id}
                      chart={chart}
                      onFullscreen={() => setSelectedChart(chart)}
                    />
                  ))}
            </div>
          </>
        ) : (
          // No interactive data - just show static charts with valid URLs
          <div className="space-y-3">
            {staticCharts.map((chart) => (
              <StaticChartItem
                key={chart.id}
                chart={chart}
                onFullscreen={() => setSelectedChart(chart)}
                onDownload={() => handleDownload(chart)}
              />
            ))}
          </div>
        )}
      </div>

      {selectedChart && (
        <ChartModal
          chart={selectedChart}
          onClose={() => setSelectedChart(null)}
          onDownload={handleDownload}
        />
      )}
    </>
  );
};

export default ChartDisplay;
