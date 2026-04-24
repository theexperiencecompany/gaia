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
  title?: string;
}

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
  const isUnread =
    item.status === "delivered" || item.status === "pending" || !item.status;
  const relativeTime = formatRelativeTime(item.created_at);
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
          <View className="flex-row items-center gap-2 mt-1.5">
            {!!relativeTime && (
              <Text className="text-xs text-zinc-500">{relativeTime}</Text>
            )}
            <View className="px-1.5 py-0.5 rounded-full bg-zinc-700">
              <Text className="text-[10px] text-zinc-400 capitalize">
                {categoryLabel}
              </Text>
            </View>
          </View>
        </View>
        <AppIcon
          icon={isUnread ? Notification02Icon : Notification01Icon}
          size={16}
          color={isUnread ? "#00bbff" : "#71717a"}
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
        {/* Header — matches web: icon + title */}
        <View className="flex-row items-center gap-3 mb-3">
          <AppIcon icon={Notification01Icon} size={20} color="#71717a" />
          <Text className="text-sm font-medium text-zinc-100">
            {data.title ?? "Notifications"}
          </Text>
        </View>
        {/* Empty state — matches web: large icon + messages */}
        <View className="py-8 items-center">
          <AppIcon icon={Notification01Icon} size={40} color="#3f3f46" />
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
      {/* Header — icon + title + total count chip + unread chip */}
      <View className="flex-row items-center gap-3 mb-3">
        <AppIcon icon={Notification01Icon} size={20} color="#71717a" />
        <Text className="text-sm font-medium text-zinc-100 flex-1">
          {data.title ?? "Notifications"}
        </Text>
        <View className="flex-row items-center gap-1.5">
          {/* Total count badge */}
          <View className="px-2 py-0.5 rounded-full bg-zinc-700">
            <Text className="text-zinc-300 text-xs font-medium">{count}</Text>
          </View>
          {/* Unread badge */}
          {unreadCount > 0 && (
            <View className="px-2 py-0.5 rounded-full bg-blue-900/30">
              <Text className="text-blue-400 text-xs font-medium">
                {unreadCount} unread
              </Text>
            </View>
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

      {/* Footer: unread summary — matches web */}
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
