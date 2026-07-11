"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon, SparklesIcon } from "@icons";
import type { FeatureUsage, UsageActivity, UsageSummary } from "@shared/types";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";
import BlurStack from "@/components/ui/blur-stack";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { cn } from "@/lib/utils";
import type { UsageHistoryEntry } from "../../api/usageApi";
import { ActivityBadge, UsageHeatmap } from "./UsageHeatmap";

const ACCENT = "#00bbff"; // brand blue — capacity meters
const HEALTHY = "#30d158"; // apple green — the activity trend
const NEAR = "#fbbf24"; // amber — approaching the limit
const HIT = "#ff453a"; // vibrant red — limit reached
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Only the warning states borrow status hues; the "fine" state is the caller's
 * base color, so a glance separates fine / watch-out / maxed without a rainbow. */
function severityColor(percentage: number, base: string = ACCENT): string {
  if (percentage >= 100) return HIT;
  if (percentage >= 75) return NEAR;
  return base;
}

/** Fraction (0-1) of the current window already elapsed — the "you should be
 * here by now" mark. Simple: elapsed / total, from the window's reset time. */
function elapsedFraction(resetIso: string, period: Period): number {
  const end = new Date(resetIso);
  const start =
    period === "day"
      ? end.getTime() - 86_400_000
      : Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - 1, 1);
  return Math.min(
    1,
    Math.max(0, (Date.now() - start) / (end.getTime() - start)),
  );
}

type Period = "day" | "month";
type PeriodData = NonNullable<FeatureUsage["periods"]["day"]>;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

function fmtCompact(n: number): string {
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return `${n}`;
}

const CARD = "rounded-2xl bg-zinc-900/60";

function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip
      content={text}
      placement="top"
      delay={150}
      closeDelay={0}
      classNames={{
        content: "max-w-64 bg-zinc-800 text-xs text-zinc-300 shadow-xl",
      }}
    >
      <span className="cursor-default text-zinc-600 transition-colors hover:text-zinc-400">
        <InformationCircleIcon size={15} />
      </span>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------

export interface UsageViewProps {
  summary: UsageSummary;
  history: UsageHistoryEntry[];
  activity?: UsageActivity;
  onUpgrade: () => void;
}

export function UsageView({
  summary,
  history,
  activity,
  onUpgrade,
}: UsageViewProps) {
  const isPro = summary.plan_type === "pro";
  const [period, setPeriod] = useState<Period>("day");

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 pb-4">
      {!isPro && (
        <UpgradeBanner
          reason={upgradeReason(summary, history)}
          onUpgrade={onUpgrade}
        />
      )}
      <Hero summary={summary} isPro={isPro} />
      <Stats summary={summary} history={history} />
      <Trend history={history} summary={summary} />
      <div className="flex items-stretch gap-4">
        <DailyBars history={history} summary={summary} />
        {activity && <ActivityBadge tier={activity.tier} activity={activity} />}
      </div>
      {activity && <UsageHeatmap activity={activity} />}
      <Tools summary={summary} period={period} onPeriod={setPeriod} />
    </div>
  );
}

// --- Hero: the one big number + the one big bar ----------------------------

