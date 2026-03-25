import {
  BarChart as RechartsBarChart,
  Bar,
  LineChart as RechartsLineChart,
  Line,
  AreaChart as RechartsAreaChart,
  Area,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  ScatterChart as RechartsScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  RadarChart as RechartsRadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  RadialBarChart,
  RadialBar,
} from "recharts";
import {
  Chip,
  Button,
  Progress,
  Accordion as HeroAccordion,
  AccordionItem,
  Tabs,
  Tab,
  RadioGroup,
  Radio,
  Avatar,
  User,
  Kbd,
} from "@heroui/react";
import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import AnimatedNumber from "animated-number-react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/dist/style.css";
import { motion, AnimatePresence } from "motion/react";

// ---------------------------------------------------------------------------
// Chart color palette
// ---------------------------------------------------------------------------
const CHART_COLORS = ["#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const dataCardSchema = z.object({
  title: z.string(),
  fields: z.array(z.object({ label: z.string(), value: z.string() })),
});

const resultListSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      title: z.string(),
      subtitle: z.string().optional(),
      body: z.string().optional(),
      url: z.string().optional(),
      badge: z.string().optional(),
    }),
  ),
});

const dataTableSchema = z.object({
  title: z.string().optional(),
  columns: z.array(z.string()),
  rows: z.array(z.array(z.string())),
});

const comparisonTableSchema = z.object({
  title: z.string().optional(),
  leftLabel: z.string(),
  rightLabel: z.string(),
  rows: z.array(
    z.object({
      label: z.string(),
      left: z.string(),
      right: z.string(),
      highlight: z.boolean().optional(),
    }),
  ),
});

const statusCardSchema = z.object({
  title: z.string(),
  status: z.enum(["success", "error", "warning", "info", "pending"]),
  message: z.string().optional(),
  detail: z.string().optional(),
});

const actionCardSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  actions: z
    .array(
      z.object({
        label: z.string(),
        type: z.literal("continue_conversation"),
        value: z.string(),
      }),
    )
    .optional(),
});

const tagGroupSchema = z.object({
  title: z.string().optional(),
  tags: z.array(
    z.object({
      label: z.string(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
});

const fileTreeSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir"]),
      size: z.string().optional(),
    }),
  ),
});

const accordionSchema = z.object({
  title: z.string().optional(),
  items: z.array(z.object({ label: z.string(), content: z.string() })),
});

const tabsBlockSchema = z.object({
  tabs: z.array(z.object({ label: z.string(), content: z.string() })),
});

const progressListSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      label: z.string(),
      value: z.number(),
      max: z.number().optional(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
});

const statRowSchema = z.object({
  stats: z.array(
    z.object({
      label: z.string(),
      value: z.string(),
      description: z.string().optional(),
    }),
  ),
});

const selectableListSchema = z.object({
  title: z.string().optional(),
  description: z.string().optional(),
  options: z.array(
    z.object({
      label: z.string(),
      description: z.string().optional(),
      value: z.string(),
      badge: z.string().optional(),
    }),
  ),
});

const avatarListSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      name: z.string(),
      role: z.string().optional(),
      description: z.string().optional(),
      initials: z.string().optional(),
      color: z.string().optional(),
    }),
  ),
});

const kbdBlockSchema = z.object({
  title: z.string().optional(),
  shortcuts: z.array(
    z.object({ keys: z.array(z.string()), description: z.string() }),
  ),
});

// Analytics schemas
const metricCardSchema = z.object({
  title: z.string(),
  value: z.union([z.string(), z.number()]),
  unit: z.string().optional(),
  trend: z.enum(["up", "down", "neutral"]).optional(),
  trendLabel: z.string().optional(),
});

const chartDataSchema = z.array(
  z.record(z.string(), z.union([z.string(), z.number()])),
);

const barChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  xKey: z.string(),
  yKey: z.string(),
  color: z.string().optional(),
});

const lineChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.array(z.string()),
  colors: z.array(z.string()).optional(),
});

const areaChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.array(z.string()),
  colors: z.array(z.string()).optional(),
});

const pieChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  nameKey: z.string(),
  valueKey: z.string(),
});

const scatterChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  xKey: z.string(),
  yKey: z.string(),
  labelKey: z.string().optional(),
});

const radarChartSchema = z.object({
  title: z.string().optional(),
  data: chartDataSchema,
  angleKey: z.string(),
  valueKeys: z.array(z.string()),
  colors: z.array(z.string()).optional(),
});

const gaugeChartSchema = z.object({
  title: z.string().optional(),
  value: z.number(),
  min: z.number().optional(),
  max: z.number().optional(),
  unit: z.string().optional(),
  thresholds: z
    .object({ warning: z.number(), danger: z.number() })
    .optional(),
});

// Content schemas
const imageBlockSchema = z.object({
  src: z.string(),
  alt: z.string().optional(),
  caption: z.string().optional(),
});

const imageGallerySchema = z.object({
  images: z.array(
    z.object({
      src: z.string(),
      alt: z.string().optional(),
      caption: z.string().optional(),
    }),
  ),
});

const videoBlockSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  poster: z.string().optional(),
});

const audioPlayerSchema = z.object({
  src: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
});

