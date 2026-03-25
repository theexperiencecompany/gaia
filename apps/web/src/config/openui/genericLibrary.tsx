import { Calendar, type DateValue } from "@heroui/calendar";
import { Card, CardBody, CardFooter, CardHeader } from "@heroui/card";
import {
  AccordionItem,
  Avatar,
  AvatarGroup,
  Button,
  Chip,
  Accordion as HeroAccordion,
  Kbd,
  Progress,
  Radio,
  RadioGroup,
  Tab,
  Tabs,
} from "@heroui/react";
import {
  ArrowDown01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  File01Icon,
  Folder02Icon,
} from "@icons";
import { CalendarDate } from "@internationalized/date";
import { createLibrary, defineComponent } from "@openuidev/react-lang";
import { motion } from "motion/react";
import React from "react";
import {
  Area,
  Bar,
  Cell,
  Line,
  Pie,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadialBar,
  RadialBarChart,
  AreaChart as RechartsAreaChart,
  BarChart as RechartsBarChart,
  LineChart as RechartsLineChart,
  PieChart as RechartsPieChart,
  RadarChart as RechartsRadarChart,
  ScatterChart as RechartsScatterChart,
  Scatter,
  XAxis,
  YAxis,
} from "recharts";
import { z } from "zod";
import { ChevronLeft, ChevronRight } from "@/components/shared/icons";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
  useCarousel,
} from "@/components/ui/carousel";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { NumberTicker } from "@/components/ui/number-ticker";

// ---------------------------------------------------------------------------
// Chart color palette
// ---------------------------------------------------------------------------
const CHART_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#f472b6", "#fb923c"];

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const stackSchema = z.object({
  items: z.array(z.any()),
});

const dataCardSchema = z.object({
  title: z.string(),
  fields: z.array(z.object({ label: z.string(), value: z.string() })),
});

const resultListSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      subtitle: z.string().optional(),
      body: z.string().optional(),
      url: z.string().optional(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

const dataTableSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.array(z.string())),
  title: z.string().optional(),
});

const comparisonTableSchema = z.object({
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
  title: z.string().optional(),
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
  tags: z.array(
    z.object({
      label: z.string(),
      color: z
        .enum(["default", "primary", "success", "warning", "danger"])
        .optional(),
    }),
  ),
  title: z.string().optional(),
});

