import { Pressable, View } from "react-native";
import {
  AppIcon,
  Comment01Icon,
  HelpCircleIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type SupportTicketType = "support" | "feature";

export interface SupportTicketData {
  type?: SupportTicketType;
  title?: string;
  description?: string;
  status?: string;
  priority?: "high" | "medium" | "low" | "critical";
  user_name?: string;
  user_email?: string;
}

// -- Priority config -----------------------------------------------------------

const PRIORITY_CONFIG: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  critical: {
    bg: "bg-red-500/15",
    text: "text-red-400",
    label: "Critical Priority",
  },
  high: { bg: "bg-red-500/15", text: "text-red-400", label: "High Priority" },
  medium: {
    bg: "bg-amber-400/10",
    text: "text-amber-400",
    label: "Medium Priority",
  },
  low: { bg: "bg-primary/10", text: "text-primary", label: "Low Priority" },
};

// -- Status config -------------------------------------------------------------

const STATUS_CONFIG: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  open: { bg: "bg-emerald-400/10", text: "text-emerald-400", label: "Open" },
  closed: { bg: "bg-zinc-700", text: "text-zinc-400", label: "Closed" },
  pending: {
    bg: "bg-amber-400/10",
    text: "text-amber-400",
    label: "Pending",
  },
  resolved: {
    bg: "bg-primary/10",
    text: "text-primary",
    label: "Resolved",
  },
};

// -- Divider ------------------------------------------------------------------

function Divider() {
  return <View className="h-px bg-zinc-700 my-1.5" />;
}

// -- Pill badge ---------------------------------------------------------------

function Pill({
  bg,
  text,
  label,
}: {
  bg: string;
  text: string;
  label: string;
}) {
  return (
    <View className={`self-start rounded-full px-2.5 py-0.5 ${bg}`}>
      <Text className={`text-[11px] font-medium ${text}`}>{label}</Text>
    </View>
  );
}

// -- Card ---------------------------------------------------------------------

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  const isFeature = data.type === "feature";
  const typeLabel = isFeature ? "Feature Request" : "Support Ticket";

  const priorityInfo =
    data.priority && PRIORITY_CONFIG[data.priority]
      ? PRIORITY_CONFIG[data.priority]
      : null;

  const statusKey = (data.status ?? "open").toLowerCase();
  const statusInfo = STATUS_CONFIG[statusKey] ?? STATUS_CONFIG.open;

  return (
    <ToolCardShell>
      {/* Header row — type icon + chip + status */}
      <View className="flex-row items-center gap-2 mb-3">
        <View
          className={`rounded-full p-1 ${isFeature ? "bg-emerald-400/10" : "bg-primary/10"}`}
        >
          <AppIcon
            icon={isFeature ? Comment01Icon : HelpCircleIcon}
            size={13}
            color={isFeature ? "#34d399" : "#00bbff"}
          />
        </View>
        <Text
          className={`text-xs font-medium ${isFeature ? "text-emerald-400" : "text-primary"}`}
        >
          {typeLabel}
        </Text>
        <View className="ml-auto">
          <Pill
            bg={statusInfo.bg}
            text={statusInfo.text}
            label={statusInfo.label}
          />
        </View>
      </View>

      {/* Title row with edit button */}
      <View className="flex-row items-center justify-between mb-1.5">
        <Text className="text-zinc-100 text-base font-semibold flex-1 mr-2">
          {data.title ?? "Untitled Ticket"}
        </Text>
        <Pressable hitSlop={8} className="p-1">
          <AppIcon icon={PencilEdit01Icon} size={15} color="#71717a" />
        </Pressable>
      </View>

      <Divider />

      {/* Priority pill */}
      {priorityInfo ? (
        <View className="mt-1 mb-2">
          <Pill
            bg={priorityInfo.bg}
            text={priorityInfo.text}
            label={priorityInfo.label}
          />
        </View>
      ) : null}

      {/* User info */}
      {(data.user_name ?? data.user_email) ? (
        <>
          <View className="flex-row items-center gap-1.5 mb-2">
            <Text className="text-zinc-400 text-xs">From:</Text>
            <Text className="text-zinc-200 text-xs font-medium">
              {data.user_name ?? data.user_email}
            </Text>
            {data.user_name && data.user_email ? (
              <Text className="text-zinc-500 text-xs">({data.user_email})</Text>
            ) : null}
          </View>
          <Divider />
        </>
      ) : null}

      {/* Description */}
      {data.description ? (
        <ToolCardInner dense>
          <Text
            className="text-zinc-200 text-xs leading-[18px]"
            numberOfLines={8}
          >
            {data.description}
          </Text>
        </ToolCardInner>
      ) : null}

      {/* Submit button */}
      <View className="mt-3 flex-row justify-end">
        <Pressable
          className="rounded-full bg-primary px-4 py-2"
          android_ripple={{ color: "rgba(0,0,0,0.1)" }}
        >
          <Text className="text-black text-sm font-medium">Submit Ticket</Text>
        </Pressable>
      </View>
    </ToolCardShell>
  );
}
