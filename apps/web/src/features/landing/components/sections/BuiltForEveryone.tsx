"use client";

import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const CHART_DATA = [
  { occupation: "Computer Programmers", actual: 75, theoretical: 95 },
  { occupation: "Customer Service", actual: 67, theoretical: 88 },
  { occupation: "Data Entry Keyers", actual: 67, theoretical: 82 },
  { occupation: "Computer & Math", actual: 33, theoretical: 94 },
  { occupation: "Office & Admin", actual: 8, theoretical: 90 },
  { occupation: "Sales & Marketing", actual: 12, theoretical: 65 },
  { occupation: "Healthcare", actual: 5, theoretical: 45 },
  { occupation: "Food & Service", actual: 0, theoretical: 15 },
];

const OCCUPATION_SLUG: Record<string, string> = {
  "Computer Programmers": "software-developers",
  "Customer Service": "customer-success",
  "Computer & Math": "software-developers",
  "Office & Admin": "operations-managers",
  "Sales & Marketing": "sales-professionals",
};

const PERSONA_CHIPS = [
  { label: "Chiefs of Staff", slug: "chiefs-of-staff" },
  { label: "Recruiters", slug: "recruiters" },
  { label: "Agency Owners", slug: "agency-owners" },
  { label: "Founders", slug: "startup-founders" },
  { label: "Sales Professionals", slug: "sales-professionals" },
  { label: "Operations Managers", slug: "operations-managers" },
  { label: "Lawyers", slug: "lawyers" },
  { label: "HR Managers", slug: "hr-managers" },
];

const COLOR_ACTUAL = "#00bbff";
const COLOR_THEORETICAL = "#52525b";

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
  const slug = label ? OCCUPATION_SLUG[label] : undefined;

  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-900 p-3 text-sm shadow-xl">
      {slug ? (
        <Link
          href={`/for/${slug}`}
          className="mb-2 block font-medium text-zinc-100 hover:text-primary transition-colors"
        >
          {label}
        </Link>
      ) : (
        <p className="mb-2 font-medium text-zinc-100">{label}</p>
      )}
      {payload.map((item) => (
        <div key={item.name} className="flex items-center gap-2 text-zinc-300">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: item.color }}
          />
          <span>{item.name}:</span>
          <span className="font-medium">{item.value}%</span>
        </div>
      ))}
    </div>
  );
}

export default function BuiltForEveryone() {
  return (
    <section className="flex flex-col items-center px-4 py-24 sm:px-6 sm:py-28 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center gap-12">
        {/* Eyebrow */}
        <p className="text-primary text-xs uppercase tracking-widest font-medium">
          AI shouldn&apos;t only be for engineers
        </p>

        {/* Headline */}
        <h2 className="text-4xl sm:text-5xl md:text-6xl font-medium font-serif! text-center tracking-tight max-w-4xl">
          Today, AI works hardest for developers. GAIA works for everyone else.
        </h2>

        {/* Body text */}
        <p className="text-base sm:text-xl text-zinc-400 font-light text-center max-w-3xl">
          Anthropic&apos;s research shows computer programmers are 75%
          AI-covered. Operations, sales, recruiting, legal, HR — the people who
          actually run companies — are barely touched. GAIA is built for them.
        </p>

        {/* Chart */}
        <div className="w-full max-w-4xl">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart
              data={CHART_DATA}
              layout="vertical"
              margin={{ top: 0, right: 24, bottom: 0, left: 140 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#27272a"
                horizontal={false}
              />
              <XAxis
                type="number"
                domain={[0, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tick={{ fill: "#a1a1aa", fontSize: 12 }}
                axisLine={{ stroke: "#3f3f46" }}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="occupation"
                width={136}
                tick={({
                  x,
                  y,
                  payload,
                }: {
                  x: number;
                  y: number;
                  payload: { value: string };
                }) => {
                  const slug = OCCUPATION_SLUG[payload.value];
                  return (
                    <foreignObject
                      x={x - 136}
                      y={y - 10}
                      width={132}
                      height={20}
                    >
                      {slug ? (
                        <a
                          href={`/for/${slug}`}
                          className="block text-right text-xs text-primary hover:underline leading-5 truncate"
                        >
                          {payload.value}
                        </a>
                      ) : (
                        <span className="block text-right text-xs text-zinc-400 leading-5 truncate">
                          {payload.value}
                        </span>
                      )}
                    </foreignObject>
                  );
                }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                content={<CustomTooltip />}
                cursor={{ fill: "rgba(255,255,255,0.03)" }}
              />
              <Legend
                wrapperStyle={{
                  fontSize: 12,
                  color: "#a1a1aa",
                  paddingTop: 12,
                }}
              />
              <Bar
                dataKey="theoretical"
                name="Theoretical potential"
                fill={COLOR_THEORETICAL}
                radius={[0, 3, 3, 0]}
                barSize={8}
              />
              <Bar
                dataKey="actual"
                name="Actual AI usage"
                fill={COLOR_ACTUAL}
                radius={[0, 3, 3, 0]}
                barSize={8}
              />
            </BarChart>
          </ResponsiveContainer>

          {/* Caption */}
          <p className="text-xs text-zinc-500 mt-2 text-center">
            Source:{" "}
            <a
              href="https://www.anthropic.com/research/labor-market-impacts"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-zinc-300"
            >
              Anthropic Economic Index, 2025
            </a>
          </p>
        </div>

        {/* Persona chips */}
        <div className="flex flex-wrap gap-2 justify-center">
          {PERSONA_CHIPS.map((chip) => (
            <Link
              key={chip.slug}
              href={`/for/${chip.slug}`}
              className="inline-flex items-center rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300 hover:border-primary hover:text-primary transition-colors"
            >
              {chip.label}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
