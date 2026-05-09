import { useMutation } from "@tanstack/react-query";
import { Button, Chip } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import {
  AppIcon,
  CheckmarkBadge01Icon,
  NotificationIcon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";
import { inAppNotificationsApi } from "@/features/notifications/api/inapp-notifications-api";

// ---------------------------------------------------------------------------
// Types — mirror NotificationRecord from
// apps/web/src/types/features/notificationTypes.ts. Fields are optional so we
// can render the loose tool output streamed from the agent.
// ---------------------------------------------------------------------------

export interface NotificationActionItem {
  id: string;
  label: string;
  style?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  executed?: boolean;
}

export interface NotificationItem {
  id?: string;
  title?: string;
  body?: string;
  type?: string;
  status?: string;
  created_at?: string;
  metadata?: { reminder_id?: string };
  /** Web NotificationRecord nests title/body/actions under `content`. */
  content?: {
    title?: string;
    body?: string;
    actions?: NotificationActionItem[];
  };
}

export interface NotificationData {
  notifications?: NotificationItem[];
  title?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const UNREAD_STATUSES = new Set(["delivered", "pending"]);

function isUnread(item: NotificationItem): boolean {
  // Treat missing status as unread to match web's NotificationItem behavior
  // when the agent ships partial records.
  if (!item.status) return true;
  return UNREAD_STATUSES.has(item.status);
}

/**
 * Approximation of date-fns `formatDistanceToNow(date, { addSuffix: true })`.
 * The web NotificationItem uses date-fns; mobile keeps the dependency surface
 * small and emits the same human-readable phrasing.
 */
function formatDistanceToNow(isoString?: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const diffSeconds = Math.round(diffMs / 1000);
  if (diffSeconds < 30) return "less than a minute ago";
  if (diffSeconds < 90) return "1 minute ago";
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 45) return `${diffMinutes} minutes ago`;
  if (diffMinutes < 90) return "about 1 hour ago";
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `about ${diffHours} hours ago`;
  if (diffHours < 42) return "1 day ago";
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 30) return `${diffDays} days ago`;
  if (diffDays < 45) return "about 1 month ago";
  if (diffDays < 365) {
    const diffMonths = Math.round(diffDays / 30);
    return `about ${diffMonths} months ago`;
  }
  const diffYears = Math.round(diffDays / 365);
  if (diffYears === 1) return "about 1 year ago";
  return `about ${diffYears} years ago`;
}

// ---------------------------------------------------------------------------
// NotificationRow — port of NotificationItem.tsx
// ---------------------------------------------------------------------------

interface NotificationRowProps {
  item: NotificationItem;
  onMarkAsRead?: (id: string) => Promise<void> | void;
  onAction?: (id: string, actionId: string) => Promise<void> | void;
}