const fileTreeSchema = z.object({
  items: z.array(
    z.object({
      path: z.string(),
      type: z.enum(["file", "dir"]),
      size: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

const accordionSchema = z.object({
  items: z.array(z.object({ label: z.string(), content: z.string() })),
  title: z.string().optional(),
});

const tabsBlockSchema = z.object({
  tabs: z.array(z.object({ label: z.string(), content: z.string() })),
});

const progressListSchema = z.object({
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
  title: z.string().optional(),
});

const selectableListSchema = z.object({
  options: z.array(
    z.object({
      label: z.string(),
      description: z.string().optional(),
      value: z.string(),
      badge: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
  description: z.string().optional(),
});

const avatarListSchema = z.object({
  items: z.array(
    z.object({
      name: z.string(),
      role: z.string().optional(),
      description: z.string().optional(),
      initials: z.string().optional(),
      color: z.string().optional(),
    }),
  ),
  title: z.string().optional(),
});

const kbdBlockSchema = z.object({
  shortcuts: z.array(
    z.object({ keys: z.array(z.string()), description: z.string() }),
  ),
  title: z.string().optional(),
});

// Analytics schemas
const statRowSchema = z.object({
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
  data: chartDataSchema,
  xKey: z.string(),
  yKey: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  color: z.string().optional(),
});

const lineChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.array(z.string()),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
});

const areaChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKeys: z.array(z.string()),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
});

const pieChartSchema = z.object({
  data: chartDataSchema,
  nameKey: z.string(),
  valueKey: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
});

const scatterChartSchema = z.object({
  data: chartDataSchema,
  xKey: z.string(),
  yKey: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  labelKey: z.string().optional(),
});

const radarChartSchema = z.object({
  data: chartDataSchema,
  angleKey: z.string(),
  valueKeys: z.array(z.string()),
  title: z.string().optional(),
  description: z.string().optional(),
  footer: z.string().optional(),
  colors: z.array(z.string()).optional(),
});

const gaugeChartSchema = z.object({
  value: z.number(),
  title: z.string().optional(),
  min: z.number().optional(),
  max: z.number().optional(),
  unit: z.string().optional(),
  thresholds: z.object({ warning: z.number(), danger: z.number() }).optional(),
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

const mapBlockSchema = z.object({
  lat: z.number(),
  lng: z.number(),
  label: z.string().optional(),
  zoom: z.number().optional(),
});

const calendarMiniSchema = z.object({
  markedDates: z.array(
    z.object({
      date: z.string(),
      label: z.string().optional(),
      color: z.enum(["success", "warning", "danger", "default"]).optional(),
    }),
  ),
  title: z.string().optional(),
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
  nodes: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      description: z.string().optional(),
      children: z.array(z.unknown()).optional(),
    }),
  ),
  title: z.string().optional(),
});

// Timeline & Notifications schemas
const timelineSchema = z.object({
  items: z.array(
    z.object({
      time: z.string(),
      title: z.string(),
      description: z.string().optional(),
      status: z.enum(["success", "error", "warning", "neutral"]).optional(),
    }),
  ),
  title: z.string().optional(),
});

const alertBannerSchema = z.object({
  variant: z.enum(["info", "success", "warning", "error"]),
  title: z.string(),
  description: z.string().optional(),
});

const stepsSchema = z.object({
  items: z.array(
    z.object({
      title: z.string(),
      description: z.string().optional(),
      status: z.enum(["complete", "active", "pending"]).optional(),
    }),
  ),
  title: z.string().optional(),
});

// ---------------------------------------------------------------------------
// Component Implementations
// ---------------------------------------------------------------------------

// ---- Layout & Data ----

export function DataCardView(props: z.infer<typeof dataCardSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      <p className="text-sm font-semibold text-zinc-100 mb-3">{props.title}</p>
      <div className="space-y-2">
        {props.fields.map((field, i) => (
          <div
            key={i}
            className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-4"
          >
            <span className="text-xs text-zinc-500">{field.label}</span>
            <span className="text-sm font-medium text-zinc-200">
              {field.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ResultListView(props: z.infer<typeof resultListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => (
          <div key={i} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium text-zinc-200">
                {item.title}
              </span>
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
              <div className="flex items-center gap-1 mt-1.5">
                <span className="text-xs text-zinc-600 truncate flex-1">
                  {item.url}
                </span>
                <ArrowRight01Icon className="w-3 h-3 text-zinc-600 shrink-0" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function DataTableView(props: z.infer<typeof dataTableSchema>) {
  return (
    <div>
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="overflow-auto rounded-2xl bg-zinc-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800">
              {props.columns.map((col, i) => (
                <th
                  key={i}
                  className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-500"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, ri) => (
              <tr
                key={ri}
                className={
                  ri % 2 === 0
                    ? "bg-zinc-900 hover:bg-zinc-800/40 transition-colors"
                    : "bg-transparent hover:bg-zinc-800/40 transition-colors"
                }
              >
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
    <div>
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="rounded-2xl bg-zinc-900 overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800">
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-500" />
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-300">
                {props.leftLabel}
              </th>
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-zinc-300">
                {props.rightLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {props.rows.map((row, i) => (
              <tr
                key={i}
                className={
                  row.highlight
                    ? "bg-[#00bbff]/5"
                    : "hover:bg-zinc-800/40 transition-colors"
                }
              >
                <td className="px-3 py-2 text-xs text-zinc-500">{row.label}</td>
                <td className="px-3 py-2 text-xs text-zinc-300">
                  {row.left.toLowerCase() === "yes" ? (
                    <CheckmarkCircle01Icon className="w-4 h-4 text-emerald-400" />
                  ) : row.left.toLowerCase() === "no" ? (
                    <Cancel01Icon className="w-4 h-4 text-red-400/70" />
                  ) : (
                    row.left
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-zinc-300">
                  {row.right.toLowerCase() === "yes" ? (
                    <CheckmarkCircle01Icon className="w-4 h-4 text-emerald-400" />
                  ) : row.right.toLowerCase() === "no" ? (
                    <Cancel01Icon className="w-4 h-4 text-red-400/70" />
                  ) : (
                    row.right
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const STATUS_CHIP_COLOR: Record<
  string,
  "success" | "danger" | "warning" | "default"
> = {
  success: "success",
  error: "danger",
  warning: "warning",
  pending: "default",
};

const STATUS_DOT: Record<string, string> = {
  success: "bg-emerald-400",
  error: "bg-red-400",
  warning: "bg-amber-400",
  info: "bg-blue-400",
  pending: "bg-zinc-500",
};

export function StatusCardView(props: z.infer<typeof statusCardSchema>) {
  const chipColor = STATUS_CHIP_COLOR[props.status] ?? "default";
  const dotColor = STATUS_DOT[props.status] ?? "bg-zinc-500";
  const isPending = props.status === "pending";
  const isInfo = props.status === "info";
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-xl">
      <div className="flex items-center gap-2 mb-2">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          {isPending && (
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-50 ${dotColor}`}
            />
          )}
          <span
            className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dotColor}`}
          />
        </span>
        <p className="text-sm font-medium text-zinc-200 flex-1">
          {props.title}
        </p>
        {isInfo ? (
          <span className="inline-flex items-center rounded-full bg-[#00bbff]/10 px-2 py-0.5 text-xs font-medium text-[#00bbff]">
            {props.status.charAt(0).toUpperCase() + props.status.slice(1)}
          </span>
        ) : (
          <Chip size="sm" variant="flat" color={chipColor}>
            {props.status.charAt(0).toUpperCase() + props.status.slice(1)}
          </Chip>
        )}
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
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      <p className="text-sm font-semibold text-zinc-100 mb-1">{props.title}</p>
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      {props.actions && props.actions.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {props.actions.map((action, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleClick(action.value)}
              className="rounded-full bg-zinc-700/60 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition-colors cursor-pointer"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TagGroupView(props: z.infer<typeof tagGroupSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {props.tags.map((tag, i) =>
          tag.color === "primary" ? (
            <span
              key={i}
              className="inline-flex items-center rounded-full bg-[#00bbff]/10 px-2 py-0.5 text-xs font-medium text-[#00bbff]"
            >
              {tag.label}
            </span>
          ) : (
            <Chip
              key={i}
              size="sm"
              variant="flat"
              color={tag.color ?? "default"}
            >
              {tag.label}
            </Chip>
          ),
        )}
      </div>
    </div>
  );
}

type FileTreeNode = {
  name: string;
  type: "file" | "dir";
  size?: string;
  children: Record<string, FileTreeNode>;
};

function buildFileTree(
  items: Array<{ path: string; type: "file" | "dir"; size?: string }>,
): Record<string, FileTreeNode> {
  const root: Record<string, FileTreeNode> = {};
  for (const item of items) {
    const parts = item.path.replace(/\/$/, "").split("/").filter(Boolean);
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      if (!current[part]) {
        current[part] = {
          name: part,
          type: isLast ? item.type : "dir",
          size: isLast ? item.size : undefined,
          children: {},
        };
      }
      current = current[part].children;
    }
  }
  return root;
}

function FileTreeNodeRow({
  node,
  depth,
}: {
  node: FileTreeNode;
  depth: number;
}) {
  const [open, setOpen] = React.useState(true);
  const isDir = node.type === "dir";
  const hasChildren = Object.keys(node.children).length > 0;

  return (
    <div>
      <div
        className="flex items-center justify-between gap-2 px-2 py-1 rounded-lg hover:bg-zinc-800/60 transition cursor-pointer select-none"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        onClick={isDir && hasChildren ? () => setOpen((o) => !o) : undefined}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {isDir && hasChildren ? (
            open ? (
              <ArrowDown01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
            ) : (
              <ArrowRight01Icon className="w-3 h-3 text-zinc-500 shrink-0" />
            )
          ) : (
            <span className="w-3 h-3 shrink-0" />
          )}
          {isDir ? (
            <Folder02Icon className="w-4 h-4 text-[#00bbff] shrink-0" />
          ) : (
            <File01Icon className="w-4 h-4 text-zinc-500 shrink-0" />
          )}
          <span
            className={
              isDir
                ? "text-sm font-medium text-zinc-300 truncate"
                : "text-sm text-zinc-400 truncate"
            }
          >
            {node.name}
          </span>
        </div>
        {!isDir && node.size && (
          <span className="text-xs text-zinc-600 shrink-0">{node.size}</span>
        )}
      </div>
      {isDir && open && hasChildren && (
        <div>
          {Object.values(node.children).map((child) => (
            <FileTreeNodeRow key={child.name} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function FileTreeView(props: z.infer<typeof fileTreeSchema>) {
  const tree = buildFileTree(props.items);
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div>
        {Object.values(tree).map((node) => (
          <FileTreeNodeRow key={node.name} node={node} depth={0} />
        ))}
      </div>
    </div>
  );
}

export function AccordionView(props: z.infer<typeof accordionSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-3 py-0 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 pt-3 pb-2">
          {props.title}
        </p>
      )}
      <HeroAccordion variant="light">
        {props.items.map((item, i) => (
          <AccordionItem
            key={i}
            aria-label={item.label}
            title={
              <span className="text-sm font-medium text-zinc-200">
                {item.label}
              </span>
            }
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
    <Tabs variant="solid" size="sm">
      {props.tabs.map((tab, i) => (
        <Tab key={i} title={<span className="text-sm">{tab.label}</span>}>
          <div className="rounded-2xl bg-zinc-800/50 p-4">
            <p className="text-sm text-zinc-300 whitespace-pre-wrap">
              {tab.content}
            </p>
          </div>
        </Tab>
      ))}
    </Tabs>
  );
}

export function ProgressListView(props: z.infer<typeof progressListSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => {
          const max = item.max ?? 100;
          const pct = Math.min(100, Math.round((item.value / max) * 100));
          return (
            <div key={i} className="rounded-2xl bg-zinc-900 p-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-medium text-zinc-200">
                  {item.label}
                </span>
                <span className="text-xs text-zinc-500">{pct}%</span>
              </div>
              <Progress
                value={pct}
                color={item.color ?? "primary"}
                size="sm"
                className="w-full"
                classNames={{
                  indicator:
                    !item.color || item.color === "primary"
                      ? "!bg-[#00bbff]"
                      : undefined,
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SelectableListView(
  props: z.infer<typeof selectableListSchema>,
) {
  const [selected, setSelected] = React.useState<string>("");

  const handleSelect = (value: string) => {
    setSelected(value);
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-sm">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <RadioGroup
        value={selected}
        onValueChange={handleSelect}
        orientation="vertical"
        classNames={{ wrapper: "space-y-2" }}
      >
        {props.options.map((option, i) => (
          <Radio
            key={i}
            value={option.value}
            classNames={{
              base: [
                "rounded-2xl bg-zinc-900 p-3 m-0 min-w-full cursor-pointer",
                "data-[selected=true]:bg-primary/20!",
              ].join(" "),
              wrapper: "group-data-[selected=true]:border-[#00bbff]",
              label: "text-zinc-200",
              description: "text-zinc-400",
            }}
            description={option.description}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-zinc-200">
                {option.label}
              </span>
              {option.badge && (
                <span className="rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs text-zinc-400">
                  {option.badge}
                </span>
              )}
            </div>
          </Radio>
        ))}
      </RadioGroup>
    </div>
  );
}

export function AvatarListView(props: z.infer<typeof avatarListSchema>) {
  const hasDetails = props.items.some((item) => item.role || item.description);
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      {hasDetails ? (
        <div className="space-y-2">
          {props.items.map((item, i) => (
            <div key={i} className="flex items-center gap-3">
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
                  <p className="text-xs text-zinc-500 truncate">
                    {item.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <AvatarGroup max={7} size="sm">
          {props.items.map((item, i) => (
            <Avatar
              key={i}
              name={item.initials ?? item.name}
              className="shrink-0"
              style={item.color ? { backgroundColor: item.color } : undefined}
            />
          ))}
        </AvatarGroup>
      )}
    </div>
  );
}

export function KbdBlockView(props: z.infer<typeof kbdBlockSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.shortcuts.map((shortcut, i) => (
          <div
            key={i}
            className="rounded-2xl bg-zinc-900 p-3 flex items-center justify-between gap-4"
          >
            <span className="text-xs text-zinc-400 flex-1">
              {shortcut.description}
            </span>
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

const TREND_STYLES: Record<string, { color: string }> = {
  up: { color: "text-emerald-400" },
  down: { color: "text-red-400" },
  neutral: { color: "text-zinc-400" },
};

function TrendIcon({
  trend,
  className,
}: {
  trend: string;
  className?: string;
}) {
  if (trend === "up") return <ArrowUp01Icon className={className} />;
  if (trend === "down") return <ArrowDown01Icon className={className} />;
  return <ArrowRight01Icon className={className} />;
}

export function StatRowView(props: z.infer<typeof statRowSchema>) {
  const trendStyle = props.trend ? TREND_STYLES[props.trend] : null;
  return (
    <div className="rounded-2xl bg-zinc-800 p-5 flex-1 min-w-[160px]">
      <p className="text-xs text-zinc-500 mb-1.5">{props.title}</p>
      <div className="flex items-end gap-1.5">
        <span className="text-4xl font-bold text-zinc-100 leading-none">
          {props.value}
        </span>
        {props.unit && (
          <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
      {trendStyle && props.trendLabel && props.trend && (
        <div className={`flex items-center gap-1 mt-2 ${trendStyle.color}`}>
          <TrendIcon
            trend={props.trend}
            className={`w-3.5 h-3.5 ${trendStyle.color}`}
          />
          <span className="text-xs font-medium">{props.trendLabel}</span>
        </div>
      )}
    </div>
  );
}

function ChartCard({
  title,
  description,
  footer,
  children,
}: {
  title?: string;
  description?: string;
  footer?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="bg-zinc-800 border-none shadow-none w-full min-w-fit max-w-lg">
      {(title || description) && (
        <CardHeader className="pb-0 flex-col items-start">
          {title && (
            <p className="text-sm font-semibold text-zinc-100">{title}</p>
          )}
          {description && (
            <p className="text-xs text-zinc-400">{description}</p>
          )}
        </CardHeader>
      )}
      <CardBody>{children}</CardBody>
      {footer && (
        <CardFooter>
          <p className="text-xs text-zinc-500">{footer}</p>
        </CardFooter>
      )}
    </Card>
  );
}

export function BarChartView(props: z.infer<typeof barChartSchema>) {
  const color = props.color ?? CHART_COLORS[0];
  const chartConfig: ChartConfig = {
    [props.yKey]: { label: props.yKey, color },
  };
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[200px] w-full">
        <RechartsBarChart data={props.data}>
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip
            cursor={false}
            content={<ChartTooltipContent hideLabel />}
          />
          <Bar
            dataKey={props.yKey}
            fill={`var(--color-${props.yKey})`}
            radius={8}
          />
        </RechartsBarChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function LineChartView(props: z.infer<typeof lineChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    props.yKeys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[200px] w-full">
        <RechartsLineChart data={props.data}>
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          {props.yKeys.map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </RechartsLineChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function AreaChartView(props: z.infer<typeof areaChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    props.yKeys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[200px] w-full">
        <RechartsAreaChart data={props.data}>
          <defs>
            {props.yKeys.map((key) => (
              <linearGradient
                key={key}
                id={`gradient-${key}`}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="0%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.4}
                />
                <stop
                  offset="95%"
                  stopColor={`var(--color-${key})`}
                  stopOpacity={0.05}
                />
              </linearGradient>
            ))}
          </defs>
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          {props.yKeys.map((key) => (
            <Area
              key={key}
              type="natural"
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              fill={`url(#gradient-${key})`}
            />
          ))}
        </RechartsAreaChart>
      </ChartContainer>
    </ChartCard>
  );
}

const PIE_COLORS = ["#00bbff", "#34d399", "#60a5fa", "#a78bfa", "#f472b6"];

export function PieChartView(props: z.infer<typeof pieChartSchema>) {
  const chartConfig: ChartConfig = Object.fromEntries(
    props.data.map((entry, i) => {
      const name = String(entry[props.nameKey] ?? i);
      return [name, { label: name, color: PIE_COLORS[i % PIE_COLORS.length] }];
    }),
  );
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[200px] w-full">
        <RechartsPieChart>
          <Pie
            data={props.data}
            dataKey={props.valueKey}
            nameKey={props.nameKey}
            cx="50%"
            cy="50%"
            outerRadius={70}
            innerRadius={40}
            strokeWidth={0}
          >
            {props.data.map((_entry, i) => (
              <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
          <ChartTooltip
            content={<ChartTooltipContent nameKey={props.nameKey} />}
          />
          <ChartLegend
            content={<ChartLegendContent nameKey={props.nameKey} />}
          />
        </RechartsPieChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function ScatterChartView(props: z.infer<typeof scatterChartSchema>) {
  const chartConfig: ChartConfig = {
    scatter: { label: "Data", color: CHART_COLORS[0] },
  };
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[200px] w-full">
        <RechartsScatterChart>
          <XAxis
            dataKey={props.xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <YAxis
            dataKey={props.yKey}
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Scatter data={props.data} fill="var(--color-scatter)" />
        </RechartsScatterChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function RadarChartView(props: z.infer<typeof radarChartSchema>) {
  const colors = props.colors ?? CHART_COLORS;
  const chartConfig: ChartConfig = Object.fromEntries(
    props.valueKeys.map((key, i) => [
      key,
      { label: key, color: colors[i % colors.length] },
    ]),
  );
  return (
    <ChartCard
      title={props.title}
      description={props.description}
      footer={props.footer}
    >
      <ChartContainer config={chartConfig} className="h-[220px] w-full">
        <RechartsRadarChart data={props.data}>
          <PolarGrid stroke="#3f3f46" />
          <PolarAngleAxis
            dataKey={props.angleKey}
            tick={{ fill: "#71717a", fontSize: 11 }}
          />
          <ChartTooltip content={<ChartTooltipContent />} />
          {props.valueKeys.map((key) => (
            <Radar
              key={key}
              dataKey={key}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              fill={`var(--color-${key})`}
              fillOpacity={0.2}
            />
          ))}
          <ChartLegend content={<ChartLegendContent />} />
        </RechartsRadarChart>
      </ChartContainer>
    </ChartCard>
  );
}

export function GaugeChartView(props: z.infer<typeof gaugeChartSchema>) {
  const min = props.min ?? 0;
  const max = props.max ?? 100;
  const pct = Math.min(
    100,
    Math.max(0, ((props.value - min) / (max - min)) * 100),
  );
  const warning = props.thresholds?.warning ?? 60;
  const danger = props.thresholds?.danger ?? 80;
  const color =
    pct >= danger ? "#f87171" : pct >= warning ? "#fbbf24" : "#34d399";

  const chartConfig: ChartConfig = {
    value: { label: props.title ?? "Value", color },
  };
  const data = [{ name: "value", value: pct, fill: color }];

  return (
    <div
      className="rounded-2xl bg-zinc-800 p-4 text-center"
      style={{ width: 180 }}
    >
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </p>
      )}
      <ChartContainer
        config={chartConfig}
        className="mx-auto h-[120px] w-[150px]"
      >
        <RadialBarChart
          innerRadius={45}
          outerRadius={65}
          data={data}
          startAngle={180}
          endAngle={180 - (pct / 100) * 180}
          barSize={10}
        >
          <RadialBar
            dataKey="value"
            background={{ fill: "#27272a" }}
            cornerRadius={10}
          />
        </RadialBarChart>
      </ChartContainer>
      <div className="-mt-10">
        <span className="text-2xl font-semibold leading-none" style={{ color }}>
          {props.value}
        </span>
        {props.unit && (
          <span className="text-xs text-zinc-500 ml-0.5">{props.unit}</span>
        )}
      </div>
    </div>
  );
}

// ---- Content ----

export function ImageBlockView(props: z.infer<typeof imageBlockSchema>) {
  return (
    <div className="rounded-2xl overflow-hidden">
      <img
        src={props.src}
        alt={props.alt ?? ""}
        className="w-full object-cover max-h-96"
      />
      {props.caption && (
        <p className="text-xs text-zinc-500 mt-2 text-center">
          {props.caption}
        </p>
      )}
    </div>
  );
}

function GalleryImage({
  img,
}: {
  img: { src: string; alt?: string; caption?: string };
}) {
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="relative overflow-hidden rounded-xl cursor-pointer"
      style={{ aspectRatio: "3/2" }}
    >
      <img
        src={img.src}
        alt={img.alt ?? ""}
        className="w-full h-full object-cover"
      />
      {img.caption && (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2 pointer-events-none">
          <p className="text-xs text-white/90 font-medium leading-snug">
            {img.caption}
          </p>
        </div>
      )}
    </motion.div>
  );
}

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  const images = props.images;
  const count = images.length;

  if (count === 1) {
    return <GalleryImage img={images[0]} />;
  }

  if (count === 2) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        {images.map((img, i) => (
          <GalleryImage key={i} img={img} />
        ))}
      </div>
    );
  }

  if (count === 3) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        <GalleryImage img={images[0]} />
        <GalleryImage img={images[1]} />
        <div className="col-span-2">
          <GalleryImage img={images[2]} />
        </div>
      </div>
    );
  }

  if (count === 4) {
    return (
      <div className="grid grid-cols-2 gap-1.5">
        {images.map((img, i) => (
          <GalleryImage key={i} img={img} />
        ))}
      </div>
    );
  }

  // 5+ images: first row of 3, remaining in second row
  const topRow = images.slice(0, 3);
  const bottomRow = images.slice(3);

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-1.5">
        {topRow.map((img, i) => (
          <GalleryImage key={i} img={img} />
        ))}
      </div>
      {bottomRow.length > 0 && (
        <div
          className={`grid grid-cols-${Math.min(bottomRow.length, 3)} gap-1.5`}
        >
          {bottomRow.map((img, i) => (
            <GalleryImage key={i} img={img} />
          ))}
        </div>
      )}
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
    <div className="w-full min-w-fit max-w-xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      {isEmbed ? (
        <iframe
          src={embedSrc}
          className="w-full rounded-2xl aspect-video"
          style={{ border: "none" }}
          allowFullScreen
          title={props.title ?? "video"}
        />
      ) : (
        <video
          src={src}
          poster={props.poster}
          controls
          className="w-full rounded-2xl aspect-video object-cover"
        />
      )}
    </div>
  );
}

export function AudioPlayerView(props: z.infer<typeof audioPlayerSchema>) {
  return (
    <div className="w-full min-w-fit max-w-xl">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-1">
          {props.title}
        </p>
      )}
      {props.description && (
        <p className="text-xs text-zinc-400 mb-3">{props.description}</p>
      )}
      <audio src={props.src} controls className="w-full mt-2" />
    </div>
  );
}

export function MapBlockView(props: z.infer<typeof mapBlockSchema>) {
  const { lat, lng } = props;
  const bbox = `${lng - 0.01},${lat - 0.01},${lng + 0.01},${lat + 0.01}`;
  const src = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lng}`;
  return (
    <div>
      {props.label && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.label}
        </p>
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

const CALENDAR_DOT_COLOR: Record<string, string> = {
  success: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
  default: "#a1a1aa",
};

function dateStrToCalendarDate(dateStr: string): CalendarDate {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new CalendarDate(y, m, d);
}

export function CalendarMiniView(props: z.infer<typeof calendarMiniSchema>) {
  const markedSet = new Set(props.markedDates.map((d) => d.date));
  const today = new Date();
  const firstDate =
    props.markedDates.length > 0
      ? dateStrToCalendarDate(props.markedDates[0].date)
      : new CalendarDate(
          today.getFullYear(),
          today.getMonth() + 1,
          today.getDate(),
        );

  return (
    <div>
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <Calendar
        isReadOnly
        defaultValue={firstDate as unknown as DateValue}
        topContent={null}
        bottomContent={null}
        isDateUnavailable={(date: DateValue) => {
          const str = `${date.year}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
          return !markedSet.has(str);
        }}
      />
      {props.markedDates.some((d) => d.label) && (
        <div className="mt-2 space-y-1">
          {props.markedDates
            .filter((d) => d.label)
            .map((d, i) => (
              <div key={i} className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{
                    backgroundColor: CALENDAR_DOT_COLOR[d.color ?? "default"],
                  }}
                />
                <span className="text-xs text-zinc-300">{d.label}</span>
                <span className="text-xs text-zinc-500 ml-auto">{d.date}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

export function NumberTickerView(props: z.infer<typeof numberTickerSchema>) {
  const isDecimal = props.value % 1 !== 0;
  return (
    <div className="py-1 text-center">
      {props.label && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.label}
        </p>
      )}
      <div className="flex items-end justify-center gap-1">
        <span className="text-3xl font-semibold text-zinc-100">
          <NumberTicker value={props.value} decimalPlaces={isDecimal ? 1 : 0} />
        </span>
        {props.unit && (
          <span className="text-sm text-zinc-500 mb-0.5">{props.unit}</span>
        )}
      </div>
    </div>
  );
}

function CarouselDotIndicators() {
  const { selectedIndex, scrollSnaps, scrollTo } = useCarousel();
  if (scrollSnaps.length <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-1.5">
      {scrollSnaps.map((_, index) => (
        <button
          key={index}
          type="button"
          aria-label={`Go to slide ${index + 1}`}
          onClick={() => scrollTo(index)}
          className={[
            "rounded-full transition-all duration-200",
            index === selectedIndex
              ? "w-2 h-2 bg-zinc-300"
              : "w-1.5 h-1.5 bg-zinc-600 hover:bg-zinc-500",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

export function CarouselView(props: z.infer<typeof carouselSchema>) {
  const handleAction = (value: string) => {
    window.dispatchEvent(
      new CustomEvent("openui:action", {
        detail: { type: "continue_conversation", value },
      }),
    );
  };

  const total = props.items.length;

  return (
    <div>
      <Carousel opts={{ align: "start", loop: true }}>
        <CarouselContent className="-ml-0">
          {props.items.map((item, i) => (
            <CarouselItem key={i} className="pl-0 h-full">
              <div className="rounded-2xl bg-zinc-800 p-4 min-h-full flex flex-col">
                {item.image && (
                  <img
                    src={item.image}
                    alt={item.title}
                    className="w-full rounded-2xl object-cover h-40 mb-3"
                  />
                )}
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold text-zinc-100">
                    {item.title}
                  </p>
                  {item.badge && (
                    <Chip
                      size="sm"
                      variant="flat"
                      className="shrink-0 text-xs text-zinc-400"
                    >
                      {item.badge}
                    </Chip>
                  )}
                </div>
                {item.body && (
                  <p className="text-xs text-zinc-400 mt-1 flex-1">
                    {item.body}
                  </p>
                )}
                {item.actions && item.actions.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-auto pt-3">
                    {item.actions.map((action, j) => (
                      <Button
                        key={j}
                        size="sm"
                        variant="flat"
                        onPress={() => handleAction(action.value)}
                      >
                        {action.label}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            </CarouselItem>
          ))}
        </CarouselContent>
        {total > 1 && (
          <div className="flex items-center justify-between mt-3 px-1">
            <CarouselPrevious className="rounded-full bg-zinc-800 hover:bg-zinc-700 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronLeft className="w-4 h-4 text-zinc-300" />
            </CarouselPrevious>
            <CarouselDotIndicators />
            <CarouselNext className="rounded-full bg-zinc-800 hover:bg-zinc-700 border-none p-1.5 disabled:opacity-40 transition-colors cursor-pointer">
              <ChevronRight className="w-4 h-4 text-zinc-300" />
            </CarouselNext>
          </div>
        )}
      </Carousel>
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
    <div>
      <div
        className="flex items-start gap-1.5 py-1 cursor-pointer select-none"
        style={{ paddingLeft: `${depth * 16}px` }}
        onClick={() => hasChildren && setExpanded((e) => !e)}
      >
        <span className="mt-0.5 w-3.5 h-3.5 shrink-0 flex items-center justify-center">
          {hasChildren ? (
            <span className="cursor-pointer">
              {expanded ? (
                <ArrowDown01Icon className="w-3 h-3 text-zinc-400" />
              ) : (
                <ArrowRight01Icon className="w-3 h-3 text-zinc-500" />
              )}
            </span>
          ) : (
            <span className="w-1.5 h-1.5 rounded-full bg-zinc-700 inline-block mt-0.5" />
          )}
        </span>
        <div className="flex-1 min-w-0">
          <span
            className={
              hasChildren
                ? "text-sm font-medium text-zinc-300"
                : "text-sm text-zinc-400"
            }
          >
            {node.label}
          </span>
          {node.description && (
            <span className="text-xs text-zinc-600 ml-2">
              {node.description}
            </span>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div className="ml-3 border-l border-zinc-800 pl-1">
          {node.children?.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child as TreeNode}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function TreeViewView(props: z.infer<typeof treeViewSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
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

function formatTimelineTime(raw: string): string {
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function TimelineView(props: z.infer<typeof timelineSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-0">
        {props.items.map((item, i) => {
          const dotColor = TIMELINE_DOT[item.status ?? "neutral"];
          const isLast = i === props.items.length - 1;
          return (
            <div key={i} className="flex gap-3">
              {/* Time column */}
              <div className="w-16 shrink-0 pt-0.5 text-right">
                <span className="text-[10px] text-zinc-600 leading-tight">
                  {formatTimelineTime(item.time)}
                </span>
              </div>
              {/* Dot + line */}
              <div className="flex flex-col items-center">
                <span
                  className={`h-2 w-2 rounded-full shrink-0 mt-1.5 ${dotColor}`}
                />
                {!isLast && <div className="w-px flex-1 my-1 bg-zinc-700" />}
              </div>
              {/* Content */}
              <div className="pb-4 flex-1 min-w-0">
                <p className="text-sm font-medium text-zinc-200">
                  {item.title}
                </p>
                {item.description && (
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {item.description}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ALERT_STYLES: Record<
  string,
  { bg: string; text: string; accent: string; border: string }
> = {
  info: {
    bg: "bg-blue-400/5",
    text: "text-blue-400",
    accent: "text-blue-300",
    border: "border-l-4 border-blue-400",
  },
  success: {
    bg: "bg-emerald-400/5",
    text: "text-emerald-400",
    accent: "text-emerald-300",
    border: "border-l-4 border-emerald-400",
  },
  warning: {
    bg: "bg-amber-400/5",
    text: "text-amber-400",
    accent: "text-amber-300",
    border: "border-l-4 border-amber-400",
  },
  error: {
    bg: "bg-red-400/5",
    text: "text-red-400",
    accent: "text-red-300",
    border: "border-l-4 border-red-400",
  },
};

export function AlertBannerView(props: z.infer<typeof alertBannerSchema>) {
  const style = ALERT_STYLES[props.variant] ?? ALERT_STYLES.info;
  return (
    <div
      className={`rounded-r-2xl rounded-l-sm px-4 py-3 w-full min-w-fit max-w-xl ${style.bg} ${style.border}`}
    >
      <p className={`text-sm font-semibold ${style.text}`}>{props.title}</p>
      {props.description && (
        <p className={`text-xs mt-1 ${style.accent}`}>{props.description}</p>
      )}
    </div>
  );
}

function StepDot({
  status,
  index,
}: {
  status: "complete" | "active" | "pending";
  index: number;
}) {
  if (status === "complete") {
    return (
      <span className="flex items-center justify-center h-5 w-5 shrink-0 rounded-full bg-emerald-400/15 relative top-1">
        <CheckmarkCircle01Icon className="w-4 h-4 text-emerald-400" />
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="relative flex h-5 w-5 shrink-0 items-center justify-center top-1">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-30" />
        <span className="relative flex h-5 w-5 rounded-full bg-primary/20 items-center justify-center">
          <span className="h-2 w-2 rounded-full bg-primary" />
        </span>
      </span>
    );
  }
  return (
    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-zinc-700 relative top-1">
      <span className="text-xs font-medium text-zinc-500">{index + 1}</span>
    </span>
  );
}

export function StepsView(props: z.infer<typeof stepsSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full max-w-sm">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-3">
          {props.title}
        </p>
      )}
      <div className="space-y-2">
        {props.items.map((item, i) => {
          const status = (item.status ?? "pending") as
            | "complete"
            | "active"
            | "pending";
          const isActive = status === "active";
          const isComplete = status === "complete";
          return (
            <div
              key={i}
              className={`rounded-2xl p-3 flex items-start gap-3 ${
                isActive
                  ? "bg-primary/10 border-1 border-primary/50"
                  : "bg-zinc-900"
              }`}
            >
              <StepDot status={status} index={i} />
              <div className="flex-1 min-w-0 pt-0.5">
                <p
                  className={`text-sm font-medium ${
                    isActive
                      ? "text-zinc-100"
                      : isComplete
                        ? "text-zinc-300"
                        : "text-zinc-500"
                  }`}
                >
                  {item.title}
                </p>
                {item.description && (
                  <p
                    className={`text-xs  ${isActive ? "text-zinc-300" : "text-zinc-500 "} mt-0.5`}
                  >
                    {item.description}
                  </p>
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

const stackDef = defineComponent({
  name: "Stack",
  description: "Vertical stack of multiple components.",
  props: stackSchema,
  component: ({ props, renderNode }) => (
    <div className="flex flex-col gap-3">
      {(props.items as unknown[]).map((item, i) => (
        <React.Fragment key={i}>{renderNode(item)}</React.Fragment>
      ))}
    </div>
  ),
});

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

const statRowDef = defineComponent({
  name: "StatRow",
  description: "Single KPI with optional trend.",
  props: statRowSchema,
  component: ({ props }) => React.createElement(StatRowView, props),
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
    stackDef,
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
    selectableListDef,
    avatarListDef,
    kbdBlockDef,
    statRowDef,
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
    mapBlockDef,
    calendarMiniDef,
    numberTickerDef,
    carouselDef,
    treeViewDef,
    timelineDef,
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
        "StatRow",
        "BarChart",
        "LineChart",
        "AreaChart",
        "PieChart",
        "ScatterChart",
        "RadarChart",
        "GaugeChart",
      ],
      notes: [
        "StatRow for single KPI",
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
      components: ["Timeline", "AlertBanner", "Steps"],
      notes: [
        "Timeline for event sequences",
        "AlertBanner for inline notices",
        "Steps for ordered instructions",
      ],
    },
  ],
});
