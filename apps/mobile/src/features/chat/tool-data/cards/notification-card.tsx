import { Card, Chip } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Notification01Icon,
  Notification02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface NotificationItem {
  title?: string;
  body?: string;
  type?: string;
  status?: string;
  created_at?: string;
  // Support nested content structure (NotificationRecord shape)
  content?: {
    title?: string;
    body?: string;
  };
}

export interface NotificationData {
  notifications?: NotificationItem[];
}

const typeConfig: Record<string, { bgColor: string; iconColor: string }> = {
  info: { bgColor: "bg-[#00bbff]/15", iconColor: "#00bbff" },
  success: { bgColor: "bg-green-500/15", iconColor: "#4ade80" },
  warning: { bgColor: "bg-yellow-500/15", iconColor: "#facc15" },
  error: { bgColor: "bg-red-500/15", iconColor: "#f87171" },
};

function formatRelativeTime(isoString?: string): string | null {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function NotificationRow({ item }: { item: NotificationItem }) {
  const title = item.content?.title ?? item.title;
  const body = item.content?.body ?? item.body;
  const typeKey = item.type?.toLowerCase() ?? "info";
  const config = typeConfig[typeKey] ?? typeConfig.info;
  const relativeTime = formatRelativeTime(item.created_at);
  const isUnread =
    item.status === "delivered" || item.status === "pending" || !item.status;

  return (
    <View className="flex-row items-start gap-3 py-2.5 border-b border-white/8 last:border-b-0">
      <View className={`rounded-full p-1.5 mt-0.5 ${config.bgColor}`}>
        <AppIcon
          icon={isUnread ? Notification02Icon : Notification01Icon}
          size={13}
          color={config.iconColor}
        />
      </View>
      <View className="flex-1 min-w-0">
        <View className="flex-row items-center justify-between gap-2">
          {!!title && (
            <Text
              className={`text-sm font-medium flex-1 ${isUnread ? "text-white" : "text-[#8e8e93]"}`}
              numberOfLines={1}
            >
              {title}
            </Text>
          )}
          {!!relativeTime && (
            <Text className="text-[10px] text-[#8e8e93] flex-shrink-0">
              {relativeTime}
            </Text>
          )}
        </View>
        {!!body && (
          <Text
            className="text-xs text-[#8e8e93] mt-0.5 leading-[16px]"
            numberOfLines={2}
          >
            {body}
          </Text>
        )}
      </View>
    </View>
  );
}

export function NotificationCard({ data }: { data: NotificationData }) {
  const notifications = data.notifications ?? [];
  const count = notifications.length;
  const unreadCount = notifications.filter(
    (n) => n.status === "delivered" || n.status === "pending" || !n.status,
  ).length;

  if (count === 0) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-6 px-4 items-center">
          <AppIcon icon={Notification01Icon} size={24} color="#8e8e93" />
          <Text className="text-sm text-[#8e8e93] mt-2">No notifications</Text>
        </Card.Body>
      </Card>
    );
  }

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={Notification01Icon} size={14} color="#8e8e93" />
          <Text className="text-xs text-[#8e8e93]">Notifications</Text>
          <View className="flex-row items-center gap-1.5 ml-auto">
            <Chip
              size="sm"
              variant="secondary"
              color="default"
              animation="disable-all"
            >
              <Chip.Label>{count} total</Chip.Label>
            </Chip>
            {unreadCount > 0 && (
              <Chip
                size="sm"
                variant="primary"
                color="accent"
                animation="disable-all"
              >
                <Chip.Label>{unreadCount} unread</Chip.Label>
              </Chip>
            )}
          </View>
        </View>

        {/* Notifications list */}
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
          {notifications.map((item, index) => (
            <NotificationRow
              key={
                item.content?.title ||
                item.title ||
                item.created_at ||
                String(index)
              }
              item={item}
            />
          ))}
        </View>
      </Card.Body>
    </Card>
  );
}