function NotificationRow({
  item,
  onMarkAsRead,
  onAction,
}: NotificationRowProps) {
  const title = item.content?.title ?? item.title ?? "Notification";
  const body = item.content?.body ?? item.body ?? "";
  const actions = item.content?.actions ?? [];
  const unread = isUnread(item);
  const relativeTime = formatDistanceToNow(item.created_at);
  const categoryLabel = item.metadata?.reminder_id ? "reminder" : "system";
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [isMarking, setIsMarking] = useState(false);

  const handleMarkAsRead = async () => {
    if (!item.id || !onMarkAsRead) return;
    setIsMarking(true);
    try {
      await onMarkAsRead(item.id);
    } finally {
      setIsMarking(false);
    }
  };

  const handleAction = async (actionId: string) => {
    if (!item.id || !onAction) return;
    setPendingActionId(actionId);
    try {
      await onAction(item.id, actionId);
    } finally {
      setPendingActionId(null);
    }
  };

  return (
    <View className="rounded-2xl bg-zinc-900 p-4">
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 min-w-0">
          {/* Title row + unread dot */}
          <View className="flex-row items-center gap-2">
            <Text
              className="text-sm font-medium text-zinc-100 flex-1"
              numberOfLines={1}
            >
              {title}
            </Text>
            {unread && (
              <View className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
            )}
          </View>

          {/* Body */}
          {!!body && (
            <Text
              className="my-1 text-sm font-light text-zinc-400"
              numberOfLines={2}
            >
              {body}
            </Text>
          )}

          {/* Footer — relative time + category chip */}
          <View className="mt-1 flex-row items-center gap-2">
            {!!relativeTime && (
              <Text className="text-xs text-zinc-600 capitalize">
                {relativeTime}
              </Text>
            )}
            <View className="rounded-full bg-zinc-800 px-2 py-0.5">
              <Text className="text-xs text-zinc-400 capitalize">
                {categoryLabel}
              </Text>
            </View>
          </View>
        </View>

        {/* Mark as read icon button — only visible while unread */}
        {unread && item.id && onMarkAsRead && (
          <Button
            variant="secondary"
            size="sm"
            isIconOnly
            onPress={handleMarkAsRead}
            isDisabled={isMarking}
          >
            {isMarking ? (
              <ActivityIndicator size="small" color="#a1a1aa" />
            ) : (
              <AppIcon icon={CheckmarkBadge01Icon} size={14} color="#a1a1aa" />
            )}
          </Button>
        )}
      </View>

      {/* Action buttons */}
      {actions.length > 0 && (
        <View className="mt-3 flex-row gap-2 flex-wrap">
          {actions.map((action) => {
            const isExecuted = action.executed === true;
            const isExecuting = pendingActionId === action.id;
            const isDisabled =
              action.disabled || isExecuted || isExecuting || !onAction;

            return (
              <Button
                key={action.id}
                variant={action.style === "primary" ? "primary" : "secondary"}
                size="sm"
                isDisabled={isDisabled}
                onPress={() => void handleAction(action.id)}
              >
                {isExecuting ? (
                  <View className="flex-row items-center gap-1">
                    <ActivityIndicator size="small" color="#e5e5e5" />
                    <Button.Label>Processing...</Button.Label>
                  </View>
                ) : isExecuted ? (
                  <View className="flex-row items-center gap-1">
                    <Button.Label>{action.label}</Button.Label>
                    <AppIcon icon={Tick02Icon} size={12} color="#a1a1aa" />
                  </View>
                ) : (
                  <Button.Label>{action.label}</Button.Label>
                )}
              </Button>
            );
          })}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// NotificationCard — port of NotificationListSection.tsx
// ---------------------------------------------------------------------------

interface NotificationCardProps {
  data: NotificationData;
}

export function NotificationCard({ data }: NotificationCardProps) {
  const initialNotifications = data.notifications ?? [];
  const title = data.title ?? "Your Notifications";

  // Local state mirrors web's `localNotifications` so the row can disappear
  // from the unread set immediately after a successful mark-as-read.
  const [notifications, setNotifications] =
    useState<NotificationItem[]>(initialNotifications);

  const markAsReadMutation = useMutation({
    mutationFn: async (notificationId: string) => {
      await inAppNotificationsApi.markAsRead(notificationId);
    },
  });

  const bulkMarkAsReadMutation = useMutation({
    mutationFn: async (notificationIds: string[]) => {
      await inAppNotificationsApi.bulkMarkAsRead(notificationIds);
    },
  });

  const executeActionMutation = useMutation({
    mutationFn: async ({
      notificationId,
      actionId,
    }: {
      notificationId: string;
      actionId: string;
    }) => {
      await inAppNotificationsApi.executeAction(notificationId, actionId);
    },
  });

  const unreadNotifications = notifications.filter(isUnread);
  const unreadCount = unreadNotifications.length;
  const totalCount = notifications.length;

  const markRead = (id: string): NotificationItem[] =>
    notifications.map((n) =>
      n.id === id
        ? {
            ...n,
            status: "read",
          }
        : n,
    );

  const handleMarkAsRead = async (id: string) => {
    try {
      await markAsReadMutation.mutateAsync(id);
      setNotifications(markRead(id));
    } catch {
      // Silent — UI stays in unread state on failure (matches web flow).
    }
  };

  const handleMarkAllAsRead = async () => {
    if (unreadCount === 0) return;
    const ids = unreadNotifications
      .map((n) => n.id)
      .filter((id): id is string => Boolean(id));
    if (ids.length === 0) return;
    try {
      await bulkMarkAsReadMutation.mutateAsync(ids);
      setNotifications(
        notifications.map((n) =>
          ids.includes(n.id ?? "") ? { ...n, status: "read" } : n,
        ),
      );
    } catch {
      // Silent on failure.
    }
  };

  const handleExecuteAction = async (id: string, actionId: string) => {
    try {
      await executeActionMutation.mutateAsync({
        notificationId: id,
        actionId,
      });
    } catch {
      // Silent on failure.
    }
  };

  // Empty state — matches web's "No notifications found" panel.
  if (totalCount === 0) {
    return (
      <CollapsibleCard
        icon={NotificationIcon}
        iconColor="#a1a1aa"
        iconSize={20}
        title={title}
        titleTone="bright"
      >
        <View className="items-center justify-center py-8">
          <AppIcon icon={NotificationIcon} size={40} color="#52525b" />
          <Text className="mt-4 text-sm font-medium text-zinc-300">
            No notifications found
          </Text>
          <Text className="mt-1 text-sm text-zinc-400 text-center">
            You're all caught up! New notifications will appear here.
          </Text>
        </View>
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      icon={NotificationIcon}
      iconColor="#a1a1aa"
      iconSize={20}
      title={title}
      titleTone="bright"
      trailing={
        <View className="flex-row items-center gap-1.5">
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
            className="bg-zinc-700"
          >
            <Chip.Label className="text-zinc-300">{totalCount}</Chip.Label>
          </Chip>
          {unreadCount > 0 && (
            <Chip
              size="sm"
              variant="soft"
              color="default"
              animation="disable-all"
              className="bg-blue-900/30"
            >
              <Chip.Label className="text-blue-400">
                {unreadCount} unread
              </Chip.Label>
            </Chip>
          )}
        </View>
      }
    >
      <View className="gap-3">
        {/* Mark all read */}
        {unreadCount > 0 && (
          <View className="items-end">
            <Button
              size="sm"
              variant="secondary"
              onPress={() => void handleMarkAllAsRead()}
              isDisabled={bulkMarkAsReadMutation.isPending}
            >
              {bulkMarkAsReadMutation.isPending ? (
                <View className="flex-row items-center gap-1">
                  <ActivityIndicator size="small" color="#a1a1aa" />
                  <Button.Label>Marking...</Button.Label>
                </View>
              ) : (
                <Button.Label>Mark all read</Button.Label>
              )}
            </Button>
          </View>
        )}

        {/* Scrollable notification list — web caps at 60vh; mobile uses a
            fixed pixel cap that fits the chat bubble. */}
        <ScrollView
          style={{ maxHeight: 480 }}
          nestedScrollEnabled
          showsVerticalScrollIndicator={false}
        >
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
                onMarkAsRead={handleMarkAsRead}
                onAction={handleExecuteAction}
              />
            ))}
          </View>
        </ScrollView>

        {/* Footer — unread summary */}
        {unreadCount > 0 && (
          <View>
            <View className="h-px bg-zinc-700" />
            <Text className="mt-3 text-sm text-zinc-400">
              {unreadCount} unread notification{unreadCount !== 1 ? "s" : ""}
            </Text>
          </View>
        )}
      </View>
    </CollapsibleCard>
  );
}
