import { CheckmarkCircle01Icon } from "@icons";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

export const timelineSchema = z.object({
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

export const alertBannerSchema = z.object({
  variant: z.enum(["info", "success", "warning", "error"]),
  title: z.string(),
  description: z.string().optional(),
});

export const stepsSchema = z.object({
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
// Helpers
// ---------------------------------------------------------------------------

const TIMELINE_STATUS: Record<
  string,
  { dot: string; ring: string; label: string; labelColor: string }
> = {
  success: {
    dot: "bg-emerald-400",
    ring: "ring-emerald-400/25",
    label: "Success",
    labelColor: "text-emerald-400 bg-emerald-400/10",
  },
  error: {
    dot: "bg-red-400",
    ring: "ring-red-400/25",
    label: "Failed",
    labelColor: "text-red-400 bg-red-400/10",
  },
  warning: {
    dot: "bg-amber-400",
    ring: "ring-amber-400/25",
    label: "Warning",
    labelColor: "text-amber-400 bg-amber-400/10",
  },
  neutral: {
    dot: "bg-zinc-500",
    ring: "ring-zinc-500/20",
    label: "",
    labelColor: "",
  },
};

const ALERT_STYLES: Record<
  string,
  { inner: string; text: string; accent: string }
> = {
  info: {
    inner: "bg-blue-400/10",
    text: "text-blue-400",
    accent: "text-blue-300",
  },
  success: {
    inner: "bg-emerald-400/10",
    text: "text-emerald-400",
    accent: "text-emerald-300",
  },
  warning: {
    inner: "bg-amber-400/10",
    text: "text-amber-400",
    accent: "text-amber-300",
  },
  error: {
    inner: "bg-red-400/10",
    text: "text-red-400",
    accent: "text-red-300",
  },
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

function StepDot({
  status,
  index,
  dimmed,
}: {
  status: "complete" | "active" | "pending";
  index: number;
  dimmed: boolean;
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
    <span
      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full relative top-1 ${
        dimmed ? "bg-zinc-700" : "bg-zinc-600"
      }`}
    >
      <span
        className={`text-xs font-medium ${dimmed ? "text-zinc-500" : "text-zinc-300"}`}
      >
        {index + 1}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function TimelineView(props: z.infer<typeof timelineSchema>) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full max-w-lg">
      {props.title && (
        <p className="text-sm font-semibold text-zinc-100 mb-4">
          {props.title}
        </p>
      )}
      <div className="relative">
        {/* Continuous connector line */}
        <div className="absolute left-[5px] top-3 bottom-3 w-px bg-zinc-700/50" />
        <div className="space-y-0">
          {props.items.map((item, i) => {
            const st = TIMELINE_STATUS[item.status ?? "neutral"];
            const isLast = i === props.items.length - 1;
            return (
              <div
                key={`${item.time}-${item.title}`}
                className={`flex gap-4 relative ${!isLast ? "pb-5" : ""}`}
              >
                {/* Dot */}
                <span
                  className={`h-2.5 w-2.5 rounded-full shrink-0 mt-1.5 z-10 ring-4 ring-offset-0 ${st.dot} ${st.ring}`}
                />
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-zinc-100 leading-tight">
                      {item.title}
                    </p>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {item.status && item.status !== "neutral" && (
                        <span
                          className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${st.labelColor}`}
                        >
                          {st.label}
                        </span>
                      )}
                      <span className="text-[11px] text-zinc-500 tabular-nums">
                        {formatTimelineTime(item.time)}
                      </span>
                    </div>
                  </div>
                  {item.description && (
                    <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                      {item.description}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function AlertBannerView(props: z.infer<typeof alertBannerSchema>) {
  const style = ALERT_STYLES[props.variant] ?? ALERT_STYLES.info;
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full min-w-fit max-w-xl">
      <div className={`rounded-xl ${style.inner} p-3`}>
        <p className={`text-sm font-semibold ${style.text}`}>{props.title}</p>
        {props.description && (
          <p className={`text-xs mt-1 ${style.accent}`}>{props.description}</p>
        )}
      </div>
    </div>
  );
}

export function StepsView(props: z.infer<typeof stepsSchema>) {
  const hasActiveItem = props.items.some((item) => item.status === "active");
  const activeIndex = props.items.findIndex((item) => item.status === "active");

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
          // When no active item exists, pending items look normal (not dimmed).
          // When an active item exists, only items after it look dimmed.
          const isDimmed =
            status === "pending" && hasActiveItem && i > activeIndex;

          return (
            <div
              key={item.title}
              className={`rounded-2xl p-3 flex items-start gap-3 ${
                isActive
                  ? "bg-primary/10 border-1 border-primary/50"
                  : "bg-zinc-900"
              }`}
            >
              <StepDot status={status} index={i} dimmed={isDimmed} />
              <div className="flex-1 min-w-0 pt-0.5">
                <p
                  className={`text-sm font-medium ${
                    isActive
                      ? "text-zinc-100"
                      : isDimmed
                        ? "text-zinc-500"
                        : "text-zinc-200"
                  }`}
                >
                  {item.title}
                </p>
                {item.description && (
                  <p
                    className={`text-xs mt-0.5 ${isDimmed ? "text-zinc-600" : "text-zinc-400"}`}
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
// Component definitions
// ---------------------------------------------------------------------------

export const timelineDef = defineComponent({
  name: "Timeline",
  description: "Ordered sequence of events with timestamps.",
  props: timelineSchema,
  component: ({ props }) => React.createElement(TimelineView, props),
});

export const alertBannerDef = defineComponent({
  name: "AlertBanner",
  description: "Inline alert notice with variant styling.",
  props: alertBannerSchema,
  component: ({ props }) => React.createElement(AlertBannerView, props),
});

export const stepsDef = defineComponent({
  name: "Steps",
  description: "Ordered step sequence with completion status.",
  props: stepsSchema,
  component: ({ props }) => React.createElement(StepsView, props),
});
