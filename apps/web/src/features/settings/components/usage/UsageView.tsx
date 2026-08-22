"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { Fire02Icon, SparklesIcon } from "@icons";
import { USAGE_WARN_THRESHOLD } from "@shared/constants/usage";
import type { FeatureUsage, UsageActivity, UsageSummary } from "@shared/types";
import { formatCompactNumber, formatDate, formatDateUTC } from "@shared/utils";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
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
import { DayByDay } from "./DayByDay";
import { ActivityBadge, UsageHeatmap } from "./UsageHeatmap";
import { CARD, HEALTHY, InfoTip, NEAR, severityColor } from "./usageChrome";

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

/** Local wall-clock time of an instant, e.g. "5:30 AM" — "midnight" would be
 * a lie for every user outside UTC. */
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
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
  const primary = summary.primary_feature;
  const [period, setPeriod] = useState<Period>("day");

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 pb-4">
      {!isPro && (
        <UpgradeBanner reason={upgradeReason(summary)} onUpgrade={onUpgrade} />
      )}
      <Hero summary={summary} isPro={isPro} />
      <Stats
        summary={summary}
        history={history}
        primary={primary}
        streak={activity?.streak}
      />
      <Trend history={history} summary={summary} primary={primary} />
      <div className="flex items-stretch gap-4">
        {activity && <DayByDay activity={activity} />}
        {activity && <ActivityBadge tier={activity.tier} activity={activity} />}
      </div>
      {activity && <UsageHeatmap activity={activity} />}
      <Tools
        summary={summary}
        primary={primary}
        period={period}
        onPeriod={setPeriod}
      />
    </div>
  );
}

// --- Hero: the one big number + the one big bar ----------------------------

// One percentage per window, driven entirely by the rolling cost budget — the
// single wall every plan is measured against now that chat is priced by usage,
// not message counts. Free has only a daily budget (its wall); pro adds a
// monthly compute allowance, so only pro shows the month window.
function heroWindow(
  summary: UsageSummary,
  win: Period,
): { percent: number; resetIso: string | undefined } {
  const window =
    win === "day" ? summary.budget?.daily : summary.budget?.monthly;
  return {
    percent: window?.percentage ?? 0,
    resetIso: window?.reset_time,
  };
}

function Hero({ summary, isPro }: { summary: UsageSummary; isPro: boolean }) {
  // Free has no monthly allowance to show, so its hero is daily-only.
  const [win, setWin] = useState<Period>(isPro ? "month" : "day");
  const { percent, resetIso } = heroWindow(summary, win);
  const used = Math.min(100, Math.round(percent));

  const elapsed = resetIso ? elapsedFraction(resetIso, win) : 0;
  const pace = elapsed * 100;
  const projected = elapsed > 0.05 ? percent / elapsed : percent;
  const willExceed = !!resetIso && percent < 100 && projected >= 100;
  const showPace = !!resetIso && pace > 2 && pace < 98;
  // The gauge shows what's USED, so the pace tick marks where usage "should"
  // be at an even burn rate: the share of the window already elapsed.
  // Recharts maps value 0→startAngle(230°), 100→-50°; radii in the 100x100
  // viewBox match innerRadius 70% / outerRadius 100%.
  const theta = ((230 - pace * 2.8) * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);

  return (
    <section className={cn(CARD, "relative flex items-center gap-5 p-4")}>
      {isPro && (
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
      )}
      <div className="relative size-32 shrink-0">
        <ChartContainer config={{}} className="aspect-square size-32">
          <RadialBarChart
            data={[{ value: used }]}
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
        {/* Pace tick: where usage "should" be at an even burn. Amber if ahead of it. */}
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
            {used}%
          </span>
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="text-sm font-medium text-zinc-400">
            {win === "day" ? "Today" : "This month"}
          </p>
          <InfoTip text="How much of your usage allowance you've used this window, based on the AI compute your activity has consumed." />
        </div>
        <p className="mt-1 text-xl font-semibold text-white">
          {win === "day"
            ? "of your daily allowance used"
            : "of your monthly allowance used"}
        </p>
        <p className="mt-2 text-[13px] text-zinc-500">
          {win === "day"
            ? resetIso
              ? `Resets at ${fmtTime(resetIso)}`
              : ""
            : resetIso
              ? `Resets ${formatDate(resetIso, "short")}`
              : ""}
        </p>
      </div>
    </section>
  );
}

// --- Stats row: three small cards ------------------------------------------