const diffBlockSchema = z.object({
  title: z.string().optional(),
  hunks: z.array(
    z.object({
      header: z.string(),
      lines: z.array(
        z.object({
          type: z.enum(["add", "remove", "context"]),
          content: z.string(),
        }),
      ),
    }),
  ),
});

const mapBlockSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  zoom: z.number().optional(),
});

const calendarMiniSchema = z.object({
  title: z.string().optional(),
  markedDates: z.array(
    z.object({
      date: z.string(),
      label: z.string().optional(),
      color: z
        .enum(["success", "warning", "danger", "default"])
        .optional(),
    }),
  ),
  mode: z.enum(["single", "range"]).optional(),
});

const numberTickerSchema = z.object({
  value: z.number(),
  label: z.string().optional(),
  unit: z.string().optional(),
  duration: z.number().optional(),
});

const carouselSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      body: z.string().optional(),
      image: z.string().optional(),
      badge: z.string().optional(),
      actions: z
        .array(z.object({ label: z.string(), value: z.string() }))
        .optional(),
    }),
  ),
  autoPlay: z.boolean().optional(),
});

const treeViewSchema = z.object({
  title: z.string().optional(),
  nodes: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      description: z.string().optional(),
      children: z.array(z.unknown()).optional(),
    }),
  ),
});

// Timeline & Notifications schemas
const timelineSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      time: z.string(),
      title: z.string(),
      description: z.string().optional(),
      status: z
        .enum(["success", "error", "warning", "neutral"])
        .optional(),
    }),
  ),
});

const jsonViewerSchema = z.object({
  title: z.string().optional(),
  data: z.string(),
});

const alertBannerSchema = z.object({
  variant: z.enum(["info", "success", "warning", "error"]),
  title: z.string(),
  description: z.string().optional(),
});

const stepsSchema = z.object({
  title: z.string().optional(),
  items: z.array(
    z.object({
      title: z.string(),
      description: z.string().optional(),
      status: z.enum(["complete", "active", "pending"]).optional(),
    }),
  ),
});

// ---------------------------------------------------------------------------
// Component Implementations
// ---------------------------------------------------------------------------

// ---- Layout & Data ----

