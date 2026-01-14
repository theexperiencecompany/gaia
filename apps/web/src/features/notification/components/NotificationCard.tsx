"use client";

import { Card } from "@heroui/react";

import { Button } from "@/components/ui/button";
import { ArrowDown01Icon, ArrowLeft01Icon } from "@/icons";
import type { Notification } from "@/types/notifications";
import { getNotificationIcon } from "@/utils/notifications";

interface NotificationCardProps {
  notification: Notification;
  onAction: (
    notification: Notification,
    actionType: string,
    actionId?: string,
  ) => void;
}

export const NotificationCard = ({
  notification,
  onAction,
}: NotificationCardProps) => {
  return (
    <Card className="w-full rounded-2xl border-none bg-surface-200 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-1 flex-shrink-0 text-foreground-400">
          {getNotificationIcon(notification.source)}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <h3 className="mb-1 text-medium text-white">
                {notification.title}
              </h3>
              <p className="text-sm whitespace-pre-line text-foreground-300">
                {notification.description}
              </p>
            </div>
            <span className="flex-shrink-0 text-xs text-foreground-400">
              {notification.timestamp}
            </span>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <div className="flex items-center gap-2">
              {notification.actions.primary && (
                <Button
                  size="sm"
                  onClick={() =>
                    onAction(
                      notification,
                      notification.actions.primary?.label || "",
                      notification.actions.primary?.actionId,
                    )
                  }
                  variant={notification.actions.primary.variant || "default"}
                  className={
                    notification.actions.primary.variant === "secondary"
                      ? "bg-surface-700 text-white hover:bg-surface-600"
                      : ""
                  }
                >
                  {notification.actions.primary.label}
                </Button>
              )}
              {notification.actions.secondary && (
                <Button
                  size="sm"
                  onClick={() =>
                    onAction(
                      notification,
                      notification.actions.secondary?.label || "",
                      notification.actions.secondary?.actionId,
                    )
                  }
                  variant="secondary"
                  className="bg-surface-700 text-white hover:bg-surface-600"
                >
                  {notification.actions.secondary.label}
                  {notification.actions.secondary.label === "Snooze" && (
                    <ArrowDown01Icon className="ml-1 h-3 w-3" />
                  )}
                  {notification.actions.secondary.label === "Undo" && (
                    <ArrowLeft01Icon className="ml-1 h-3 w-3" />
                  )}
                </Button>
              )}
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onAction(notification, "mark as read")}
                className="text-foreground-400 hover:text-white"
              >
                Mark as Read
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
};
