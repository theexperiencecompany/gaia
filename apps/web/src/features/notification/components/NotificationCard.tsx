"use client";

import { Button } from "@heroui/button";
import { CheckmarkCircle02Icon, LinkSquare02Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useNotificationActions } from "@/hooks/useNotificationActions";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import {
  ActionStyle,
  ActionType,
  type ModalConfig,
  type NotificationAction,
  type NotificationRecord,
  NotificationStatus,
} from "@/types/features/notificationTypes";

interface NotificationCardProps {
  notification: NotificationRecord;
  /**
   * Surface the card sits on: "raised" (zinc-800 card on the page background
   * or a zinc-900 panel) or "inset" (zinc-900 card inside a zinc-800 surface,
   * e.g. chat tool cards).
   */
  tone?: "raised" | "inset";
  /** Clamp the body to two lines in dense contexts (popover, chat). */
  clampBody?: boolean;
  onMarkAsRead?: (id: string) => void | Promise<void>;
  onModalOpen?: (config: ModalConfig) => void;
  onRefresh?: () => void;
}

const ACTION_BUTTON_COLOR: Record<
  ActionStyle,
  "primary" | "danger" | "default"
> = {
  [ActionStyle.PRIMARY]: "primary",
  [ActionStyle.DANGER]: "danger",
  [ActionStyle.SECONDARY]: "default",
};

export const NotificationCard = ({
  notification,
  tone = "raised",
  clampBody = false,
  onMarkAsRead,
  onModalOpen,
  onRefresh,
}: NotificationCardProps) => {
  const { executeAction, loading, confirmationProps } = useNotificationActions({
    onSuccess: () => onRefresh?.(),
    onModalOpen,
  });

  const { title, body, actions = [] } = notification.content;
  const isUnread = notification.status === NotificationStatus.DELIVERED;

  const handleActionPress = async (action: NotificationAction) => {
    trackEvent(ANALYTICS_EVENTS.NOTIFICATION_CLICKED, {
      notification_id: notification.id,
      action_id: action.id,
      action_type: action.type,
    });
    await executeAction(notification.id, action);
  };

  const handleMarkAsRead = async () => {
    trackEvent(ANALYTICS_EVENTS.NOTIFICATION_DISMISSED, {
      notification_id: notification.id,
    });
    await onMarkAsRead?.(notification.id);
  };

  const surface =
    tone === "raised"
      ? isUnread
        ? "bg-zinc-800"
        : "bg-zinc-800/40"
      : isUnread
        ? "bg-zinc-900"
        : "bg-zinc-900/40";

  return (
    <div className={`w-full rounded-2xl p-4 transition-colors ${surface}`}>
      <div className="min-w-0">
        <div className="flex min-h-6 items-center gap-2">
          <h3
            className={`truncate text-sm font-medium ${isUnread ? "text-zinc-100" : "text-zinc-400"}`}
          >
            {title}
          </h3>
          {isUnread && (
            <span className="size-1.5 shrink-0 rounded-full bg-primary" />
          )}
          <span
            className="shrink-0 text-xs whitespace-nowrap text-zinc-500"
            suppressHydrationWarning
          >
            {formatDistanceToNow(new Date(notification.created_at), {
              addSuffix: true,
            })}
          </span>
        </div>
        <p
          className={`mt-0.5 text-sm ${clampBody ? "line-clamp-2" : ""} ${isUnread ? "text-zinc-400" : "text-zinc-500"}`}
        >
          {body}
        </p>
      </div>

      {(actions.length > 0 || (isUnread && onMarkAsRead)) && (
        <div
          className={`mt-3 flex flex-wrap items-center gap-2 ${isUnread ? "" : "opacity-70"}`}
        >
          {actions.map((action) => {
            const isExecuted = Boolean(action.executed);
            const isLoading = loading === action.id;

            return (
              <Button
                key={action.id}
                size="sm"
                variant="flat"
                color={
                  ACTION_BUTTON_COLOR[action.style ?? ActionStyle.SECONDARY]
                }
                className="rounded-xl"
                isDisabled={action.disabled || isExecuted || isLoading}
                isLoading={isLoading}
                onPress={() => handleActionPress(action)}
                endContent={
                  isExecuted ? (
                    <CheckmarkCircle02Icon className="size-3.5" />
                  ) : action.type === ActionType.REDIRECT ? (
                    <LinkSquare02Icon className="size-3.5" />
                  ) : undefined
                }
              >
                {action.label}
              </Button>
            );
          })}
          {isUnread && onMarkAsRead && (
            <Button
              size="sm"
              variant="light"
              className="rounded-xl text-zinc-500"
              startContent={<CheckmarkCircle02Icon className="size-4" />}
              onPress={handleMarkAsRead}
            >
              Mark as read
            </Button>
          )}
        </div>
      )}

      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
