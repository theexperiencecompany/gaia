import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import type { z } from "zod";
import { sanitizeRedirectUrl } from "@/lib/url-safety";
import { useSafeTriggerAction } from "../hooks/useSafeTriggerAction";
import { ToolCard } from "../primitives";
import { timelineSchema } from "../promptSpecs";

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

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

export function TimelineView(props: z.infer<typeof timelineSchema>) {
  const triggerAction = useSafeTriggerAction();

  return (
    <ToolCard size="standard" title={props.title}>
      <div className="relative">
        <div className="absolute left-[5px] top-3 bottom-3 w-px bg-zinc-700/50" />
        <div className="space-y-0">
          {props.items.map((item, i) => {
            const st = TIMELINE_STATUS[item.status ?? "neutral"];
            const isLast = i === props.items.length - 1;
            const hasExtra =
              item.actor ||
              (item.links && item.links.length > 0) ||
              (item.actions && item.actions.length > 0);
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
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-zinc-100 leading-tight">
                        {item.title}
                      </p>
                      {item.actor && (
                        <p className="text-xs text-zinc-500 mt-0.5">
                          {item.actor}
                        </p>
                      )}
                    </div>
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
                  {hasExtra && (
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      {item.links?.map((link) => {
                        const safeHref = sanitizeRedirectUrl(String(link.url));
                        const linkClassName =
                          link.type === "primary"
                            ? "text-xs text-[#00bbff]"
                            : "text-xs text-zinc-400";
                        return safeHref ? (
                          <Link
                            key={`${item.title}-${link.label}-${link.url}`}
                            href={safeHref}
                            isExternal
                            className={linkClassName}
                          >
                            {link.label}
                          </Link>
                        ) : (
                          <span
                            key={`${item.title}-${link.label}-${link.url}`}
                            className={linkClassName}
                          >
                            {link.label}
                          </span>
                        );
                      })}
                      {item.actions?.map((action) => (
                        <Button
                          key={`${item.title}-${action.value}`}
                          size="sm"
                          variant="flat"
                          onPress={() => triggerAction(action.value)}
                        >
                          {action.label}
                        </Button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </ToolCard>
  );
}

// ---------------------------------------------------------------------------
// Component definitions
// ---------------------------------------------------------------------------

export const timelineDef = defineComponent({
  name: "Timeline",
  description:
    "Chronological event feed with timestamps, status dots, optional actor, links, and actions.",
  props: timelineSchema,
  component: ({ props }) => React.createElement(TimelineView, props),
});