function Hero({ summary, isPro }: { summary: UsageSummary; isPro: boolean }) {
  const [win, setWin] = useState<Period>("month");
  const chatDay = summary.features.chat_messages?.periods.day;
  const chatMonth = summary.features.chat_messages?.periods.month;
  const daily = summary.budget?.daily;
  const monthly = summary.budget?.monthly;

  // One percentage per window — whichever wall binds first (message cap or
  // compute allowance). Pro has no message caps, so only the budget applies.
  const percent =
    win === "day"
      ? Math.max(isPro ? 0 : (chatDay?.percentage ?? 0), daily?.percentage ?? 0)
      : isPro
        ? (monthly?.percentage ?? 0)
        : (chatMonth?.percentage ?? 0);
  const resetIso =
    win === "day"
      ? (chatDay?.reset_time ?? daily?.reset_time)
      : isPro
        ? monthly?.reset_time
        : chatMonth?.reset_time;
  const remaining = Math.max(0, Math.round(100 - percent));

  const elapsed = resetIso ? elapsedFraction(resetIso, win) : 0;
  const pace = elapsed * 100;
  const projected = elapsed > 0.05 ? percent / elapsed : percent;
  const willExceed = !!resetIso && percent < 100 && projected >= 100;
  const showPace = !!resetIso && pace > 2 && pace < 98;
  // The gauge shows what's LEFT (fuel-gauge style), so the pace tick marks the
  // remaining allowance you'd have at an even burn rate: 100% - time elapsed.
  const expectedRemaining = 100 - pace;
  // Recharts maps value 0→startAngle(230°), 100→-50°; radii in the 100x100
  // viewBox match innerRadius 70% / outerRadius 100%.
  const theta = ((230 - expectedRemaining * 2.8) * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);

  return (
    <section className={cn(CARD, "relative flex items-center gap-5 p-4")}>
      <Tabs
        size="sm"
        radius="full"
        selectedKey={win}
        onSelectionChange={(k) => setWin(k as Period)}
        className="absolute right-4 top-4"
        classNames={{
          tabList: "bg-zinc-800/80 p-0.5",
          cursor: "bg-zinc-700",
          tab: "h-6 px-3",
          tabContent:
            "text-xs font-medium text-zinc-500 group-data-[selected=true]:text-zinc-100",
        }}
      >
        <Tab key="month" title="Month" />
        <Tab key="day" title="Today" />
      </Tabs>
      <div className="relative size-32 shrink-0">
        <ChartContainer config={{}} className="aspect-square size-32">
          <RadialBarChart
            data={[{ value: remaining }]}
            innerRadius="76%"
            outerRadius="100%"
            startAngle={230}
            endAngle={-50}
          >
            <PolarAngleAxis
              type="number"
              domain={[0, 100]}
              tick={false}
              axisLine={false}
            />
            <RadialBar
              dataKey="value"
              cornerRadius={10}
              background={{ fill: "#27272a" }}
              fill={severityColor(percent)}
            />
          </RadialBarChart>
        </ChartContainer>
        {/* Pace tick: the remaining you'd have at an even burn. Amber if behind it. */}
        {showPace && (
          <svg
            viewBox="0 0 100 100"
            className="pointer-events-none absolute inset-0 h-full w-full"
            aria-hidden="true"
          >
            <title>Usage pace indicator</title>
            <line
              x1={50 + 37 * cos}
              y1={50 - 37 * sin}
              x2={50 + 46 * cos}
              y2={50 - 46 * sin}
              stroke={willExceed ? NEAR : "rgba(255,255,255,0.9)"}
              strokeWidth={2.5}
              strokeLinecap="round"
            />
          </svg>
        )}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-2xl font-semibold leading-none tracking-tight text-white tabular-nums">
            {remaining}%
          </span>
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-zinc-400">
          {win === "day" ? "Usage today" : "Usage this month"}
        </p>
        <p className="mt-1 text-xl font-semibold text-white">
          {win === "day"
            ? "of today's allowance left"
            : "of this month's allowance left"}
        </p>
        <p className="mt-2 text-[13px] text-zinc-500">
          {win === "day"
            ? "Resets at midnight"
            : resetIso
              ? `Resets ${fmtDate(resetIso)}`
              : ""}
        </p>
      </div>
    </section>
  );
}

// --- Daily bars: the day-by-day pattern, colored by how close to the limit -

function DailyTooltip({
  active,
  payload,
  limit,
}: {
  active?: boolean;
  payload?: { payload: { label: string; messages: number } }[];
  limit: number;
}) {
  if (!active || !payload?.length) return null;
  const { label, messages } = payload[0].payload;
  const color = severityColor(
    limit > 0 ? (messages / limit) * 100 : 0,
    HEALTHY,
  );
  return (
    <div className="rounded-lg bg-zinc-800 px-2.5 py-1.5 text-xs shadow-xl">
      <p className="mb-1 text-zinc-400">{label}</p>
      <div className="flex items-center gap-1.5">
        <span
          className="size-2 rounded-[2px]"
          style={{ backgroundColor: color }}
        />
        <span className="font-medium text-zinc-100">
          {messages} {messages === 1 ? "message" : "messages"}
        </span>
      </div>
    </div>
  );
}

