import { View } from "react-native";
import { NotificationIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface NotificationItem {
  id?: string;
  title?: string;
  body?: string;
  type?: string;
  status?: string;
  created_at?: string;
  metadata?: {
    reminder_id?: string | null;
  } | null;
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

// -- Helpers ------------------------------------------------------------------

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

function isUnreadStatus(status?: string): boolean {
  return status === "delivered" || status === "pending" || !status;
}

function categoryLabel(item: NotificationItem): string {
  return item.metadata?.reminder_id ? "reminder" : "system";
}

// -- Row ----------------------------------------------------------------------

function NotificationRow({ item }: { item: NotificationItem }) {
  const title = item.content?.title ?? item.title ?? "Notification";
  const body = item.content?.body ?? item.body;
  const relativeTime = formatRelativeTime(item.created_at);
  const unread = isUnreadStatus(item.status);
  const category = categoryLabel(item);

  return (
    <ToolCardInner>
      <View className="flex-row items-start gap-3">
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center gap-2">
            <Text
              className="text-sm font-medium text-zinc-100 flex-1"
              numberOfLines={1}
            >
              {title}
            </Text>
            {unread && (
              <View className="w-1.5 h-1.5 rounded-full bg-[#00bbff]" />
            )}
          </View>
          {!!body && (
            <Text
              className="mt-1 text-sm text-zinc-400"
              numberOfLines={2}
            >
              {body}
            </Text>
          )}
          <View className="mt-1.5 flex-row items-center gap-2">
            {!!relativeTime && (
              <Text className="text-xs text-zinc-500">{relativeTime}</Text>
            )}
            <View className="rounded-full bg-zinc-700 px-2 py-0.5">
              <Text className="text-xs text-zinc-400 capitalize">
                {category}
              </Text>
            </View>
          </View>
        </View>
      </View>
    </ToolCardInner>
  );
}

// -- Card ---------------------------------------------------------------------

export function NotificationCard({ data }: { data: NotificationData }) {
  const notifications = data.notifications ?? [];
  const count = notifications.length;
  const unreadCount = notifications.filter((n) => isUnreadStatus(n.status))
    .length;
  const title = data.title ?? "Notifications";

  if (count === 0) {
    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={NotificationIcon}
          iconColor="#a1a1aa"
          title={title}
        />
        <ToolCardInner>
          <View className="items-center py-4">
            <Text className="text-sm font-medium text-zinc-300">
              No notifications found
            </Text>
            <Text className="mt-1 text-xs text-zinc-500 text-center">
              You're all caught up. New notifications will appear here.
            </Text>
          </View>
        </ToolCardInner>
      </ToolCardShell>
    );
  }

  const unreadBadge =
    unreadCount > 0 ? (
      <View className="rounded-full bg-[#00bbff]/15 px-2 py-0.5">
        <Text className="text-xs font-medium text-[#00bbff]">
          {unreadCount} unread
        </Text>
      </View>
    ) : undefined;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={NotificationIcon}
        iconColor="#a1a1aa"
        title={title}
        count={count}
        trailing={unreadBadge}
      />
      <View className="gap-2">
        {notifications.map((item, index) => (
          <NotificationRow
            key={
              item.id ??
              item.content?.title ??
              item.title ??
              item.created_at ??
              String(index)
            }
            item={item}
          />
        ))}
      </View>
    </ToolCardShell>
  );
}
