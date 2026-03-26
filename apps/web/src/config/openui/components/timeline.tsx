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

const TIMELINE_DOT: Record<string, string> = {
  success: "bg-emerald-400",
  error: "bg-red-400",
  warning: "bg-amber-400",
  neutral: "bg-zinc-500",
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

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

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
              <div className="w-16 shrink-0 pt-0.5 text-right">
                <span className="text-[10px] text-zinc-600 leading-tight">
                  {formatTimelineTime(item.time)}
                </span>
              </div>
              <div className="flex flex-col items-center">
                <span
                  className={`h-2 w-2 rounded-full shrink-0 mt-1.5 ${dotColor}`}
                />
                {!isLast && <div className="w-px flex-1 my-1 bg-zinc-700" />}
              </div>
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