function DailyBars({
  history,
  summary,
}: {
  history: UsageHistoryEntry[];
  summary: UsageSummary;
}) {
  const limit = summary.features.chat_messages?.periods.day?.limit ?? 0;
  const data = useMemo(() => {
    if (!history.length) return [];
    const dayKey = (d: Date) =>
      `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
    const used = new Map<string, number>();
    let end = 0;
    for (const e of history) {
      const d = new Date(e.date);
      used.set(dayKey(d), e.features.chat_messages?.periods.day?.used ?? 0);
      end = Math.max(end, d.getTime());
    }
    // Trailing 30 days ending on the latest day we have data for (= today).
    return Array.from({ length: 30 }, (_, i) => {
      const d = new Date(end - (29 - i) * 86_400_000);
      const key = dayKey(d);
      return {
        key,
        label: `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`,
        messages: used.get(key) ?? 0,
      };
    });
  }, [history]);

  const daysHit = data.filter((d) => limit > 0 && d.messages >= limit).length;
  if (data.length < 2) return null;

  return (
    <section className={cn(CARD, "flex min-w-0 flex-1 flex-col p-5")}>
      <div className="mb-4 flex items-baseline justify-between">
        <div className="flex items-center gap-1.5">
          <p className="text-base font-semibold text-white">Day by day</p>
          <InfoTip text="Messages sent each day over the last 30 days. Bars turn amber as you near the daily limit and red on days you hit it." />
        </div>
        {daysHit > 0 && (
          <p className="text-[13px] text-zinc-500">
            Limit hit on{" "}
            <span className="font-medium text-zinc-300">
              {daysHit} {daysHit === 1 ? "day" : "days"}
            </span>
          </p>
        )}
      </div>
      <ChartContainer
        config={{ messages: { label: "Messages", color: HEALTHY } }}
        className="mt-2 aspect-auto min-h-0 w-full flex-1"
      >
        <BarChart
          data={data}
          margin={{ left: 0, right: 0, top: 10, bottom: 0 }}
        >
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tickMargin={12}
            minTickGap={36}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          {limit > 0 && <YAxis hide domain={[0, Math.round(limit * 1.28)]} />}
          {limit > 0 && (
            <ReferenceLine
              y={limit}
              stroke="#3f3f46"
              strokeDasharray="3 3"
              label={{
                value: `${limit} limit`,
                position: "top",
                fill: "#71717a",
                fontSize: 10,
              }}
            />
          )}
          <ChartTooltip
            cursor={{ fill: "#ffffff08" }}
            content={<DailyTooltip limit={limit} />}
          />
          <Bar dataKey="messages" radius={5} maxBarSize={9}>
            {data.map((d) => (
              <Cell
                key={d.key}
                fill={severityColor(
                  limit > 0 ? (d.messages / limit) * 100 : 0,
                  HEALTHY,
                )}
              />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
    </section>
  );
}

// --- Stats row: three small cards ------------------------------------------

function Stats({
  summary,
  history,
}: {
  summary: UsageSummary;
  history: UsageHistoryEntry[];
}) {
  const ceiling = summary.budget?.per_request_token_ceiling;

  // Engagement metrics for the current month, derived from the daily history:
  // average messages per elapsed day, and how many of those days saw any use.
  const { dailyAvg, activeDays, elapsedDays } = useMemo(() => {
    const empty = { dailyAvg: 0, activeDays: 0, elapsedDays: 0 };
    const resetIso = summary.features.chat_messages?.periods.month?.reset_time;
    if (!history.length || !resetIso) return empty;
    const end = new Date(resetIso); // first of next month, UTC
    const curMonth = (end.getUTCMonth() + 11) % 12;
    const curYear =
      curMonth === 11 ? end.getUTCFullYear() - 1 : end.getUTCFullYear();
    const byDom = new Map<number, number>();
    for (const e of history) {
      const d = new Date(e.date);
      if (d.getUTCMonth() !== curMonth || d.getUTCFullYear() !== curYear)
        continue;
      byDom.set(
        d.getUTCDate(),
        e.features.chat_messages?.periods.day?.used ?? 0,
      );
    }
    if (!byDom.size) return empty;
    const elapsedDays = Math.max(...byDom.keys());
    let total = 0;
    let activeDays = 0;
    for (const used of byDom.values()) {
      total += used;
      if (used > 0) activeDays += 1;
    }
    return {
      dailyAvg: Math.round(total / Math.max(1, elapsedDays)),
      activeDays,
      elapsedDays,
    };
  }, [history, summary]);

  return (
    <div className="grid grid-cols-3 gap-3">
      <StatCard
        label="Daily average"
        value={dailyAvg.toLocaleString()}
        sub="messages per day"
      />
      <StatCard
        label="Active days"
        value={`${activeDays}`}
        sub={`of ${elapsedDays} days this month`}
      />
      <StatCard
        label="Max task"
        value={ceiling ? fmtCompact(ceiling) : "—"}
        sub="tokens / run"
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  percent,
}: {
  label: string;
  value: string;
  sub: string;
  percent?: number;
}) {
  return (
    <div className={cn(CARD, "flex flex-col p-4")}>
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-white tabular-nums">
        {value}
      </p>
      <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>
      {percent !== undefined && (
        <Meter percent={percent} className="mt-3 h-1" />
      )}
    </div>
  );
}

// --- Meter: the house usage bar (flat, single accent, no border) -----------

function Meter({
  percent,
  className,
  pace,
  paceWarn,
}: {
  percent: number;
  className?: string;
  /** 0-100 tick marking where usage "should" be by now (time elapsed). */
  pace?: number;
  /** Amber tick when usage is running ahead of that pace. */
  paceWarn?: boolean;
}) {
  const pct = Math.min(100, Math.max(0, percent));
  return (
    <div
      className={cn(
        "relative w-full overflow-hidden rounded-full bg-zinc-800",
        className,
      )}
    >
      <div
        className="h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${pct}%`, backgroundColor: severityColor(percent) }}
      />
      {pace !== undefined && pace > 1 && pace < 99 && (
        <div
          className="absolute top-0 h-full w-0.5 -translate-x-1/2"
          style={{
            left: `${pace}%`,
            backgroundColor: paceWarn ? NEAR : "rgba(255,255,255,0.65)",
          }}
        />
      )}
    </div>
  );
}

