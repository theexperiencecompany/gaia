"use client";

import { Link } from "@heroui/link";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import LargeHeader from "../shared/LargeHeader";

// Source: Anthropic Economic Index, 2025
// https://www.anthropic.com/research/labor-market-impacts
// Values read directly from the published radar chart (rings at 0.2, 0.4, 0.6, 0.8, 1.0).
const CHART_DATA = [
  { occupation: "Management", theoretical: 0.9, observed: 0.1 },
  { occupation: "Business & finance", theoretical: 0.92, observed: 0.31 },
  { occupation: "Computer & math", theoretical: 0.91, observed: 0.37 },
  {
    occupation: "Architecture & engineering",
    theoretical: 0.83,
    observed: 0,
  },
  { occupation: "Life & social sciences", theoretical: 0.76, observed: 0.1 },
  { occupation: "Social services", theoretical: 0.48, observed: 0.05 },
  { occupation: "Legal", theoretical: 0.9, observed: 0.2 },
  { occupation: "Education & library", theoretical: 0.61, observed: 0.18 },
  { occupation: "Arts & media", theoretical: 0.8, observed: 0.2 },
  { occupation: "Healthcare practitioners", theoretical: 0.6, observed: 0.1 },
  { occupation: "Healthcare support", theoretical: 0.28, observed: 0 },
  { occupation: "Protective service", theoretical: 0.31, observed: 0 },
  { occupation: "Food & serving", theoretical: 0.2, observed: 0 },
  { occupation: "Grounds maintenance", theoretical: 0.1, observed: 0 },
  { occupation: "Personal care", theoretical: 0.2, observed: 0.05 },
  { occupation: "Sales", theoretical: 0.63, observed: 0.2 },
  { occupation: "Office & admin", theoretical: 0.95, observed: 0.3 },
  { occupation: "Agriculture", theoretical: 0.15, observed: 0 },
  { occupation: "Construction", theoretical: 0.17, observed: 0 },
  { occupation: "Installation & repair", theoretical: 0.19, observed: 0 },
  { occupation: "Production", theoretical: 0.2, observed: 0 },
  { occupation: "Transportation", theoretical: 0.1, observed: 0 },
];

const COLOR_THEORETICAL = "#60a5fa";
const COLOR_OBSERVED = "#f87171";

interface TooltipPayloadItem {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

interface AngleTickProps {
  x?: number;
  y?: number;
  cx?: number;
  cy?: number;
  payload?: { value: string };
}

const LABEL_OFFSET = 18;

function renderAngleTick(props: AngleTickProps) {
  const { x = 0, y = 0, cx = 0, cy = 0, payload } = props;
  const dx = x - cx;
  const dy = y - cy;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const nx = x + (dx / dist) * LABEL_OFFSET;
  const ny = y + (dy / dist) * LABEL_OFFSET;

  // textAnchor follows the horizontal direction of the label relative to centre
  const horizontalRatio = dx / dist;
  let textAnchor: "start" | "middle" | "end" = "middle";
  if (horizontalRatio > 0.2) textAnchor = "start";
  else if (horizontalRatio < -0.2) textAnchor = "end";

  return (
    <text
      x={nx}
      y={ny}
      fill="#a1a1aa"
      fontSize={11}
      textAnchor={textAnchor}
      dominantBaseline="middle"
    >
      {payload?.value}
    </text>
  );
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl bg-zinc-900 p-3 text-sm shadow-xl outline outline-1 outline-zinc-800">
      <p className="mb-1.5 font-medium text-zinc-100">{label}</p>
      {payload.map((item) => (
        <div key={item.name} className="flex items-center gap-2 text-zinc-300">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: item.color }}
          />
          <span className="text-xs">{item.name}:</span>
          <span className="text-xs font-medium tabular-nums">
            {Math.round(item.value * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export default function BuiltForEveryone() {
  return (
    <section className="flex flex-col items-center px-4 py-24 sm:px-6 sm:py-32 lg:px-8">
      <div className="flex w-full max-w-6xl flex-col items-center gap-10">
        <LargeHeader
          chipText="Built for the other 95%"
          headingText={
            <>
              AI happened to coding.
              <br />
              It hasn&apos;t happened to anything else yet.
            </>
          }
          subHeadingText="Blue is what LLMs could handle. Red is what they're actually handling. GAIA is built to bridge the gap other assistants have not."
          centered
        />

        <div className="relative w-full">
          {/* Top-right legend */}
          <div className="absolute right-0 top-0 z-10 flex flex-col gap-1.5 text-xs text-zinc-400 sm:right-4 sm:top-4">
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: COLOR_THEORETICAL }}
              />
              Theoretical AI coverage
            </div>
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: COLOR_OBSERVED }}
              />
              Observed AI coverage
            </div>
          </div>

          <div className="mx-auto w-full max-w-5xl">
            <ResponsiveContainer width="100%" height={580}>
              <RadarChart
                data={CHART_DATA}
                outerRadius="78%"
                margin={{ top: 30, right: 120, bottom: 30, left: 120 }}
              >
                <PolarGrid stroke="#3f3f46" gridType="circle" />
                <PolarAngleAxis
                  dataKey="occupation"
                  tick={renderAngleTick}
                  tickLine={false}
                />
                <PolarRadiusAxis
                  angle={135}
                  domain={[0, 1]}
                  tick={{ fill: "#52525b", fontSize: 9 }}
                  tickCount={6}
                  axisLine={false}
                  tickFormatter={(v: number) => v.toFixed(1)}
                  stroke="#3f3f46"
                />
                <Radar
                  name="Theoretical AI coverage"
                  dataKey="theoretical"
                  stroke={COLOR_THEORETICAL}
                  fill={COLOR_THEORETICAL}
                  fillOpacity={0.35}
                  strokeWidth={2}
                  dot={{ r: 3, fill: COLOR_THEORETICAL, strokeWidth: 0 }}
                />
                <Radar
                  name="Observed AI coverage"
                  dataKey="observed"
                  stroke={COLOR_OBSERVED}
                  fill={COLOR_OBSERVED}
                  fillOpacity={0.45}
                  strokeWidth={2}
                  dot={{ r: 3, fill: COLOR_OBSERVED, strokeWidth: 0 }}
                />
                <Tooltip content={<CustomTooltip />} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <div className="mx-auto max-w-3xl space-y-1 text-center text-[11px] text-zinc-500">
            <p className="font-medium text-zinc-400">
              Figure: Theoretical capability and observed exposure by
              occupational category
            </p>
            <p>
              <span className="text-blue-400 pr-1">
                Share of job tasks that LLMs could theoretically perform (blue
                area)
              </span>
              <span className="text-red-400">
                and our own job coverage measure derived from usage data (red
                area).
              </span>
            </p>
            <p className="pt-1">
              Source:{" "}
              <Link
                href="https://www.anthropic.com/research/labor-market-impacts"
                isExternal
                showAnchorIcon={false}
                className="underline underline-offset-2 hover:text-zinc-300 transition-colors"
              >
                Anthropic Economic Index, 2025
              </Link>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
