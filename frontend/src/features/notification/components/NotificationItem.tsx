import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/react";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useConfirmation } from "@/hooks/useConfirmation";
import { CheckmarkBadge01Icon } from '@/icons';

import {
  NotificationAction,
  NotificationRecord,
  NotificationStatus,
} from "../../../types/features/notificationTypes";

interface NotificationItemProps {
  notification: NotificationRecord;
  onMarkAsRead: (id: string) => void;
}

export const NotificationItem = ({
  notification,
  onMarkAsRead,
}: NotificationItemProps) => {
  const { confirm, confirmationProps } = useConfirmation();
  const [executingActionId, setExecutingActionId] = useState<string | null>(
    null,
  );

  // Access content directly from notification
  const content = notification.content || {
    title: "Notification",
    body: "No details available",
    actions: [],
  };

  const isUnread = notification.status === NotificationStatus.DELIVERED;

  return (
    <div className={`w-full rounded-2xl bg-zinc-900 p-4`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h4 className="max-w-[250px] truncate text-sm font-medium text-zinc-100">
              {content.title}
            </h4>
            {isUnread && (
              <div className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />
            )}
          </div>
          <p className="my-1 line-clamp-2 text-left text-sm font-light break-words text-zinc-400">
            {content.body}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-zinc-600">
            <span className="capitalize">
              {formatDistanceToNow(new Date(notification.created_at), {
                addSuffix: true,
              })}
            </span>
            <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 capitalize">
              {notification.metadata?.reminder_id ? "reminder" : "system"}
            </span>
          </div>
        </div>

        {isUnread && (
          <div className="flex flex-shrink-0 items-center gap-1">
            <Tooltip content="Mark as Read">
              <Button
                variant="flat"
                size="sm"
                isIconOnly
                onPress={() => onMarkAsRead(notification.id)}
                title="Mark as read"
              >
                <CheckmarkBadge01Icon className="h-3.5 w-3.5" />
              </Button>
            </Tooltip>
          </div>
        )}
      </div>

      {/* Actions buttons if present */}
      {content.actions &&
        Array.isArray(content.actions) &&
        content.actions.length > 0 && (
          <div className="mt-3 flex gap-2">
            {content.actions.map((action: NotificationAction) => {
              const isExecuted = action.executed || false;
              const isCurrentlyExecuting = executingActionId === action.id;
              const isDisabled =
                action.disabled || isExecuted || isCurrentlyExecuting;

              return (
                <Button
                  key={action.id}
                  variant={action.style === "primary" ? "solid" : "flat"}
                  size="sm"
                  className={`h-7 bg-zinc-800/50 text-xs text-zinc-200 hover:bg-zinc-800/70 ${
                    isExecuted ? "cursor-not-allowed opacity-50" : ""
                  }`}
                  disabled={isDisabled}
                  onPress={async () => {
                    if (isDisabled) return;

                    try {
                      if (
                        action.requires_confirmation &&
                        action.confirmation_message
                      ) {
                        const confirmed = await confirm({
                          title: "Confirm Action",
                          message: action.confirmation_message,
                          confirmText: "Continue",
                          cancelText: "Cancel",
                          variant:
                            action.style === "danger"
                              ? "destructive"
                              : "default",
                        });
                        if (!confirmed) return;
                      }

                      setExecutingActionId(action.id);

                      const { NotificationsAPI } = await import(
                        "@/services/api/notifications"
                      );
                      const result = await NotificationsAPI.executeAction(
                        notification.id,
                        action.id,
                      );

                      if (result.success) {
                        toast.success(
                          result.message || "Action executed successfully",
                        );
                        // Optionally trigger a refresh here if needed
                      } else {
                        toast.error(
                          result.message || "Failed to execute action",
                        );
                      }
                    } catch (error) {
                      console.error("Action execution failed:", error);
                      toast.error("Failed to execute action");
                    } finally {
                      setExecutingActionId(null);
                    }
                  }}
                >
                  {isCurrentlyExecuting ? (
                    <div className="flex items-center gap-1">
                      <div className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
                      <span>Processing...</span>
                    </div>
                  ) : (
                    <>
                      {action.label}
                      {isExecuted && <span className="ml-1">✓</span>}
                    </>
                  )}
                </Button>
              );
            })}
          </div>
        )}

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
