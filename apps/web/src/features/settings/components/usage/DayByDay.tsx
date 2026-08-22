"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";
import { ShuffleIcon } from "@icons";
import type { UsageActivity } from "@shared/types";
import { formatCompactNumber, formatDateUTC } from "@shared/utils";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { useRecharts } from "@/components/ui/chart-loader";
import { cn } from "@/lib/utils";
import { tokenComparisons } from "./tokenScale";
import { ACCENT, CARD, HEALTHY, InfoTip } from "./usageChrome";
import { TAB_CLASSNAMES } from "./usageTabs";

// recharts is heavy, so it loads on demand instead of shipping eagerly with
// the settings page. The shared promise means every chart here triggers a
// single chunk load.

type Metric = "actions" | "tokens";

const RANGES = [
  { key: "week", label: "Week", days: 7 },
  { key: "month", label: "Month", days: 30 },
  { key: "year", label: "Year", days: 365 },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

/** Seconds between automatic rotations of the token-scale line. */
const ROTATE_MS = 6000;

// Shared x-axis styling for both chart shapes. Static at module scope so
// memoized recharts children see a stable prop instead of a fresh object per
// render.
const X_AXIS = {
  dataKey: "label",
  tickLine: false,
  axisLine: false,
  tickMargin: 8,
  minTickGap: 36,
  tick: { fill: "#71717a", fontSize: 11 },
} as const;

interface Row {
  key: string;
  label: string;
  actions: number;
  input: number;
  output: number;
  cached: number;
  reasoning: number;
  tokens: number;
}

/**
 * Both series come from the daily rollup, which is the only per-day store that
 * reaches back a year — the usage snapshots the message counts used to come
 * from are a short rolling window (the endpoint caps at 90 days and holds far
 * less in practice), so a "year" built from them was mostly zeros.
 */
function buildRows(activity: UsageActivity, days: number): Row[] {
  return activity.days.slice(-days).map((d) => ({
    key: d.date,
    label: formatDateUTC(d.date, "short"),
    actions: d.count,
    input: d.input_tokens,
    output: d.output_tokens,
    cached: d.cached_tokens,
    reasoning: d.reasoning_tokens,
    tokens: d.tokens,
  }));
}

function DayTooltip({
  active,
  payload,
  metric,
}: {
  active?: boolean;
  payload?: { payload: Row }[];
  metric: Metric;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;

  if (metric === "actions") {
    return (
      <div className="rounded-lg bg-zinc-800 px-2.5 py-1.5 text-xs shadow-xl">
        <p className="mb-1 text-zinc-400">{row.label}</p>
        <div className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-[2px]"
            style={{ backgroundColor: HEALTHY }}
          />
          <span className="font-medium text-zinc-100">
            {row.actions} {row.actions === 1 ? "action" : "actions"}
          </span>
        </div>
      </div>
    );
  }

  if (row.tokens === 0) {
    return (
      <div className="rounded-lg bg-zinc-800 px-2.5 py-1.5 text-xs shadow-xl">
        <p className="text-zinc-400">{row.label}</p>
        <p className="mt-0.5 text-zinc-500">Nothing used</p>
      </div>
    );
  }

  // Cached and reasoning are subsets of the two figures above them, so they sit
  // under a rule as detail rather than reading like extra tokens on top.
  const detail = [
    { name: "of input, cached", value: row.cached },
    { name: "of output, reasoning", value: row.reasoning },
  ].filter((d) => d.value > 0);

  return (
    <div className="min-w-44 rounded-lg bg-zinc-800 px-2.5 py-2 text-xs shadow-xl">
      <div className="flex items-baseline justify-between gap-4">
        <p className="text-zinc-400">{row.label}</p>
        <p className="font-semibold tabular-nums text-zinc-100">
          {formatCompactNumber(row.tokens)}
        </p>
      </div>
      <div className="mt-1.5 flex flex-col gap-1">
        {[
          { name: "Input", value: row.input, color: ACCENT },
          { name: "Output", value: row.output, color: HEALTHY },
        ].map((p) => (
          <div key={p.name} className="flex items-center gap-1.5">
            <span
              className="size-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: p.color }}
            />
            <span className="flex-1 text-zinc-400">{p.name}</span>
            <span className="tabular-nums text-zinc-200">
              {p.value.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      {detail.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1 border-t border-zinc-700/70 pt-1.5">
          {detail.map((d) => (
            <div key={d.name} className="flex items-center gap-1.5">
              <span className="flex-1 text-zinc-500">{d.name}</span>
              <span className="tabular-nums text-zinc-400">
                {d.value.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The one line that makes an eight-digit number mean something. Rotates on its
 *  own so it is never the same line twice, with shuffle for anyone who wants to
 *  keep going. */
function TokenScaleLine({ tokens }: { tokens: number }) {
  const lines = useMemo(() => tokenComparisons(tokens), [tokens]);
  const [index, setIndex] = useState(0);

  const next = useCallback(
    () => setIndex((i) => (lines.length ? (i + 1) % lines.length : 0)),
    [lines.length],
  );

  useEffect(() => {
    if (lines.length < 2) return;
    const id = window.setInterval(next, ROTATE_MS);
    return () => window.clearInterval(id);
  }, [lines.length, next]);

  if (!lines.length) return null;

  return (
    <div className="mt-2 flex items-center gap-1">
      <p className="min-w-0 flex-1 truncate text-[13px] text-zinc-500">
        That&apos;s about{" "}
        <span className="font-medium text-zinc-300">
          {lines[index % lines.length]}
        </span>
        .
      </p>
      {lines.length > 1 && (
        <Button
          isIconOnly
          size="sm"
          variant="light"
          radius="full"
          className="size-6 min-w-6 shrink-0 text-zinc-500 data-[hover=true]:text-zinc-200"
          aria-label="Show another comparison"
          onPress={next}
        >
          <ShuffleIcon size={13} />
        </Button>
      )}
    </div>
  );
}

/**
 * One card for "what did each day look like" — actions taken, or tokens burned.
 * They were two cards asking the same question of the same days, which meant
 * two axes to learn and two scales to reconcile; as one switch they compare
 * directly.
 */
export function DayByDay({ activity }: { activity: UsageActivity }) {
  const R = useRecharts();
  const [metric, setMetric] = useState<Metric>("actions");
  const [range, setRange] = useState<RangeKey>("month");
  const days = RANGES.find((r) => r.key === range)?.days ?? 30;
  const rangeLabel = RANGES.find((r) => r.key === range)?.label.toLowerCase();

  const { rows, totalActions, totalTokens } = useMemo(() => {
    const rows = buildRows(activity, days);
    return {
      rows,
      totalActions: rows.reduce((sum, r) => sum + r.actions, 0),
      totalTokens: rows.reduce((sum, r) => sum + r.tokens, 0),
    };
  }, [activity, days]);

  const isTokens = metric === "tokens";
  const isYear = range === "year";
  const total = isTokens ? totalTokens : totalActions;
  const isEmpty = total === 0;
  const seriesKey = isTokens ? "tokens" : "actions";
  const seriesColor = isTokens ? ACCENT : HEALTHY;
  // Distinct per metric so the two gradients can't collide in one document.
  const fillId = `dayByDay-${seriesKey}`;
  // Fewer days, fatter bars — a week of hairlines looks broken.
  const barWidth = range === "week" ? 28 : 10;

  const yAxis = {
    width: 34,
    tickLine: false,
    axisLine: false,
    tickCount: 3,
    tick: { fill: "#71717a", fontSize: 10 },
    tickFormatter: (v: number) =>
      isTokens ? formatCompactNumber(v) : String(v),
  } as const;

  return (
    <section className={cn(CARD, "flex min-w-0 flex-1 flex-col p-5")}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <p className="text-base font-semibold text-white">Day by day</p>
          <InfoTip
            text={
              isTokens
                ? "Tokens charged to you each day. Background work (memory, onboarding) is billed separately and not counted here."
                : "Everything GAIA did for you each day — messages and tool calls."
            }
          />
        </div>
        {/* The metric is what the card IS, so it sits with the title. The range
            drops to the reading line below — side by side the two groups
            collided and forced the heading to wrap. */}
        <Tabs
          size="sm"
          radius="full"
          aria-label="Metric"
          selectedKey={metric}
          onSelectionChange={(k) => setMetric(k as Metric)}
          classNames={TAB_CLASSNAMES}
        >
          <Tab key="actions" title="Actions" />
          <Tab key="tokens" title="Tokens" />
        </Tabs>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3">
        <p className="min-w-0 truncate text-[13px] text-zinc-500">
          <span className="font-medium tabular-nums text-zinc-300">
            {formatCompactNumber(total)}
          </span>{" "}
          {isTokens ? "tokens" : "actions"} in the last {rangeLabel}
        </p>
        <Tabs
          size="sm"
          radius="full"
          aria-label="Range"
          selectedKey={range}
          onSelectionChange={(k) => setRange(k as RangeKey)}
          classNames={TAB_CLASSNAMES}
        >
          {RANGES.map((r) => (
            <Tab key={r.key} title={r.label} />
          ))}
        </Tabs>
      </div>

      {isEmpty ? (
        <div className="flex h-28 w-full items-center justify-center text-sm text-zinc-600">
          Nothing in the last {rangeLabel}.
        </div>
      ) : R ? (
        <ChartContainer
          config={{ value: { label: isTokens ? "Tokens" : "Messages" } }}
          className="mt-3 aspect-auto h-28 w-full"
        >
          {/* A year is 365 categories in ~440px — bars land under a pixel wide
              and read as noise, so the long range switches to a filled line. */}
          {isYear ? (
            <R.AreaChart
              data={rows}
              margin={{ left: 0, right: 0, top: 4, bottom: 0 }}
            >
              <defs>
                <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={seriesColor} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={seriesColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <R.XAxis {...X_AXIS} />
              <R.YAxis {...yAxis} />
              <ChartTooltip content={<DayTooltip metric={metric} />} />
              <R.Area
                dataKey={seriesKey}
                type="monotone"
                stroke={seriesColor}
                strokeWidth={2}
                fill={`url(#${fillId})`}
                dot={false}
              />
            </R.AreaChart>
          ) : (
            <R.BarChart
              data={rows}
              margin={{ left: 0, right: 0, top: 4, bottom: 0 }}
            >
              <R.XAxis {...X_AXIS} />
              <R.YAxis {...yAxis} />
              <ChartTooltip
                cursor={{ fill: "#ffffff08" }}
                content={<DayTooltip metric={metric} />}
              />
              {/* One bar per day, not a stack: the input/output split is
                  hundreds to one, so a stacked cap is invisible and its rounded
                  corner never shows. The split lives in the tooltip, where it
                  is readable, and the bar keeps its rounded top. */}
              <R.Bar
                dataKey={seriesKey}
                radius={4}
                maxBarSize={barWidth}
                fill={seriesColor}
              />
            </R.BarChart>
          )}
        </ChartContainer>
      ) : (
        // Same-box placeholder for the moment before the chart chunk arrives.
        <div className="mt-3 h-28 w-full rounded-lg bg-zinc-800/60" />
      )}

      {isTokens && totalTokens > 0 && <TokenScaleLine tokens={totalTokens} />}
    </section>
  );
}