function Stats({
  summary,
  history,
  primary,
  streak = 0,
}: {
  summary: UsageSummary;
  history: UsageHistoryEntry[];
  /** The feature key whose activity drives the engagement metrics. */
  primary: string;
  /** Current consecutive-active-days streak (from the activity rollup). */
  streak?: number;
}) {
  const ceiling = summary.budget?.per_request_token_ceiling;

  // Engagement metrics for the current month, derived from the daily history.
  // Chat is cost-priced (no daily count allowance), so this averages plain
  // message activity per day rather than a share of any count limit.
  const { dailyAvg, activeDays, elapsedDays } = useMemo(() => {
    // Days elapsed this month (today included) is a calendar fact — it is never
    // zero, and it is the denominator BOTH metrics are reported against. Compute
    // it before any early return, or a user with no history yet reads
    // "0 of 0 days this month" on their first visit. Only the derived counts
    // may collapse to zero.
    const elapsedDays = new Date().getUTCDate();
    const empty = { dailyAvg: 0, activeDays: 0, elapsedDays };
    const resetIso = summary.features[primary]?.periods.month?.reset_time;
    if (!history.length || !resetIso) return empty;
    const window = currentMonthWindow(resetIso);
    const byDom = new Map<number, number>();
    for (const e of history) {
      const d = new Date(e.date);
      if (!isInWindow(d, window)) continue;
      // Only set when the snapshot actually carries a day period — an entry
      // without one must not clobber a real earlier value with 0.
      const day = e.features[primary]?.periods.day;
      if (day?.used !== undefined) byDom.set(d.getUTCDate(), day.used);
    }
    if (!byDom.size) return empty;
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
  }, [history, summary, primary]);

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
        accent={
          streak > 0 ? (
            <Tooltip
              content={`${streak}-day streak — you've been active every day for the last ${streak} days`}
              placement="top"
              delay={150}
              closeDelay={0}
              classNames={{
                content: "max-w-64 bg-zinc-800 text-xs text-zinc-300 shadow-xl",
              }}
            >
              <span className="flex cursor-default items-center gap-0.5 text-xs font-medium text-orange-400">
                <Fire02Icon size={13} />
                {streak}
              </span>
            </Tooltip>
          ) : undefined
        }
      />
      <StatCard
        label="Max task"
        value={ceiling ? formatCompactNumber(ceiling) : "—"}
        sub="tokens / run"
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  /** Small highlight rendered at the label row's right edge (e.g. streak). */
  accent?: React.ReactNode;
}) {
  return (
    <div className={cn(CARD, "flex flex-col p-4")}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-500">{label}</p>
        {accent}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-white tabular-nums">
        {value}
      </p>
      <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>
    </div>
  );
}

// --- Meter: the house usage bar (flat, single accent, no border) -----------

function Meter({
  percent,
  className,
}: {
  percent: number;
  className?: string;
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
  return {
    curMonth,
    curYear,
    daysInMonth,
    name: formatDateUTC(new Date(Date.UTC(curYear, curMonth, 1)), "month"),
  };
}

/** True when a snapshot instant falls inside the resolved month window. */
function isInWindow(date: Date, window: MonthWindow): boolean {
  return (
    date.getUTCMonth() === window.curMonth &&
    date.getUTCFullYear() === window.curYear
  );
}

/** Latest cumulative month counter per calendar day. Snapshots are HOURLY, so
 * summing per-entry values would overcount an active day by up to 24x —
 * ascending order means the last entry per day is the day's final count. */
function cumulativeByDay(
  history: UsageHistoryEntry[],
  window: MonthWindow,
  primary: string,
): Map<number, number> {
  const byDom = new Map<number, number>();
  for (const e of history) {
    const d = new Date(e.date);
    if (!isInWindow(d, window)) continue;
    const used = e.features[primary]?.periods.month?.used;
    if (used !== undefined) byDom.set(d.getUTCDate(), used);
  }
  return byDom;
}

/** Chart rows + projection. Simple average pace (total / days elapsed); the
 * projection CONTINUES from today's cumulative — never restarts from zero.
 * Plots raw message counts: chat has no meaningful monthly count cap (free's
 * is a large abuse backstop, pro has none), so a "% of allowance" trend would
 * be meaningless. The run-out projection stays inert unless a real, reachable
 * cap is passed. */
function buildTrendSeries(
  byDom: Map<number, number>,
  daysInMonth: number,
  limit: number,
) {
  const rows: AreaPoint[] = [...byDom.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([dom, used]) => ({ dom, actual: used, projected: null }));
  const cap = limit;
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
}: {
  active?: boolean;
  payload?: { dataKey?: string | number; value?: number | null }[];
  label?: number;
  monthName: string;
}) {
  if (!active || !payload?.length) return null;
  const actual = payload.find((p) => p.dataKey === "actual" && p.value != null);
  const projected = payload.find(
    (p) => p.dataKey === "projected" && p.value != null,
  );
  // The last actual point carries a duplicate `projected` value purely to keep
  // the dashed line visually continuous — never show both for one day.
  const row = actual
    ? { name: "Sent", color: HEALTHY, value: actual.value }
    : projected
      ? { name: "Projected", color: NEAR, value: projected.value }
      : null;
  if (!row) return null;
  const formatted = Number(row.value).toLocaleString();
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
  primary,
}: {
  history: UsageHistoryEntry[];
  summary: UsageSummary;
  /** The feature key whose cumulative monthly activity is plotted. */
  primary: string;
}) {
  const month = summary.features[primary]?.periods.month;
  const limit = month?.limit ?? 0;
  const resetIso = month?.reset_time;
  const liveMonthUsed = month?.used;

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
      if (!resetIso) return empty;
      const window = currentMonthWindow(resetIso);
      const byDom = cumulativeByDay(history, window, primary);
      // Today's point comes from the LIVE month counter — the same number the
      // hero gauge shows — so the two widgets can never disagree about "now"
      // (snapshots lag up to an hour behind the live Redis counter). The
      // cumulative series must never DECREASE: if the live counter reads lower
      // than history (counter eviction/reset), keep the historical maximum
      // instead of drawing an impossible cliff.
      if (liveMonthUsed !== undefined) {
        const historicalMax = Math.max(0, ...byDom.values());
        byDom.set(
          new Date().getUTCDate(),
          Math.max(liveMonthUsed, historicalMax),
        );
      }
      // One point is enough: an inactive-this-month user gets an honest flat
      // line at their live counter (usually 0) instead of a missing section.
      if (byDom.size < 1) return { ...empty, monthName: window.name };
      return {
        ...buildTrendSeries(byDom, window.daysInMonth, limit),
        monthName: window.name,
      };
    }, [history, resetIso, limit, primary, liveMonthUsed]);

  if (!rows.length) return null;

  // A month with zero usage has nothing to plot and nothing to project —
  // "at this pace you'll land at 0" is noise. Keep the card (a vanishing
  // section reads as a bug) with a quiet empty state instead.
  const isEmpty = rows.every((r) => !r.actual && !r.projected);

  return (
    <section className={cn(CARD, "p-5")}>
      <div className="mb-4 flex items-baseline justify-between">
        <div className="flex items-center gap-1.5">
          <p className="text-base font-semibold text-white">Usage this month</p>
          <InfoTip text="Your cumulative messages sent this month. The dashed line projects where you'll land at your current pace." />
        </div>
        {runOutDom && (
          <p className="text-[13px] font-medium text-amber-400">
            On track to run out {monthName} {runOutDom} ({daysLeft}{" "}
            {daysLeft === 1 ? "day" : "days"} left)
          </p>
        )}
      </div>
      {isEmpty && (
        <div className="flex aspect-[16/6] w-full items-center justify-center text-sm text-zinc-600">
          Nothing used yet this {monthName} — your trend will appear here.
        </div>
      )}
      {!isEmpty && (
        <ChartContainer
          config={{ actual: { label: "Sent", color: HEALTHY } }}
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
                y={limit}
                stroke="#52525b"
                strokeDasharray="4 4"
                label={{
                  value: `${limit.toLocaleString()} limit`,
                  position: "insideTopRight",
                  fill: "#a1a1aa",
                  fontSize: 10,
                }}
              />
            )}
            <ChartTooltip content={<TrendTooltip monthName={monthName} />} />
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
      )}
    </section>
  );
}