export function DataCardView(props: z.infer<typeof dataCardSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      <div className="space-y-2">
        {props.fields.map((field, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-2">
            <span className="text-xs text-zinc-400">{field.label}</span>
            <span className="text-sm font-medium text-zinc-200">{field.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ResultListView(props: z.infer<typeof resultListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">{item.title}</span>
              {item.badge && (
                <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400 shrink-0">
                  {item.badge}
                </span>
              )}
            </div>
            {item.subtitle && (
              <p className="text-xs text-zinc-400 mt-1">{item.subtitle}</p>
            )}
            {item.body && (
              <p className="text-xs text-zinc-400 mt-1">{item.body}</p>
            )}
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 mt-1 block truncate hover:underline"
              >
                {item.url}
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function DataTableView(props: z.infer<typeof dataTableSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="overflow-auto rounded-2xl bg-zinc-900">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {props.columns.map((col, i) => (
                <th
                  key={i}
                  className="px-3 py-2 text-left text-xs font-semibold text-zinc-400"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, ri) => (
              <tr key={ri} className="hover:bg-zinc-800/50 transition-colors">
                {row.map((cell, ci) => (
                  <td key={ci} className="px-3 py-2 text-xs text-zinc-300">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ComparisonTableView(
  props: z.infer<typeof comparisonTableSchema>,
) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="rounded-2xl bg-zinc-900 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-500" />
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-300">
                {props.leftLabel}
              </th>
              <th className="px-3 py-2 text-left text-xs font-semibold text-zinc-300">
                {props.rightLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, i) => (
              <tr
                key={i}
                className={row.highlight ? "bg-violet-400/10" : "hover:bg-zinc-800/50 transition-colors"}
              >
                <td className="px-3 py-2 text-xs text-zinc-400">{row.label}</td>
                <td className="px-3 py-2 text-xs text-zinc-300">{row.left}</td>
                <td className="px-3 py-2 text-xs text-zinc-300">{row.right}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const STATUS_STYLES: Record<string, { bg: string; text: string; dot: string }> = {
  success: { bg: "bg-emerald-400/10", text: "text-emerald-400", dot: "bg-emerald-400" },
  error: { bg: "bg-red-400/10", text: "text-red-400", dot: "bg-red-400" },
  warning: { bg: "bg-amber-400/10", text: "text-amber-400", dot: "bg-amber-400" },
  info: { bg: "bg-blue-400/10", text: "text-blue-400", dot: "bg-blue-400" },
  pending: { bg: "bg-zinc-700/50", text: "text-zinc-400", dot: "bg-zinc-400" },
};

export function StatusCardView(props: z.infer<typeof statusCardSchema>) {
  const style = STATUS_STYLES[props.status] ?? STATUS_STYLES.pending;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className={`h-2 w-2 rounded-full ${style.dot}`} />
        <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${style.bg} ${style.text}`}>
          {props.status}
        </span>
      </div>
      {props.message && (
        <p className="text-sm text-zinc-300 mt-1">{props.message}</p>
      )}
      {props.detail && (
        <p className="text-xs text-zinc-500 mt-1">{props.detail}</p>
      )}
    </div>
  );
}

export function ActionCardView(props: z.infer<typeof actionCardSchema>) {
  const handleClick = (value: string) => {
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-semibold text-zinc-100 mb-1">{props.title}</p>
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      {props.actions && props.actions.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {props.actions.map((action, i) => (
            <Button
              key={i}
              size="sm"
              variant="flat"
              className="text-zinc-300"
              onPress={() => handleClick(action.value)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TagGroupView(props: z.infer<typeof tagGroupSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {props.tags.map((tag, i) => (
          <Chip
            key={i}
            size="sm"
            variant="flat"
            color={tag.color ?? "default"}
          >
            {tag.label}
          </Chip>
        ))}
      </div>
    </div>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-1 rounded-2xl bg-zinc-900 p-3">
        {props.items.map((item, i) => (
          <div key={i} className="flex items-center justify-between gap-2 py-0.5">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs text-zinc-500 shrink-0">
                {item.type === "dir" ? "📁" : "📄"}
              </span>
              <span className="text-xs font-mono text-zinc-300 truncate">{item.path}</span>
            </div>
            {item.size && (
              <span className="text-xs text-zinc-500 shrink-0">{item.size}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AccordionView(props: z.infer<typeof accordionSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-3 py-0">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 pt-3 pb-2">{props.title}</p>
      )}
      <HeroAccordion variant="light">
        {props.items.map((item, i) => (
          <AccordionItem
            key={i}
            aria-label={item.label}
            title={<span className="text-sm font-medium text-zinc-200">{item.label}</span>}
          >
            <p className="text-xs text-zinc-400 pb-2">{item.content}</p>
          </AccordionItem>
        ))}
      </HeroAccordion>
    </div>
  );
}

export function TabsBlockView(props: z.infer<typeof tabsBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <Tabs variant="underlined" size="sm">
        {props.tabs.map((tab, i) => (
          <Tab key={i} title={tab.label}>
            <div className="rounded-2xl bg-zinc-900 p-3 mt-2">
              <p className="text-xs text-zinc-300 whitespace-pre-wrap">{tab.content}</p>
            </div>
          </Tab>
        ))}
      </Tabs>
    </div>
  );
}

export function ProgressListView(props: z.infer<typeof progressListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => {
          const max = item.max ?? 100;
          const pct = Math.min(100, Math.round((item.value / max) * 100));
          return (
            <div key={i} className="rounded-2xl bg-zinc-900 p-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-medium text-zinc-200">{item.label}</span>
                <span className="text-xs text-zinc-500">{pct}%</span>
              </div>
              <Progress
                value={pct}
                color={item.color ?? "primary"}
                size="sm"
                className="w-full"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function StatRowView(props: z.infer<typeof statRowSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex flex-wrap gap-2">
        {props.stats.map((stat, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3 flex-1 min-w-[100px] text-center">
            <p className="text-xl font-semibold text-zinc-100">{stat.value}</p>
            <p className="text-xs text-zinc-500 mt-0.5">{stat.label}</p>
            {stat.description && (
              <p className="text-xs text-zinc-600 mt-0.5">{stat.description}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SelectableListView(props: z.infer<typeof selectableListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">{props.title}</p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <RadioGroup>
        <div className="space-y-2">
          {props.options.map((option, i) => (
            <div key={i} className="rounded-2xl bg-zinc-900 p-3 flex items-center gap-3">
              <Radio value={option.value} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-zinc-200">{option.label}</span>
                  {option.badge && (
                    <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400">
                      {option.badge}
                    </span>
                  )}
                </div>
                {option.description && (
                  <p className="text-xs text-zinc-400 mt-0.5">{option.description}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </RadioGroup>
    </div>
  );
}

export function AvatarListView(props: z.infer<typeof avatarListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3 flex items-center gap-3">
            <Avatar
              name={item.initials ?? item.name}
              size="sm"
              className="shrink-0"
              style={item.color ? { backgroundColor: item.color } : undefined}
            />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-zinc-200">{item.name}</p>
              {item.role && (
                <p className="text-xs text-zinc-400">{item.role}</p>
              )}
              {item.description && (
                <p className="text-xs text-zinc-500 truncate">{item.description}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function KbdBlockView(props: z.infer<typeof kbdBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.shortcuts.map((shortcut, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-4">
            <span className="text-xs text-zinc-400 flex-1">{shortcut.description}</span>
            <div className="flex items-center gap-1 shrink-0">
              {shortcut.keys.map((key, ki) => (
                <Kbd key={ki}>{key}</Kbd>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Analytics ----

const TREND_STYLES: Record<string, { color: string; symbol: string }> = {
  up: { color: "text-emerald-400", symbol: "↑" },
  down: { color: "text-red-400", symbol: "↓" },
  neutral: { color: "text-zinc-400", symbol: "→" },
};

export function MetricCardView(props: z.infer<typeof metricCardSchema>) {
  const trendStyle = props.trend ? TREND_STYLES[props.trend] : null;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-400 mb-1">{props.title}</p>
      <div className="flex items-end gap-2">
        <span className="text-3xl font-semibold text-zinc-100">{props.value}</span>
        {props.unit && <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>}
      </div>
      {trendStyle && props.trendLabel && (
        <p className={`text-xs mt-1 ${trendStyle.color}`}>
          {trendStyle.symbol} {props.trendLabel}
        </p>
      )}
    </div>
  );
}

export function BarChartView(props: z.infer<typeof barChartSchema>) {
  const color = props.color ?? CHART_COLORS[0];
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={200}>
        <RechartsBarChart data={props.data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
          <XAxis dataKey={props.xKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
            labelStyle={{ color: "#e4e4e7" }}
          />
          <Bar dataKey={props.yKey} fill={color} radius={[4, 4, 0, 0]} />
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LineChartView(props: z.infer<typeof lineChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={200}>
        <RechartsLineChart data={props.data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
          <XAxis dataKey={props.xKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
            labelStyle={{ color: "#e4e4e7" }}
          />
          <Legend />
          {props.yKeys.map((key, i) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={colors[i % colors.length]}
              dot={false}
            />
          ))}
        </RechartsLineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AreaChartView(props: z.infer<typeof areaChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={200}>
        <RechartsAreaChart data={props.data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
          <XAxis dataKey={props.xKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
            labelStyle={{ color: "#e4e4e7" }}
          />
          <Legend />
          {props.yKeys.map((key, i) => (
            <Area
              key={key}
              type="monotone"
              dataKey={key}
              stroke={colors[i % colors.length]}
              fill={`${colors[i % colors.length]}33`}
            />
          ))}
        </RechartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PieChartView(props: z.infer<typeof pieChartSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={200}>
        <RechartsPieChart>
          <Pie
            data={props.data}
            dataKey={props.valueKey}
            nameKey={props.nameKey}
            cx="50%"
            cy="50%"
            outerRadius={70}
            label
          >
            {props.data.map((_entry, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
          />
          <Legend />
        </RechartsPieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ScatterChartView(props: z.infer<typeof scatterChartSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={200}>
        <RechartsScatterChart>
          <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" />
          <XAxis dataKey={props.xKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <YAxis dataKey={props.yKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
          />
          <Scatter data={props.data} fill={CHART_COLORS[0]} />
        </RechartsScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RadarChartView(props: z.infer<typeof radarChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={220}>
        <RechartsRadarChart data={props.data}>
          <PolarGrid stroke="#3f3f46" />
          <PolarAngleAxis dataKey={props.angleKey} tick={{ fill: "#a1a1aa", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#18181b", border: "none", borderRadius: 12 }}
          />
          {props.valueKeys.map((key, i) => (
            <Radar
              key={key}
              dataKey={key}
              stroke={colors[i % colors.length]}
              fill={`${colors[i % colors.length]}33`}
            />
          ))}
          <Legend />
        </RechartsRadarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function GaugeChartView(props: z.infer<typeof gaugeChartSchema>) {
  const min = props.min ?? 0;
  const max = props.max ?? 100;
  const pct = Math.min(100, Math.max(0, ((props.value - min) / (max - min)) * 100));
  const warning = props.thresholds?.warning ?? 60;
  const danger = props.thresholds?.danger ?? 80;
  const color =
    pct >= danger
      ? "#f87171"
      : pct >= warning
        ? "#fbbf24"
        : "#34d399";

  const gaugeData = [
    { value: pct, fill: color },
    { value: 100 - pct, fill: "#27272a" },
  ];

  return (
    <div className="rounded-2xl bg-zinc-800 p-4 text-center">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <ResponsiveContainer width="100%" height={160}>
        <RadialBarChart
          innerRadius="60%"
          outerRadius="80%"
          data={gaugeData}
          startAngle={180}
          endAngle={0}
        >
          <RadialBar dataKey="value" background={false} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="-mt-8">
        <span className="text-2xl font-semibold" style={{ color }}>
          {props.value}
        </span>
        {props.unit && <span className="text-sm text-zinc-500 ml-1">{props.unit}</span>}
      </div>
    </div>
  );
}

// ---- Content ----

export function ImageBlockView(props: z.infer<typeof imageBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <img
        src={props.src}
        alt={props.alt ?? ""}
        className="w-full rounded-2xl object-cover max-h-96"
      />
      {props.caption && (
        <p className="text-xs text-zinc-500 mt-2 text-center">{props.caption}</p>
      )}
    </div>
  );
}

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="grid grid-cols-2 gap-2">
        {props.images.map((img, i) => (
          <div key={i} className="rounded-2xl overflow-hidden">
            <img
              src={img.src}
              alt={img.alt ?? ""}
              className="w-full object-cover h-40"
            />
            {img.caption && (
              <p className="text-xs text-zinc-500 mt-1 text-center">{img.caption}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function VideoBlockView(props: z.infer<typeof videoBlockSchema>) {
  const src = props.src;
  const isYouTube = src.includes("youtube.com") || src.includes("youtu.be");
  const isVimeo = src.includes("vimeo.com");

  let embedSrc = src;
  if (isYouTube) {
    const match =
      src.match(/[?&]v=([^&]+)/) ??
      src.match(/youtu\.be\/([^?]+)/) ??
      src.match(/embed\/([^?]+)/);
    const videoId = match?.[1];
    if (videoId) embedSrc = `https://www.youtube.com/embed/${videoId}`;
  } else if (isVimeo) {
    const match = src.match(/vimeo\.com\/(\d+)/);
    const videoId = match?.[1];
    if (videoId) embedSrc = `https://player.vimeo.com/video/${videoId}`;
  }

  const isEmbed = isYouTube || isVimeo;

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      {isEmbed ? (
        <iframe
          src={embedSrc}
          className="w-full rounded-2xl"
          style={{ height: "200px", border: "none" }}
          allowFullScreen
          title={props.title ?? "video"}
        />
      ) : (
        <video
          src={src}
          poster={props.poster}
          controls
          className="w-full rounded-2xl"
          style={{ maxHeight: "240px" }}
        />
      )}
    </div>
  );
}

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">{props.title}</p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <audio src={props.src} controls className="w-full mt-2" />
    </div>
  );
}

const DIFF_STYLES: Record<string, string> = {
  add: "bg-emerald-400/10 text-emerald-400",
  remove: "bg-red-400/10 text-red-400",
  context: "text-zinc-400",
};

export function DiffBlockView(props: z.infer<typeof diffBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-2">
        {props.hunks.map((hunk, hi) => (
          <div key={hi} className="rounded-2xl bg-zinc-900 overflow-auto">
            <div className="px-3 py-1.5 bg-zinc-700/50">
              <span className="text-xs font-mono text-zinc-500">{hunk.header}</span>
            </div>
            <div className="p-2">
              {hunk.lines.map((line, li) => (
                <div key={li} className={`px-2 py-0.5 rounded text-xs font-mono ${DIFF_STYLES[line.type] ?? ""}`}>
                  <span className="mr-2 select-none text-zinc-600">
                    {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
                  </span>
                  {line.content}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { lat, lng } = props;
  const bbox = `${lng - 0.01},${lat - 0.01},${lng + 0.01},${lat + 0.01}`;
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lng}`;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.label && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.label}</p>
      )}
      <iframe
        src={src}
        className="w-full rounded-2xl"
        style={{ height: "200px", border: "none" }}
        title={props.label ?? "map"}
      />
    </div>
  );
}

export function CalendarMiniView(props: z.infer<typeof calendarMiniSchema>) {
  const dates = props.markedDates.map((d) => new Date(d.date));
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="rounded-2xl bg-zinc-900 p-3 flex justify-center">
        <DayPicker
          mode="multiple"
          selected={dates}
          className="rdp-dark"
          styles={{
            caption: { color: "#e4e4e7" },
            day: { color: "#a1a1aa" },
          }}
        />
      </div>
      {props.markedDates.some((d) => d.label) && (
        <div className="mt-2 space-y-1">
          {props.markedDates.filter((d) => d.label).map((d, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-xs text-zinc-500">{d.date}</span>
              <span className="text-xs text-zinc-300">{d.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 text-center">
      {props.label && (
        <p className="text-xs text-zinc-400 mb-1">{props.label}</p>
      )}
      <div className="flex items-end justify-center gap-1">
        <span className="text-3xl font-semibold text-zinc-100">
          <AnimatedNumber
            value={props.value}
            duration={props.duration ?? 1000}
            formatValue={(v: number) => Math.round(v).toLocaleString()}
          />
        </span>
        {props.unit && (
          <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
    </div>
  );
}

export function CarouselView(props: z.infer<typeof carouselSchema>) {
  const [current, setCurrent] = React.useState(0);
  const total = props.items.length;

  const handlePrev = () => setCurrent((c) => (c - 1 + total) % total);
  const handleNext = () => setCurrent((c) => (c + 1) % total);

  const handleAction = (value: string) => {
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  const item = props.items[current];
  if (!item) return null;

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="relative overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={current}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -40 }}
            transition={{ duration: 0.2 }}
            className="rounded-2xl bg-zinc-900 p-3"
          >
            {item.image && (
              <img
                src={item.image}
                alt={item.title}
                className="w-full rounded-2xl object-cover h-40 mb-3"
              />
            )}
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-zinc-200">{item.title}</p>
              {item.badge && (
                <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400 shrink-0">
                  {item.badge}
                </span>
              )}
            </div>
            {item.body && (
              <p className="text-xs text-zinc-400 mt-1">{item.body}</p>
            )}
            {item.actions && item.actions.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {item.actions.map((action, i) => (
                  <Button
                    key={i}
                    size="sm"
                    variant="flat"
                    className="text-zinc-300"
                    onPress={() => handleAction(action.value)}
                  >
                    {action.label}
                  </Button>
                ))}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
      {total > 1 && (
        <div className="flex items-center justify-between mt-3">
          <Button size="sm" variant="flat" className="text-zinc-400" onPress={handlePrev}>
            ←
          </Button>
          <span className="text-xs text-zinc-500">{current + 1} / {total}</span>
          <Button size="sm" variant="flat" className="text-zinc-400" onPress={handleNext}>
            →
          </Button>
        </div>
      )}
    </div>
  );
}

interface TreeNode {
  id: string;
  label: string;
  description?: string;
  children?: TreeNode[];
}

function TreeNodeItem({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = React.useState(depth === 0);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div style={{ paddingLeft: depth * 12 }}>
      <div
        className="flex items-start gap-2 py-1 cursor-pointer"
        onClick={() => hasChildren && setExpanded((e) => !e)}
      >
        <span className="text-xs text-zinc-600 mt-0.5 w-3 shrink-0">
          {hasChildren ? (expanded ? "▼" : "▶") : "·"}
        </span>
        <div>
          <span className="text-xs font-medium text-zinc-300">{node.label}</span>
          {node.description && (
            <span className="text-xs text-zinc-500 ml-2">{node.description}</span>
          )}
        </div>
      </div>
      {expanded && hasChildren && node.children?.map((child) => (
        <TreeNodeItem key={child.id} node={child as TreeNode} depth={depth + 1} />
      ))}
    </div>
  );
}

export function TreeViewView(props: z.infer<typeof treeViewSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="rounded-2xl bg-zinc-900 p-3">
        {props.nodes.map((node) => (
          <TreeNodeItem key={node.id} node={node as TreeNode} depth={0} />
        ))}
      </div>
    </div>
  );
}

// ---- Timeline & Notifications ----

const TIMELINE_DOT: Record<string, string> = {
  success: "bg-emerald-400",
  error: "bg-red-400",
  warning: "bg-amber-400",
  neutral: "bg-zinc-500",
};

export function TimelineView(props: z.infer<typeof timelineSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-0">
        {props.items.map((item, i) => {
          const dotColor = TIMELINE_DOT[item.status ?? "neutral"];
          const isLast = i === props.items.length - 1;
          return (
            <div key={i} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className={`h-2.5 w-2.5 rounded-full shrink-0 mt-1 ${dotColor}`} />
                {!isLast && <div className="w-px flex-1 bg-zinc-700 my-1" />}
              </div>
              <div className="pb-3 flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-zinc-200">{item.title}</p>
                  <span className="text-xs text-zinc-500 shrink-0">{item.time}</span>
                </div>
                {item.description && (
                  <p className="text-xs text-zinc-400 mt-0.5">{item.description}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function JsonViewerView(props: z.infer<typeof jsonViewerSchema>) {
  let displayText: string;
  try {
    const parsed: unknown = JSON.parse(props.data);
    displayText = JSON.stringify(parsed, null, 2);
  } catch (_err) {
    displayText = props.data;
  }

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <pre className="text-xs text-zinc-300 font-mono overflow-auto max-h-64 bg-zinc-900 rounded-2xl p-3 whitespace-pre-wrap">
        {displayText}
      </pre>
    </div>
  );
}

const ALERT_STYLES: Record<string, { bg: string; text: string; accent: string; dot: string }> = {
  info: { bg: "bg-blue-400/10", text: "text-blue-400", accent: "text-blue-300", dot: "bg-blue-400" },
  success: { bg: "bg-emerald-400/10", text: "text-emerald-400", accent: "text-emerald-300", dot: "bg-emerald-400" },
  warning: { bg: "bg-amber-400/10", text: "text-amber-400", accent: "text-amber-300", dot: "bg-amber-400" },
  error: { bg: "bg-red-400/10", text: "text-red-400", accent: "text-red-300", dot: "bg-red-400" },
};

export function AlertBannerView(props: z.infer<typeof alertBannerSchema>) {
  const style = ALERT_STYLES[props.variant] ?? ALERT_STYLES.info;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className={`h-2 w-2 rounded-full ${style.dot}`} />
        <p className="text-sm font-semibold text-zinc-100">{props.title}</p>
        <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${style.bg} ${style.text}`}>
          {props.variant}
        </span>
      </div>
      {props.description && (
        <p className={`text-xs mt-1 ${style.accent}`}>{props.description}</p>
      )}
    </div>
  );
}

const STEP_STYLES: Record<string, { dot: string; label: string }> = {
  complete: { dot: "bg-emerald-400", label: "text-zinc-300" },
  active: { dot: "bg-blue-400", label: "text-zinc-100" },
  pending: { dot: "bg-zinc-600", label: "text-zinc-500" },
};

export function StepsView(props: z.infer<typeof stepsSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      )}
      <div className="space-y-0">
        {props.items.map((item, i) => {
          const status = item.status ?? "pending";
          const style = STEP_STYLES[status];
          const isLast = i === props.items.length - 1;
          return (
            <div key={i} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className={`h-3 w-3 rounded-full shrink-0 mt-0.5 ${style.dot}`} />
                {!isLast && <div className="w-px flex-1 bg-zinc-700 my-1" />}
              </div>
              <div className="pb-3 flex-1">
                <p className={`text-sm font-medium ${style.label}`}>{item.title}</p>
                {item.description && (
                  <p className="text-xs text-zinc-500 mt-0.5">{item.description}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// defineComponent calls
// ---------------------------------------------------------------------------

const dataCardDef = defineComponent({
  name: "DataCard",
  description: "Single record fields as label-value pairs.",
  props: dataCardSchema,
  component: ({ props }) => React.createElement(DataCardView, props),
});

const resultListDef = defineComponent({
  name: "ResultList",
  description: "List of results with title, subtitle, body, url, badge.",
  props: resultListSchema,
  component: ({ props }) => React.createElement(ResultListView, props),
});

const dataTableDef = defineComponent({
  name: "DataTable",
  description: "Tabular data with columns and rows.",
  props: dataTableSchema,
  component: ({ props }) => React.createElement(DataTableView, props),
});

const comparisonTableDef = defineComponent({
  name: "ComparisonTable",
  description: "A vs B comparison table.",
  props: comparisonTableSchema,
  component: ({ props }) => React.createElement(ComparisonTableView, props),
});

const statusCardDef = defineComponent({
  name: "StatusCard",
  description: "Operation result card with status indicator.",
  props: statusCardSchema,
  component: ({ props }) => React.createElement(StatusCardView, props),
});

const actionCardDef = defineComponent({
  name: "ActionCard",
  description: "Next-step suggestions with action buttons.",
  props: actionCardSchema,
  component: ({ props }) => React.createElement(ActionCardView, props),
});

const tagGroupDef = defineComponent({
  name: "TagGroup",
  description: "Flat set of labeled chips/tags.",
  props: tagGroupSchema,
  component: ({ props }) => React.createElement(TagGroupView, props),
});

const fileTreeDef = defineComponent({
  name: "FileTree",
  description: "Directory or file listing.",
  props: fileTreeSchema,
  component: ({ props }) => React.createElement(FileTreeView, props),
});

const accordionDef = defineComponent({
  name: "Accordion",
  description: "Collapsible sections with label and content.",
  props: accordionSchema,
  component: ({ props }) => React.createElement(AccordionView, props),
});

const tabsBlockDef = defineComponent({
  name: "TabsBlock",
  description: "Tabbed content panels.",
  props: tabsBlockSchema,
  component: ({ props }) => React.createElement(TabsBlockView, props),
});

const progressListDef = defineComponent({
  name: "ProgressList",
  description: "Labeled progress bars.",
  props: progressListSchema,
  component: ({ props }) => React.createElement(ProgressListView, props),
});

const statRowDef = defineComponent({
  name: "StatRow",
  description: "Horizontal strip of labeled statistics.",
  props: statRowSchema,
  component: ({ props }) => React.createElement(StatRowView, props),
});

const selectableListDef = defineComponent({
  name: "SelectableList",
  description: "Selectable options with radio group.",
  props: selectableListSchema,
  component: ({ props }) => React.createElement(SelectableListView, props),
});

const avatarListDef = defineComponent({
  name: "AvatarList",
  description: "People list with avatars.",
  props: avatarListSchema,
  component: ({ props }) => React.createElement(AvatarListView, props),
});

const kbdBlockDef = defineComponent({
  name: "KbdBlock",
  description: "Keyboard shortcut reference table.",
  props: kbdBlockSchema,
  component: ({ props }) => React.createElement(KbdBlockView, props),
});

const metricCardDef = defineComponent({
  name: "MetricCard",
  description: "Single KPI with optional trend.",
  props: metricCardSchema,
  component: ({ props }) => React.createElement(MetricCardView, props),
});

const barChartDef = defineComponent({
  name: "BarChart",
  description: "Bar chart for comparisons and distributions.",
  props: barChartSchema,
  component: ({ props }) => React.createElement(BarChartView, props),
});

const lineChartDef = defineComponent({
  name: "LineChart",
  description: "Line chart for trends over time.",
  props: lineChartSchema,
  component: ({ props }) => React.createElement(LineChartView, props),
});

const areaChartDef = defineComponent({
  name: "AreaChart",
  description: "Filled area chart for cumulative values.",
  props: areaChartSchema,
  component: ({ props }) => React.createElement(AreaChartView, props),
});

const pieChartDef = defineComponent({
  name: "PieChart",
  description: "Pie chart for proportions.",
  props: pieChartSchema,
  component: ({ props }) => React.createElement(PieChartView, props),
});

const scatterChartDef = defineComponent({
  name: "ScatterChart",
  description: "Scatter chart for correlation between two variables.",
  props: scatterChartSchema,
  component: ({ props }) => React.createElement(ScatterChartView, props),
});

const radarChartDef = defineComponent({
  name: "RadarChart",
  description: "Radar chart for multi-axis comparisons.",
  props: radarChartSchema,
  component: ({ props }) => React.createElement(RadarChartView, props),
});

const gaugeChartDef = defineComponent({
  name: "GaugeChart",
  description: "Radial gauge for a value with min/max bounds.",
  props: gaugeChartSchema,
  component: ({ props }) => React.createElement(GaugeChartView, props),
});

const imageBlockDef = defineComponent({
  name: "ImageBlock",
  description: "Single image with optional caption.",
  props: imageBlockSchema,
  component: ({ props }) => React.createElement(ImageBlockView, props),
});

const imageGalleryDef = defineComponent({
  name: "ImageGallery",
  description: "Grid of images with captions.",
  props: imageGallerySchema,
  component: ({ props }) => React.createElement(ImageGalleryView, props),
});

const videoBlockDef = defineComponent({
  name: "VideoBlock",
  description: "YouTube/Vimeo embed or native video player.",
  props: videoBlockSchema,
  component: ({ props }) => React.createElement(VideoBlockView, props),
});

const audioPlayerDef = defineComponent({
  name: "AudioPlayer",
  description: "Audio player with title and description.",
  props: audioPlayerSchema,
  component: ({ props }) => React.createElement(AudioPlayerView, props),
});

const diffBlockDef = defineComponent({
  name: "DiffBlock",
  description: "Code diff viewer with add/remove/context lines.",
  props: diffBlockSchema,
  component: ({ props }) => React.createElement(DiffBlockView, props),
});

const mapBlockDef = defineComponent({
  name: "MapBlock",
  description: "OpenStreetMap embed for a lat/lng location.",
  props: mapBlockSchema,
  component: ({ props }) => React.createElement(MapBlockView, props),
});

const calendarMiniDef = defineComponent({
  name: "CalendarMini",
  description: "Mini calendar with marked dates.",
  props: calendarMiniSchema,
  component: ({ props }) => React.createElement(CalendarMiniView, props),
});

const numberTickerDef = defineComponent({
  name: "NumberTicker",
  description: "Animated count-up number display.",
  props: numberTickerSchema,
  component: ({ props }) => React.createElement(NumberTickerView, props),
});

const carouselDef = defineComponent({
  name: "Carousel",
  description: "Swipeable card carousel.",
  props: carouselSchema,
  component: ({ props }) => React.createElement(CarouselView, props),
});

const treeViewDef = defineComponent({
  name: "TreeView",
  description: "Collapsible tree of nested nodes.",
  props: treeViewSchema,
  component: ({ props }) => React.createElement(TreeViewView, props),
});

const timelineDef = defineComponent({
  name: "Timeline",
  description: "Ordered sequence of events with timestamps.",
  props: timelineSchema,
  component: ({ props }) => React.createElement(TimelineView, props),
});

const jsonViewerDef = defineComponent({
  name: "JsonViewer",
  description: "Pretty-printed JSON viewer.",
  props: jsonViewerSchema,
  component: ({ props }) => React.createElement(JsonViewerView, props),
});

const alertBannerDef = defineComponent({
  name: "AlertBanner",
  description: "Inline alert notice with variant styling.",
  props: alertBannerSchema,
  component: ({ props }) => React.createElement(AlertBannerView, props),
});

const stepsDef = defineComponent({
  name: "Steps",
  description: "Ordered step sequence with completion status.",
  props: stepsSchema,
  component: ({ props }) => React.createElement(StepsView, props),
});

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

export const genericLibrary = createLibrary({
  components: [
    dataCardDef,
    resultListDef,
    dataTableDef,
    comparisonTableDef,
    statusCardDef,
    actionCardDef,
    tagGroupDef,
    fileTreeDef,
    accordionDef,
    tabsBlockDef,
    progressListDef,
    statRowDef,
    selectableListDef,
    avatarListDef,
    kbdBlockDef,
    metricCardDef,
    barChartDef,
    lineChartDef,
    areaChartDef,
    pieChartDef,
    scatterChartDef,
    radarChartDef,
    gaugeChartDef,
    imageBlockDef,
    imageGalleryDef,
    videoBlockDef,
    audioPlayerDef,
    diffBlockDef,
    mapBlockDef,
    calendarMiniDef,
    numberTickerDef,
    carouselDef,
    treeViewDef,
    timelineDef,
    jsonViewerDef,
    alertBannerDef,
    stepsDef,
  ],
  componentGroups: [
    {
      name: "Layout & Data",
      components: [
        "DataCard",
        "ResultList",
        "DataTable",
        "ComparisonTable",
        "StatusCard",
        "ActionCard",
        "TagGroup",
        "FileTree",
        "Accordion",
        "TabsBlock",
        "ProgressList",
        "StatRow",
        "SelectableList",
        "AvatarList",
        "KbdBlock",
      ],
      notes: [
        "DataCard for single records",
        "ResultList for collections",
        "DataTable for multi-column tabular data",
      ],
    },
    {
      name: "Analytics",
      components: [
        "MetricCard",
        "BarChart",
        "LineChart",
        "AreaChart",
        "PieChart",
        "ScatterChart",
        "RadarChart",
        "GaugeChart",
      ],
      notes: [
        "MetricCard for single KPI",
        "GaugeChart for value with min/max bounds",
        "RadarChart for multi-axis comparisons",
      ],
    },
    {
      name: "Content",
      components: [
        "ImageBlock",
        "ImageGallery",
        "VideoBlock",
        "AudioPlayer",
        "DiffBlock",
        "MapBlock",
        "CalendarMini",
        "NumberTicker",
        "Carousel",
        "TreeView",
      ],
      notes: [
        "VideoBlock auto-embeds YouTube and Vimeo URLs",
        "MapBlock renders OpenStreetMap for any lat/lng",
      ],
    },
    {
      name: "Timeline & Notifications",
      components: ["Timeline", "JsonViewer", "AlertBanner", "Steps"],
      notes: [
        "Timeline for event sequences",
        "JsonViewer for raw API responses",
        "AlertBanner for inline notices",
        "Steps for ordered instructions",
      ],
    },
  ],
});
