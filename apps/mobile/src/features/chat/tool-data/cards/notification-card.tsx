import { Chip } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Notification01Icon,
  Notification02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export interface NotificationItem {
  title?: string;
  body?: string;
  type?: string;
  status?: string;
  created_at?: string;
  metadata?: { reminder_id?: string };
  // Support nested content structure (NotificationRecord shape)
  content?: {
    title?: string;
    body?: string;
  };
}

export interface NotificationData {
  notifications?: NotificationItem[];
}

const TYPE_CONFIG: Record<string, { iconColor: string }> = {
  info: { iconColor: "#00bbff" },
  success: { iconColor: "#4ade80" },
  warning: { iconColor: "#facc15" },
  error: { iconColor: "#f87171" },
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
  const { iconColor } = TYPE_CONFIG[typeKey] ?? TYPE_CONFIG.info;
  const relativeTime = formatRelativeTime(item.created_at);
  const isUnread =
    item.status === "delivered" || item.status === "pending" || !item.status;
  const categoryLabel = item.metadata?.reminder_id ? "reminder" : "system";

  return (
    <ToolCardInner>
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center gap-2">
            {!!title && (
              <Text
                className={`text-sm font-medium flex-1 ${isUnread ? "text-zinc-100" : "text-zinc-400"}`}
                numberOfLines={1}
              >
                {title}
              </Text>
            )}
            {isUnread && (
              <View className="w-1.5 h-1.5 rounded-full bg-[#00bbff] shrink-0" />
            )}
          </View>
          {!!body && (
            <Text
              className="text-sm font-light text-zinc-400 mt-1 leading-snug"
              numberOfLines={2}
            >
              {body}
            </Text>
          )}
          <View className="flex-row items-center gap-2 mt-1">
            {!!relativeTime && (
              <Text className="text-xs text-zinc-500">{relativeTime}</Text>
            )}
            <View className="px-1.5 py-0.5 rounded-full bg-zinc-800">
              <Text className="text-[10px] text-zinc-400 capitalize">
                {categoryLabel}
              </Text>
            </View>
          </View>
        </View>
        <AppIcon
          icon={isUnread ? Notification02Icon : Notification01Icon}
          size={14}
          color={isUnread ? iconColor : "#71717a"}
        />
      </View>
    </ToolCardInner>
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
      <ToolCardShell>
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={Notification01Icon} size={14} color="#71717a" />
          <Text className="text-xs text-zinc-500">Notifications</Text>
        </View>
        <View className="py-8 items-center">
          <AppIcon icon={Notification01Icon} size={32} color="#3f3f46" />
          <Text className="text-sm font-medium text-zinc-300 mt-4">
            No notifications found
          </Text>
          <Text className="text-xs text-zinc-400 mt-1 text-center">
            You're all caught up! New notifications will appear here.
          </Text>
        </View>
      </ToolCardShell>
    );
  }

  return (
    <ToolCardShell>
      {/* Header */}
      <View className="flex-row items-center gap-2 mb-3">
        <AppIcon icon={Notification01Icon} size={14} color="#71717a" />
        <Text className="text-xs text-zinc-500">Notifications</Text>
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

      {/* Notification rows */}
      <View className="gap-2">
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

      {/* Footer: unread count summary */}
      {unreadCount > 0 && (
        <View className="border-t border-zinc-700 mt-3 pt-3">
          <Text className="text-sm text-zinc-400">
            {unreadCount} unread notification{unreadCount !== 1 ? "s" : ""}
          </Text>
        </View>
      )}
    </ToolCardShell>
  );
}