// --- Trend: calm 30-day bar chart (flat, breaks the card rhythm) -----------

interface MonthWindow {
  curMonth: number;
  curYear: number;
  daysInMonth: number;
  name: string;
}

/** Resolve the month a reset timestamp closes (reset = first of NEXT month). */
function currentMonthWindow(resetIso: string): MonthWindow {
  const end = new Date(resetIso);
  const curMonth = (end.getUTCMonth() + 11) % 12;
  const curYear =
    curMonth === 11 ? end.getUTCFullYear() - 1 : end.getUTCFullYear();
  const daysInMonth = new Date(
    Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 0),
  ).getUTCDate();
  return { curMonth, curYear, daysInMonth, name: MONTHS[curMonth] };
}

/** Latest cumulative month counter per calendar day. Snapshots are HOURLY, so
 * summing per-entry values would overcount an active day by up to 24x —
 * ascending order means the last entry per day is the day's final count. */
function cumulativeByDay(
  history: UsageHistoryEntry[],
  window: MonthWindow,
): Map<number, number> {
  const byDom = new Map<number, number>();
  for (const e of history) {
    const d = new Date(e.date);
    if (
      d.getUTCMonth() !== window.curMonth ||
      d.getUTCFullYear() !== window.curYear
    )
      continue;
    const used = e.features.chat_messages?.periods.month?.used;
    if (used !== undefined) byDom.set(d.getUTCDate(), used);
  }
  return byDom;
}

/** Chart rows + projection. Simple average pace (total / days elapsed); the
 * projection CONTINUES from today's cumulative — never restarts from zero. */
