import { defineComponent } from "@openuidev/react-lang";
import React from "react";
import { View } from "react-native";
import { z } from "zod";
import {
  Alert01Icon,
  AppIcon,
  CheckmarkCircle01Icon,
  InformationCircleIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { Card, SectionTitle } from "./primitives";

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

type TimelineStatus = "success" | "error" | "warning" | "neutral";
type StepStatus = "complete" | "active" | "pending";
type AlertVariant = "info" | "success" | "warning" | "error";

const TIMELINE_DOT_COLOR: Record<TimelineStatus, string> = {
  success: "#34d399",
  error: "#f87171",
  warning: "#fbbf24",
  neutral: "#a1a1aa",
};

const TIMELINE_HALO_COLOR: Record<TimelineStatus, string> = {
  success: "rgba(52, 211, 153, 0.25)",
  error: "rgba(248, 113, 113, 0.25)",
  warning: "rgba(251, 191, 36, 0.25)",
  neutral: "rgba(161, 161, 170, 0.25)",
};

const TIMELINE_LABEL: Record<TimelineStatus, string> = {
  success: "Success",
  error: "Failed",
  warning: "Warning",
  neutral: "",
};

const TIMELINE_LABEL_BG: Record<TimelineStatus, string> = {
  success: "bg-emerald-400/10",
  error: "bg-red-400/10",
  warning: "bg-amber-400/10",
  neutral: "",
};

const TIMELINE_LABEL_TEXT: Record<TimelineStatus, string> = {
  success: "text-emerald-400",
  error: "text-red-400",
  warning: "text-amber-400",
  neutral: "",
};

const ALERT_INNER_BG: Record<AlertVariant, string> = {
  info: "bg-blue-400/10",
  success: "bg-emerald-400/10",
  warning: "bg-amber-400/10",
  error: "bg-red-400/10",
};

const ALERT_TEXT: Record<AlertVariant, string> = {
  info: "text-blue-400",
  success: "text-emerald-400",
  warning: "text-amber-400",
  error: "text-red-400",
};

const ALERT_ACCENT: Record<AlertVariant, string> = {
  info: "text-blue-300",
  success: "text-emerald-300",
  warning: "text-amber-300",
  error: "text-red-300",
};

const ALERT_ICON_COLOR: Record<AlertVariant, string> = {
  info: "#60a5fa",
  success: "#34d399",
  warning: "#fbbf24",
  error: "#f87171",
};

const PRIMARY_COLOR = "#00bbff";
const GUTTER_COLOR = "#27272a";

// Timeline dimensions
const DOT_SIZE = 10;
const HALO_SIZE = 18;
const TIMELINE_LEFT_COLUMN_WIDTH = 32;
// Timeline gutter line sits at x = 15 (per spec), 2px wide.
const TIMELINE_GUTTER_LEFT = 15;
const TIMELINE_GUTTER_WIDTH = 2;
// Dot centre aligns at ~16 from top of each row.
const DOT_CENTER_Y = 16;

// Step dimensions
const STEP_BADGE_SIZE = 32;

function getAlertIcon(variant: AlertVariant) {
  switch (variant) {
    case "success":
      return CheckmarkCircle01Icon;
    case "warning":
      return Alert01Icon;
    case "error":
      return Alert01Icon;
    default:
      return InformationCircleIcon;
  }
}

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

interface TimelineDotProps {
  status: TimelineStatus;
}

function TimelineDot({ status }: TimelineDotProps) {
  const dotColor = TIMELINE_DOT_COLOR[status];
  const haloColor = TIMELINE_HALO_COLOR[status];

  return (
    <View
      style={{
        width: TIMELINE_LEFT_COLUMN_WIDTH,
        height: HALO_SIZE,
        alignItems: "center",
        justifyContent: "center",
        marginTop: DOT_CENTER_Y - HALO_SIZE / 2,
      }}
    >
      <View
        style={{
          position: "absolute",
          width: HALO_SIZE,
          height: HALO_SIZE,
          borderRadius: HALO_SIZE / 2,
          backgroundColor: haloColor,
        }}
      />
      <View
        style={{
          width: DOT_SIZE,
          height: DOT_SIZE,
          borderRadius: DOT_SIZE / 2,
          backgroundColor: dotColor,
        }}
      />
    </View>
  );
}

interface StepDotProps {
  status: StepStatus;
  index: number;
}

function StepDot({ status, index }: StepDotProps) {
  if (status === "complete") {
    return (
      <View
        style={{
          width: STEP_BADGE_SIZE,
          height: STEP_BADGE_SIZE,
          borderRadius: STEP_BADGE_SIZE / 2,
          backgroundColor: "rgba(52, 211, 153, 0.1)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={CheckmarkCircle01Icon} size={18} color="#34d399" />
      </View>
    );
  }

  if (status === "active") {
    return (
      <View
        style={{
          width: STEP_BADGE_SIZE,
          height: STEP_BADGE_SIZE,
          borderRadius: STEP_BADGE_SIZE / 2,
          backgroundColor: PRIMARY_COLOR,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text className="text-sm font-semibold text-zinc-900">{index + 1}</Text>
      </View>
    );
  }

  return (
    <View
      style={{
        width: STEP_BADGE_SIZE,
        height: STEP_BADGE_SIZE,
        borderRadius: STEP_BADGE_SIZE / 2,
        backgroundColor: GUTTER_COLOR,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Text className="text-sm font-medium text-zinc-500">{index + 1}</Text>
    </View>
  );
}

export function TimelineView(props: z.infer<typeof timelineSchema>) {
  const items = props.items;

  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View style={{ position: "relative" }}>
        {/* Gutter line 2px wide at left: 15, starts at first dot centre,
            stops at last dot centre. */}
        {items.length > 1 ? (
          <View
            style={{
              position: "absolute",
              left: TIMELINE_GUTTER_LEFT,
              top: DOT_CENTER_Y,
              bottom: DOT_CENTER_Y,
              width: TIMELINE_GUTTER_WIDTH,
              backgroundColor: GUTTER_COLOR,
            }}
          />
        ) : null}
        <View>
          {items.map((item, i) => {
            const status = (item.status ?? "neutral") as TimelineStatus;
            const isLast = i === items.length - 1;
            const label = TIMELINE_LABEL[status];
            const labelBg = TIMELINE_LABEL_BG[status];
            const labelText = TIMELINE_LABEL_TEXT[status];
            const showChip = status !== "neutral" && label !== "";

            return (
              <View
                key={`${item.time}-${item.title}`}
                style={{
                  flexDirection: "row",
                  gap: 12,
                  paddingBottom: isLast ? 0 : 16,
                  position: "relative",
                }}
              >
                <TimelineDot status={status} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text className="text-xs text-zinc-500">
                    {formatTimelineTime(item.time)}
                  </Text>
                  {showChip ? (
                    <View
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 8,
                        marginTop: 2,
                      }}
                    >
                      <Text className="text-sm font-medium text-zinc-200 flex-1">
                        {item.title}
                      </Text>
                      <View className={`rounded-full px-2 py-0.5 ${labelBg}`}>
                        <Text className={`text-xs font-medium ${labelText}`}>
                          {label}
                        </Text>
                      </View>
                    </View>
                  ) : (
                    <Text
                      className="text-sm font-medium text-zinc-200"
                      style={{ marginTop: 2 }}
                    >
                      {item.title}
                    </Text>
                  )}
                  {item.description ? (
                    <Text
                      className="text-xs text-zinc-400"
                      style={{ marginTop: 4 }}
                    >
                      {item.description}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      </View>
    </Card>
  );
}

export function AlertBannerView(props: z.infer<typeof alertBannerSchema>) {
  const variant = props.variant;
  const innerBg = ALERT_INNER_BG[variant];
  const textClass = ALERT_TEXT[variant];
  const accentClass = ALERT_ACCENT[variant];
  const iconColor = ALERT_ICON_COLOR[variant];
  const icon = getAlertIcon(variant);

  return (
    <View
      className={`w-full rounded-2xl p-3 ${innerBg}`}
      style={{ flexDirection: "row", alignItems: "flex-start", gap: 12 }}
    >
      <AppIcon icon={icon} size={20} color={iconColor} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text className={`text-sm font-medium ${textClass}`}>
          {props.title}
        </Text>
        {props.description ? (
          <Text className={`text-xs ${accentClass}`} style={{ marginTop: 2 }}>
            {props.description}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const STEP_CONNECTOR_COLOR = {
  default: GUTTER_COLOR,
  complete: "#34d399",
  active: PRIMARY_COLOR,
} as const;

export function StepsView(props: z.infer<typeof stepsSchema>) {
  const items = props.items;

  return (
    <Card>
      {props.title ? <SectionTitle>{props.title}</SectionTitle> : null}
      <View>
        {items.map((item, i) => {
          const status = (item.status ?? "pending") as StepStatus;
          const isLast = i === items.length - 1;

          // Trailing connector colour mirrors the status of the current step.
          let connectorColor: string = STEP_CONNECTOR_COLOR.default;
          if (status === "complete") {
            connectorColor = STEP_CONNECTOR_COLOR.complete;
          } else if (status === "active") {
            connectorColor = STEP_CONNECTOR_COLOR.active;
          }

          const titleColor =
            status === "pending" ? "text-zinc-500" : "text-zinc-100";
          const descriptionColor =
            status === "pending" ? "text-zinc-500" : "text-zinc-400";

          return (
            <View
              key={item.title}
              style={{
                flexDirection: "row",
                alignItems: "flex-start",
                gap: 12,
                paddingBottom: isLast ? 0 : 12,
                position: "relative",
              }}
            >
              {/* 2px vertical connector from bottom of this badge to top of
                  the next badge. */}
              {!isLast ? (
                <View
                  style={{
                    position: "absolute",
                    left: STEP_BADGE_SIZE / 2 - 1,
                    top: STEP_BADGE_SIZE,
                    bottom: 0,
                    width: 2,
                    backgroundColor: connectorColor,
                  }}
                />
              ) : null}
              <StepDot status={status} index={i} />
              <View style={{ flex: 1, minWidth: 0, paddingTop: 4 }}>
                <Text className={`text-sm font-medium ${titleColor}`}>
                  {item.title}
                </Text>
                {item.description ? (
                  <Text
                    className={`text-xs ${descriptionColor}`}
                    style={{ marginTop: 2 }}
                  >
                    {item.description}
                  </Text>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </Card>
  );
}

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
