import type { WorkflowCreatedData, WorkflowDraftData } from "@gaia/shared";
import { View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FlashIcon,
  FlowIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Helpers -----------------------------------------------------------------

interface TriggerDisplay {
  label: string;
  icon: React.ReactNode;
  badgeColor: string;
  badgeBg: string;
}

function getTriggerDisplay(
  type?: string,
  cron?: string,
  slug?: string,
): TriggerDisplay {
  switch (type) {
    case "manual":
      return {
        label: "Manual",
        icon: <AppIcon icon={FlashIcon} size={12} color="#a1a1aa" />,
        badgeColor: "#a1a1aa",
        badgeBg: "bg-zinc-700/50",
      };
    case "scheduled":
      return {
        label: cron ? formatCron(cron) : "Scheduled",
        icon: <AppIcon icon={Clock01Icon} size={12} color="#00bbff" />,
        badgeColor: "#00bbff",
        badgeBg: "bg-[#00bbff]/15",
      };
    case "integration": {
      const name =
        slug
          ?.split("_")
          .slice(0, 2)
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
          .join(" ") ?? "Integration";
      return {
        label: name,
        icon: <AppIcon icon={Calendar03Icon} size={12} color="#a78bfa" />,
        badgeColor: "#a78bfa",
        badgeBg: "bg-purple-500/15",
      };
    }
    default:
      return {
        label: "Unknown",
        icon: <AppIcon icon={FlashIcon} size={12} color="#a1a1aa" />,
        badgeColor: "#a1a1aa",
        badgeBg: "bg-zinc-700/50",
      };
  }
}

/** Very simple human-readable cron label (matches web's getScheduleDescription intent). */
function formatCron(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length < 5) return "Scheduled";
  const [min, hour, dom, , dow] = parts;
  if (dom === "*" && dow === "*") {
    if (hour === "*") return `Every ${min === "*" ? "minute" : `${min} min`}`;
    const h = Number(hour);
    const period = h >= 12 ? "PM" : "AM";
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `Daily at ${h12}:${min.padStart(2, "0")} ${period}`;
  }
  if (dom === "*" && dow !== "*") {
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const dayName = days[Number(dow)] ?? dow;
    return `Weekly on ${dayName}`;
  }
  return "Scheduled";
}

// -- Badge -------------------------------------------------------------------

function TriggerBadge({ display }: { display: TriggerDisplay }) {
  return (
    <View
      className={`flex-row items-center gap-1.5 px-2.5 py-1 rounded-full ${display.badgeBg}`}
    >
      {display.icon}
      <Text
        className="text-xs font-medium"
        style={{ color: display.badgeColor }}
      >
        {display.label}
      </Text>
    </View>
  );
}

function StatusBadge({
  label,
  color,
  bg,
}: {
  label: string;
  color: string;
  bg: string;
}) {
  return (
    <View className={`px-2.5 py-1 rounded-full ${bg}`}>
      <Text className="text-xs font-semibold" style={{ color }}>
        {label}
      </Text>
    </View>
  );
}

// -- Draft card --------------------------------------------------------------

export function WorkflowDraftCard({ data }: { data: WorkflowDraftData }) {
  const title = data.suggested_title ?? "Workflow Draft";
  const description = data.suggested_description;
  const trigger = getTriggerDisplay(
    data.trigger_type,
    data.cron_expression ?? undefined,
    data.trigger_slug ?? undefined,
  );

  return (
    <ToolCardShell>
      {/* Header */}
      <View className="flex-row items-start justify-between gap-3 mb-3">
        <View className="flex-row items-center gap-3 flex-1 min-w-0">
          <View className="w-10 h-10 rounded-xl bg-[#00bbff]/15 items-center justify-center shrink-0">
            <AppIcon icon={FlowIcon} size={20} color="#00bbff" />
          </View>
          <View className="flex-1 min-w-0">
            <Text
              className="text-base font-semibold text-zinc-100 leading-tight"
              numberOfLines={2}
            >
              {title}
            </Text>
            <Text className="text-xs mt-0.5" style={{ color: "#f59e0b99" }}>
              Review to create workflow
            </Text>
          </View>
        </View>
        <StatusBadge label="Draft" color="#f59e0b" bg="bg-amber-500/15" />
      </View>

      {/* Description */}
      {!!description && (
        <Text
          className="text-xs leading-relaxed text-zinc-400 mb-3"
          numberOfLines={2}
        >
          {description}
        </Text>
      )}

      {/* Integration note */}
      {data.trigger_type === "integration" && (
        <Text className="text-xs text-zinc-500 mb-3">
          Configure trigger settings to complete setup
        </Text>
      )}

      {/* Trigger chip */}
      <View className="mb-3">
        <TriggerBadge display={trigger} />
      </View>

      {/* Review & Create button */}
      <ToolCardInner>
        <View className="flex-row items-center justify-center gap-2">
          <AppIcon icon={PencilEdit01Icon} size={14} color="#00bbff" />
          <Text className="text-sm font-medium text-[#00bbff]">
            Review &amp; Create
          </Text>
        </View>
      </ToolCardInner>
    </ToolCardShell>
  );
}

// -- Created card ------------------------------------------------------------

export function WorkflowCreatedCard({ data }: { data: WorkflowCreatedData }) {
  const title = data.title ?? "Workflow";
  const description = data.description;
  const trigger = getTriggerDisplay(
    data.trigger_config?.type,
    data.trigger_config?.cron_expression ?? undefined,
    data.trigger_config?.trigger_name ?? undefined,
  );

  return (
    <ToolCardShell>
      {/* Header */}
      <View className="flex-row items-start justify-between gap-3 mb-3">
        <View className="flex-row items-center gap-3 flex-1 min-w-0">
          <View className="w-10 h-10 rounded-xl bg-emerald-500/15 items-center justify-center shrink-0">
            <AppIcon icon={FlowIcon} size={20} color="#10b981" />
          </View>
          <View className="flex-1 min-w-0">
            <Text
              className="text-base font-semibold text-zinc-100 leading-tight"
              numberOfLines={2}
            >
              {title}
            </Text>
            <Text className="text-xs text-zinc-500 mt-0.5">
              Workflow Created
            </Text>
          </View>
        </View>
        <View className="flex-row items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 shrink-0">
          <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#10b981" />
          <Text className="text-xs font-semibold text-emerald-400">
            Created
          </Text>
        </View>
      </View>

      {/* Description */}
      {!!description && (
        <Text
          className="text-xs leading-relaxed text-zinc-400 mb-3"
          numberOfLines={2}
        >
          {description}
        </Text>
      )}

      {/* Trigger chip */}
      <View className="mb-3">
        <TriggerBadge display={trigger} />
      </View>

      {/* View & Edit button */}
      <ToolCardInner>
        <View className="flex-row items-center justify-center gap-2">
          <AppIcon icon={PencilEdit01Icon} size={14} color="#00bbff" />
          <Text className="text-sm font-medium text-[#00bbff]">
            View &amp; Edit
          </Text>
        </View>
      </ToolCardInner>
    </ToolCardShell>
  );
}