function buildTrendSeries(
  byDom: Map<number, number>,
  daysInMonth: number,
  limit: number,
  asPct: boolean,
) {
  const toValue = (used: number) =>
    asPct ? Math.round((used / limit) * 1000) / 10 : used;
  const rows: AreaPoint[] = [...byDom.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([dom, used]) => ({ dom, actual: toValue(used), projected: null }));
  const cap = asPct ? 100 : limit;
  const cum = rows[rows.length - 1].actual ?? 0;
  const lastDom = rows[rows.length - 1].dom;
  const perDay = cum / Math.max(1, lastDom);
  rows[rows.length - 1].projected = cum; // bridge the two series visually
  let runOutDom: number | null = null;
  for (let dom = lastDom + 1; dom <= daysInMonth; dom++) {
    const proj = Math.round((cum + perDay * (dom - lastDom)) * 10) / 10;
    rows.push({ dom, actual: null, projected: proj });
    if (runOutDom === null && limit > 0 && proj >= cap) runOutDom = dom;
  }
  // Only anchor the y-scale to the cap when it's actually in reach this month
  // (free). For plans with a far-off cap (pro), scale to the data so the curve
  // isn't a flat line pinned to the bottom.
  const projectedEnd = cum + perDay * (daysInMonth - lastDom);
  const showLimit = limit > 0 && projectedEnd >= cap * 0.5;
  const yMax = showLimit
    ? Math.round(cap * 1.18)
    : Math.max(10, Math.round(Math.max(cum, projectedEnd) * 1.12));
  return {
    rows,
    runOutDom,
    daysLeft: runOutDom === null ? 0 : runOutDom - lastDom,
    showLimit,
    yMax,
  };
}

function TrendTooltip({
  active,
  payload,
  label,
  monthName,
  asPct,
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number | null }[];
  label?: number;
  monthName: string;
  asPct: boolean;
}) {
  if (!active || !payload?.length) return null;
  const actual = payload.find((p) => p.dataKey === "actual" && p.value != null);
  const projected = payload.find(
    (p) => p.dataKey === "projected" && p.value != null,
  );
  // The last actual point carries a duplicate `projected` value purely to keep
  // the dashed line visually continuous — never show both for one day.
  const row = actual
    ? { name: asPct ? "Used" : "Sent", color: HEALTHY, value: actual.value }
    : projected
      ? { name: "Projected", color: NEAR, value: projected.value }
      : null;
  if (!row) return null;
  const formatted = asPct
    ? `${Number(row.value).toLocaleString()}%`
    : Number(row.value).toLocaleString();
  return (
    <div className="rounded-lg bg-zinc-800 px-2.5 py-1.5 text-xs shadow-xl">
      <p className="mb-1 text-zinc-400">
        {monthName} {label}
      </p>
      <div className="flex items-center gap-1.5">
        <span
          className="size-2 rounded-[2px]"
          style={{ backgroundColor: row.color }}
        />
        <span className="text-zinc-400">{row.name}</span>
        <span className="pl-2 font-medium text-zinc-100 tabular-nums">
          {formatted}
        </span>
      </div>
    </div>
  );
}

interface AreaPoint {
  dom: number;
  actual: number | null;
  projected: number | null;
}

