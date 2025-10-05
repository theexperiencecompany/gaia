"use client";

import { Button as HeroButton } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  AlertCircle,
  CheckCheck,
  CheckCircle,
  Clock,
  ExternalLink,
} from "lucide-react";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useNotificationActions } from "@/hooks/useNotificationActions";
import {
  ActionType,
  ModalConfig,
  NotificationRecord,
  NotificationStatus,
} from "@/types/features/notificationTypes";
import { parseDate } from "@/utils/date/dateUtils";

import { Button } from "../../../components/ui";

interface EnhancedNotificationCardProps {
  notification: NotificationRecord;
  onMarkAsRead?: (id: string) => Promise<void>;
  onModalOpen?: (config: ModalConfig) => void;
  onRefresh?: () => void;
}

export const EnhancedNotificationCard = ({
  notification,
  onMarkAsRead,
  onModalOpen,
  onRefresh,
}: EnhancedNotificationCardProps) => {
  const [executingActionId, setExecutingActionId] = useState<string | null>(
    null,
  );

  const { executeAction, loading, getActionButtonProps, confirmationProps } =
    useNotificationActions({
      onSuccess: () => {
        // Refresh the notifications list if an action was successful
        onRefresh?.();
      },
      onModalOpen: (config) => {
        onModalOpen?.(config);
      },
    });

  const handleActionClick = async (actionId: string) => {
    const action = notification.content.actions?.find((a) => a.id === actionId);
    if (!action) return;

    setExecutingActionId(notification.id);
    try {
      await executeAction(notification.id, action);
    } finally {
      setExecutingActionId(null);
    }
  };

  const handleMarkAsRead = async () => {
    if (onMarkAsRead) {
      await onMarkAsRead(notification.id);
    }
  };

  const getActionIcon = (actionType: ActionType) => {
    switch (actionType) {
      case "redirect":
        return <ExternalLink className="h-3 w-3" strokeWidth={2.5} />;
      case "api_call":
        return <CheckCircle className="h-3 w-3" strokeWidth={2.5} />;
      case "workflow":
        return <Clock className="h-3 w-3" strokeWidth={2.5} />;
      case "modal":
        return <AlertCircle className="h-3 w-3" strokeWidth={2.5} />;
      default:
        return null;
    }
  };

  const formattedDate = parseDate(notification.created_at);
  const isUnread = notification.status === NotificationStatus.DELIVERED;

  return (
    <div
      className={`group relative w-full rounded-xl transition-all ${
        isUnread ? "bg-zinc-800/70" : "bg-zinc-900/40"
      }`}
    >
      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-3">
          {/* Main content */}
          <div className="min-w-0 flex-1 space-y-1">
            {/* Title with unread indicator */}
            <div className="flex items-center gap-2">
              <h3 className="text-[15px] leading-tight font-semibold text-white">
                {notification.content.title}
              </h3>
              {isUnread && (
                <div className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />
              )}
            </div>

            {/* Description */}
            <p className="text-[13px] leading-relaxed text-zinc-400">
              {notification.content.body}
            </p>

            {/* Date */}
            <span className="inline-block text-[11px] text-zinc-600">
              {formattedDate}
            </span>
          </div>

          {/* Mark as read button */}
          {notification.status !== NotificationStatus.READ &&
            notification.status !== NotificationStatus.ARCHIVED && (
              <Tooltip content="Mark as read" delay={300}>
                <HeroButton
                  size="sm"
                  onPress={handleMarkAsRead}
                  variant="light"
                  isIconOnly
                  className="h-8 w-8 min-w-8 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                >
                  <CheckCheck className="h-4 w-4 text-zinc-500" />
                </HeroButton>
              </Tooltip>
            )}
        </div>

        {/* Actions */}
        {notification?.content?.actions &&
          notification?.content?.actions.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {notification.content.actions.map((action) => {
                const buttonProps = getActionButtonProps(action);
                const isLoading =
                  loading === action.id || executingActionId === action.id;
                const isExecuted = action.executed || false;

                // Don't show loading for modal actions
                const showLoading = isLoading && action.type !== "modal";

                return (
                  <Button
                    key={action.id}
                    size="sm"
                    disabled={buttonProps.disabled || isLoading || isExecuted}
                    onClick={() => handleActionClick(action.id)}
                    className={`h-8 gap-1.5 rounded-md px-3 text-xs font-medium transition-all ${
                      action.style === "primary"
                        ? "bg-primary/10 text-primary hover:bg-primary/20"
                        : action.style === "danger"
                          ? "bg-red-500/10 text-red-500 hover:bg-red-500/20"
                          : "bg-zinc-800/50 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
                    } ${showLoading ? "opacity-50" : ""} ${
                      isExecuted ? "cursor-not-allowed opacity-60" : ""
                    }`}
                  >
                    {showLoading ? (
                      <div className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
                    ) : (
                      <>
                        <span>{action.label}</span>
                        {isExecuted && (
                          <CheckCircle className="h-3 w-3" strokeWidth={2.5} />
                        )}
                        {!isExecuted && getActionIcon(action.type)}
                      </>
                    )}
                  </Button>
                );
              })}
            </div>
          )}
      </div>

      {/* Confirmation Dialog */}
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
