import { Card, Chip } from "heroui-native";
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

type ChipColor = "accent" | "default" | "success" | "warning" | "danger";
type ChipVariant = "primary" | "secondary";

const priorityConfig: Record<
  string,
  { color: ChipColor; variant: ChipVariant; label: string }
> = {
  critical: { color: "danger", variant: "secondary", label: "Critical" },
  high: { color: "danger", variant: "secondary", label: "High" },
  medium: { color: "warning", variant: "secondary", label: "Medium" },
  low: { color: "accent", variant: "secondary", label: "Low" },
};

const statusConfig: Record<
  string,
  { color: ChipColor; variant: ChipVariant; label: string }
> = {
  open: { color: "success", variant: "secondary", label: "Open" },
  closed: { color: "default", variant: "secondary", label: "Closed" },
  pending: { color: "warning", variant: "secondary", label: "Pending" },
  resolved: { color: "accent", variant: "secondary", label: "Resolved" },
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
          <Chip
            size="sm"
            variant={statusInfo.variant}
            color={statusInfo.color}
            animation="disable-all"
            className="ml-auto"
          >
            <Chip.Label>{statusInfo.label}</Chip.Label>
          </Chip>
        </View>

        {/* Title */}
        <Text className="text-sm font-semibold text-white mb-1">
          {data.title || "Untitled Ticket"}
        </Text>

        {/* Priority badge */}
        {priorityInfo && (
          <Chip
            size="sm"
            variant={priorityInfo.variant}
            color={priorityInfo.color}
            animation="disable-all"
            className="self-start mb-2"
          >
            <Chip.Label>{priorityInfo.label} Priority</Chip.Label>
          </Chip>
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