function Trend({
  history,
  summary,
}: {
  history: UsageHistoryEntry[];
  summary: UsageSummary;
}) {
  const month = summary.features.chat_messages?.periods.month;
  const limit = month?.limit ?? 0;
  const resetIso = month?.reset_time;
  // Free plots percent-of-allowance (no raw counts anywhere on free); pro plots
  // real message counts since its monthly cap is an abuse backstop, not a budget.
  const asPct = summary.plan_type !== "pro" && limit > 0;

  const { rows, monthName, runOutDom, daysLeft, showLimit, yMax } =
    useMemo(() => {
      const empty = {
        rows: [] as AreaPoint[],
        monthName: "",
        runOutDom: null as number | null,
        daysLeft: 0,
        showLimit: false,
        yMax: 10,
      };
      if (history.length < 2 || !resetIso) return empty;
      const window = currentMonthWindow(resetIso);
      const byDom = cumulativeByDay(history, window);
      if (byDom.size < 2) return { ...empty, monthName: window.name };
      return {
        ...buildTrendSeries(byDom, window.daysInMonth, limit, asPct),
        monthName: window.name,
      };
    }, [history, resetIso, limit, asPct]);

  if (!rows.length) return null;

  return (
    <section className={cn(CARD, "p-5")}>
      <div className="mb-4 flex items-baseline justify-between">
        <div className="flex items-center gap-1.5">
          <p className="text-base font-semibold text-white">
            Messages this month
          </p>
          <InfoTip
            text={`Your cumulative messages this month${asPct ? ", as a share of your monthly allowance" : ""}. The dashed line projects where you'll land at your current pace.`}
          />
        </div>
        {runOutDom && (
          <p className="text-[13px] font-medium text-amber-400">
            On track to run out {monthName} {runOutDom} ({daysLeft}{" "}
            {daysLeft === 1 ? "day" : "days"} left)
          </p>
        )}
      </div>
      <ChartContainer
        config={{ actual: { label: asPct ? "Used" : "Sent", color: HEALTHY } }}
        className="aspect-[16/6] w-full"
      >
        <AreaChart
          data={rows}
          margin={{ left: 0, right: 0, top: 12, bottom: 0 }}
        >
          <defs>
            <linearGradient id="trajFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={HEALTHY} stopOpacity={0.25} />
              <stop offset="100%" stopColor={HEALTHY} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="dom"
            tickLine={false}
            axisLine={false}
            tickMargin={12}
            minTickGap={40}
            tickFormatter={(d) => `${monthName} ${d}`}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis hide domain={[0, yMax]} />
          {showLimit && (
            <ReferenceLine
              y={asPct ? 100 : limit}
              stroke="#52525b"
              strokeDasharray="4 4"
              label={{
                value: asPct ? "100%" : `${limit.toLocaleString()} limit`,
                position: "insideTopRight",
                fill: "#a1a1aa",
                fontSize: 10,
              }}
            />
          )}
          <ChartTooltip
            content={<TrendTooltip monthName={monthName} asPct={asPct} />}
          />
          <Area
            dataKey="actual"
            type="monotone"
            stroke={HEALTHY}
            strokeWidth={2}
            fill="url(#trajFill)"
            connectNulls
            dot={false}
          />
          <Area
            dataKey="projected"
            type="monotone"
            stroke={NEAR}
            strokeWidth={2}
            strokeDasharray="4 4"
            fill="none"
            connectNulls
            dot={false}
          />
        </AreaChart>
      </ChartContainer>
    </section>
  );
}

// --- Tools: comprehensive, sorted by what you've actually used -------------