// --- Tools: comprehensive, sorted by what you've actually used -------------

function Tools({
  summary,
  primary,
  period,
  onPeriod,
}: {
  summary: UsageSummary;
  /** The primary feature key, excluded here — it leads the hero, not this list. */
  primary: string;
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
      .filter(([key]) => key !== primary)
      .map(([key, f]) => ({ key, f, p: f.periods[period] }))
      .filter(
        (r): r is { key: string; f: FeatureUsage; p: PeriodData } =>
          !!r.p && r.p.limit > 0,
      )
      .sort(
        (a, b) =>
          severity(b.f) - severity(a.f) || a.f.title.localeCompare(b.f.title),
      );
  }, [summary.features, primary, period]);

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
        {/* Over-limit is legitimate (plan change, automated triggers) — mark it
            instead of letting "29/20" read like a rendering bug. */}
        <span className={p.used > p.limit ? "text-[#ff453a]" : undefined}>
          {p.used.toLocaleString()}
        </span>
        /{p.limit.toLocaleString()}
        {showPro && (
          <span className="text-zinc-600">
            {" "}
            · {formatCompactNumber(proLimit)} on Pro
          </span>
        )}
      </span>
    </div>
  );
}

// --- Upgrade banner (free only, pinned to the top) -------------------------

/** Personalized upsell line from real usage: name the friction if there is any,
 * otherwise stay aspirational. Never guilt-trips a light user. */
function upgradeReason(summary: UsageSummary): string {
  // Free's real daily wall is the rolling cost budget, not a message count, so
  // its friction lives in the live budget percentage — history carries message
  // counts, not cost, so there's no per-day budget-hit series to tally.
  const budgetPct = summary.budget?.daily?.percentage ?? 0;
  if (budgetPct >= USAGE_WARN_THRESHOLD) {
    return "You're near today's usage limit — Pro gives you much higher daily limits.";
  }
  const near = Object.values(summary.features).filter((f) => {
    const p = f.periods.day;
    return (
      !!p && p.limit > 0 && p.used > 0 && p.percentage >= USAGE_WARN_THRESHOLD
    );
  }).length;
  if (near > 0) {
    return `You're close to your limit on ${near} ${near === 1 ? "tool" : "tools"} — Pro gives you far more room.`;
  }
  return "Unlimited chat messages, much higher limits on every feature, and room for far larger tasks.";
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
