import { Card } from "heroui-native";
import { View } from "react-native";
import { AppIcon, Comment01Icon, HelpCircleIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";

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

const priorityConfig: Record<
  string,
  { bgColor: string; textColor: string; label: string }
> = {
  critical: {
    bgColor: "bg-red-500/10",
    textColor: "text-red-400",
    label: "Critical",
  },
  high: {
    bgColor: "bg-red-500/10",
    textColor: "text-red-400",
    label: "High",
  },
  medium: {
    bgColor: "bg-yellow-500/10",
    textColor: "text-yellow-400",
    label: "Medium",
  },
  low: {
    bgColor: "bg-blue-500/10",
    textColor: "text-blue-400",
    label: "Low",
  },
};

const statusConfig: Record<
  string,
  { bgColor: string; textColor: string; label: string }
> = {
  open: {
    bgColor: "bg-green-500/10",
    textColor: "text-green-400",
    label: "Open",
  },
  closed: {
    bgColor: "bg-white/10",
    textColor: "text-[#8e8e93]",
    label: "Closed",
  },
  pending: {
    bgColor: "bg-yellow-500/10",
    textColor: "text-yellow-400",
    label: "Pending",
  },
  resolved: {
    bgColor: "bg-blue-500/10",
    textColor: "text-blue-400",
    label: "Resolved",
  },
};

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  const isFeature = data.type === "feature";
  const typeLabel = isFeature ? "Feature Request" : "Support Ticket";
  const priorityInfo =
    data.priority && priorityConfig[data.priority]
      ? priorityConfig[data.priority]
      : null;
  const statusKey = data.status?.toLowerCase() ?? "open";
  const statusInfo = statusConfig[statusKey] ?? statusConfig.open;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header row */}
        <View className="flex-row items-center gap-2 mb-3">
          <View
            className={`rounded-full p-1 ${isFeature ? "bg-green-500/15" : "bg-[#00bbff]/15"}`}
          >
            <AppIcon
              icon={isFeature ? Comment01Icon : HelpCircleIcon}
              size={13}
              color={isFeature ? "#4ade80" : "#00bbff"}
            />
          </View>
          <Text
            className={`text-xs font-medium ${isFeature ? "text-green-400" : "text-[#00bbff]"}`}
          >
            {typeLabel}
          </Text>

          {/* Status badge */}
          <View
            className={`ml-auto rounded-full px-2 py-0.5 ${statusInfo.bgColor}`}
          >
            <Text className={`text-[10px] font-medium ${statusInfo.textColor}`}>
              {statusInfo.label}
            </Text>
          </View>
        </View>

        {/* Title */}
        <Text className="text-sm font-semibold text-white mb-1">
          {data.title || "Untitled Ticket"}
        </Text>

        {/* Priority badge */}
        {priorityInfo && (
          <View
            className={`self-start rounded-full px-2 py-0.5 mb-2 ${priorityInfo.bgColor}`}
          >
            <Text
              className={`text-[10px] font-medium ${priorityInfo.textColor}`}
            >
              {priorityInfo.label} Priority
            </Text>
          </View>
        )}

        {/* Description */}
        {!!data.description && (
          <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2 mt-1">
            <Text
              className="text-xs text-[#8e8e93] leading-[18px]"
              numberOfLines={4}
            >
              {data.description}
            </Text>
          </View>
        )}

        {/* User info */}
        {(data.user_name || data.user_email) && (
          <View className="flex-row items-center gap-1.5 mt-2.5">
            <Text className="text-[11px] text-[#8e8e93]">From:</Text>
            <Text className="text-[11px] text-white font-medium">
              {data.user_name || data.user_email}
            </Text>
            {data.user_name && data.user_email && (
              <Text className="text-[11px] text-[#8e8e93]">
                ({data.user_email})
              </Text>
            )}
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