function Tools({
  summary,
  period,
  onPeriod,
}: {
  summary: UsageSummary;
  period: Period;
  onPeriod: (p: Period) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const rows = useMemo(() => {
    // Order by the WORST severity across both periods (title tiebreak) so the
    // list keeps a stable order when toggling Today/Month — only bars change.
    const severity = (f: FeatureUsage) =>
      Math.max(
        f.periods.day?.percentage ?? 0,
        f.periods.month?.percentage ?? 0,
      );
    return Object.entries(summary.features)
      .filter(([key]) => key !== "chat_messages")
      .map(([key, f]) => ({ key, f, p: f.periods[period] }))
      .filter(
        (r): r is { key: string; f: FeatureUsage; p: PeriodData } =>
          !!r.p && r.p.limit > 0,
      )
      .sort(
        (a, b) =>
          severity(b.f) - severity(a.f) || a.f.title.localeCompare(b.f.title),
      );
  }, [summary.features, period]);

  const COLLAPSED = 8;
  const canCollapse = rows.length > COLLAPSED;
  const visible = showAll || !canCollapse ? rows : rows.slice(0, COLLAPSED);

  return (
    <section className={cn(CARD, "relative overflow-hidden p-5")}>
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-base font-semibold text-white">Tools</h3>
        <Tabs
          size="sm"
          radius="full"
          selectedKey={period}
          onSelectionChange={(k) => onPeriod(k as Period)}
          classNames={{
            tabList: "bg-zinc-800/80 p-0.5",
            cursor: "bg-zinc-700",
            tab: "h-6 px-3",
            tabContent:
              "text-xs font-medium text-zinc-500 group-data-[selected=true]:text-zinc-100",
          }}
        >
          <Tab key="day" title="Today" />
          <Tab key="month" title="Month" />
        </Tabs>
      </div>
      {rows.length === 0 ? (
        <p className="py-6 text-sm text-zinc-600">No tool usage yet.</p>
      ) : (
        <>
          <div className="flex flex-col divide-y divide-zinc-800/70">
            {visible.map((r) => (
              <FeatureRow
                key={r.key}
                feature={r.f}
                p={r.p}
                proLimit={
                  summary.plan_type !== "pro"
                    ? r.f.upgrade?.[period]
                    : undefined
                }
              />
            ))}
          </div>
          {canCollapse && showAll && (
            <div className="mt-3 flex justify-center">
              <Chip
                as="button"
                variant="solid"
                size="sm"
                className="cursor-pointer"
                onClick={() => setShowAll(false)}
              >
                Show less
              </Chip>
            </div>
          )}
          {canCollapse && !showAll && (
            <>
              <BlurStack className="pointer-events-none absolute inset-x-0 bottom-0 h-24" />
              <div className="absolute inset-x-0 bottom-3 z-20 flex justify-center">
                <Chip
                  as="button"
                  variant="flat"
                  size="sm"
                  className="cursor-pointer"
                  onClick={() => setShowAll(true)}
                >
                  Show more
                </Chip>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

function FeatureRow({
  feature,
  p,
  proLimit,
}: {
  feature: FeatureUsage;
  p: PeriodData;
  /** Pro's limit for this period — shown as the upgrade delta on free plans. */
  proLimit?: number;
}) {
  const showPro = proLimit !== undefined && proLimit > p.limit;
  return (
    <div className="flex items-center gap-4 py-3">
      <Tooltip
        content={feature.description}
        placement="top"
        delay={250}
        closeDelay={0}
        classNames={{
          content: "max-w-56 bg-zinc-800 text-xs text-zinc-300 shadow-xl",
        }}
      >
        <span className="w-36 shrink-0 cursor-default truncate text-sm font-medium text-zinc-200">
          {feature.title}
        </span>
      </Tooltip>
      <Meter percent={p.percentage} className="h-1.5 flex-1" />
      <span className="min-w-16 shrink-0 text-right text-xs tabular-nums text-zinc-500">
        {p.used.toLocaleString()}/{p.limit.toLocaleString()}
        {showPro && (
          <span className="text-zinc-600">
            {" "}
            · {fmtCompact(proLimit)} on Pro
          </span>
        )}
      </span>
    </div>
  );
}

// --- Upgrade banner (free only, pinned to the top) -------------------------

/** Personalized upsell line from real usage: name the friction if there is any,
 * otherwise stay aspirational. Never guilt-trips a light user. */
function upgradeReason(
  summary: UsageSummary,
  history: UsageHistoryEntry[],
): string {
  const daysHit = history.filter((e) => {
    const d = e.features.chat_messages?.periods.day;
    return !!d && d.limit > 0 && d.used >= d.limit;
  }).length;
  if (daysHit > 0) {
    return `You hit a daily limit ${daysHit} ${daysHit === 1 ? "day" : "days"} recently — Pro removes them.`;
  }
  const near = Object.values(summary.features).filter((f) => {
    const p = f.periods.day;
    return !!p && p.limit > 0 && p.used > 0 && p.percentage >= 80;
  }).length;
  if (near > 0) {
    return `You're close to your limit on ${near} ${near === 1 ? "tool" : "tools"} — Pro gives you far more room.`;
  }
  return "10x higher limits on every tool, and room for much larger tasks.";
}

function UpgradeBanner({
  reason,
  onUpgrade,
}: {
  reason: string;
  onUpgrade: () => void;
}) {
  return (
    <div className={cn(CARD, "flex items-center gap-3.5 px-4 py-3.5")}>
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10">
        <SparklesIcon className="text-primary" size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-white">Upgrade to Pro</p>
        <p className="truncate text-[13px] text-zinc-500">{reason}</p>
      </div>
      <Button
        color="primary"
        size="sm"
        className="shrink-0 font-medium"
        onPress={onUpgrade}
      >
        Upgrade
      </Button>
    </div>
  );
}
