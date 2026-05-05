"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

// Source: Anthropic Economic Index, 2025
// https://www.anthropic.com/research/labor-market-impacts
// Values are 0-1 (proportion of tasks covered/observed).
const CHART_DATA = [
  { occupation: "Management", theoretical: 0.85, observed: 0.1 },
  { occupation: "Business & finance", theoretical: 0.9, observed: 0.15 },
  { occupation: "Computer & math", theoretical: 0.95, observed: 0.35 },
  { occupation: "Architecture & engineering", theoretical: 0.8, observed: 0.1 },
  { occupation: "Life & social sciences", theoretical: 0.65, observed: 0.05 },
  { occupation: "Social services", theoretical: 0.4, observed: 0.05 },
  { occupation: "Legal", theoretical: 0.95, observed: 0.1 },
  { occupation: "Education & library", theoretical: 0.55, observed: 0.1 },
  { occupation: "Arts & media", theoretical: 0.75, observed: 0.2 },
  { occupation: "Healthcare practitioners", theoretical: 0.55, observed: 0.05 },
  { occupation: "Healthcare support", theoretical: 0.3, observed: 0.05 },
  { occupation: "Protective service", theoretical: 0.3, observed: 0.05 },
  { occupation: "Food & serving", theoretical: 0.1, observed: 0.05 },
  { occupation: "Grounds maintenance", theoretical: 0.1, observed: 0.05 },
  { occupation: "Personal care", theoretical: 0.1, observed: 0.05 },
  { occupation: "Sales", theoretical: 0.3, observed: 0.2 },
  { occupation: "Office & admin", theoretical: 0.85, observed: 0.3 },
  { occupation: "Agriculture", theoretical: 0.1, observed: 0.05 },
  { occupation: "Construction", theoretical: 0.1, observed: 0.05 },
  { occupation: "Installation & repair", theoretical: 0.2, observed: 0.05 },
  { occupation: "Production", theoretical: 0.2, observed: 0.05 },
  { occupation: "Transportation", theoretical: 0.2, observed: 0.05 },
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
        <div className="flex flex-col items-center gap-4 text-center">
          <p className="text-primary text-xs uppercase tracking-widest font-medium">
            Built for the other 95%
          </p>
          <h2 className="text-4xl sm:text-5xl md:text-6xl font-medium font-serif! tracking-tight max-w-3xl">
            AI was built for developers.
            <br />
            GAIA is for everyone else.
          </h2>
          <p className="text-base sm:text-lg text-zinc-400 font-light max-w-2xl">
            Programmers are 75% AI-covered. Operations, legal, sales, HR —
            barely touched.
          </p>
        </div>

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

          <div className="mx-auto w-full max-w-3xl">
            <ResponsiveContainer width="100%" height={620}>
              <RadarChart
                data={CHART_DATA}
                outerRadius="70%"
                margin={{ top: 60, right: 80, bottom: 40, left: 80 }}
              >
                <PolarGrid
                  stroke="#3f3f46"
                  strokeDasharray="2 4"
                  gridType="polygon"
                />
                <PolarAngleAxis
                  dataKey="occupation"
                  tick={{ fill: "#a1a1aa", fontSize: 10 }}
                  tickLine={false}
                />
                <PolarRadiusAxis
                  angle={90}
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
                  strokeWidth={1.5}
                  dot={{ r: 2, fill: COLOR_THEORETICAL, strokeWidth: 0 }}
                />
                <Radar
                  name="Observed AI coverage"
                  dataKey="observed"
                  stroke={COLOR_OBSERVED}
                  fill={COLOR_OBSERVED}
                  fillOpacity={0.45}
                  strokeWidth={1.5}
                  dot={{ r: 2, fill: COLOR_OBSERVED, strokeWidth: 0 }}
                />
                <Tooltip content={<CustomTooltip />} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <p className="mt-2 text-center text-[11px] text-zinc-500">
            Source:{" "}
            <a
              href="https://www.anthropic.com/research/labor-market-impacts"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-zinc-300 transition-colors"
            >
              Anthropic Economic Index, 2025
            </a>
          </p>
        </div>
      </div>
    </section>
  );
}
