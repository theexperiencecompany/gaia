"use client";

import { Card } from "@heroui/react";
import { ArrowDown01Icon, ArrowLeft01Icon } from "@icons";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
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
  const cardRef = useRef<HTMLDivElement | null>(null);
  const hasTrackedRef = useRef(false);

  useEffect(() => {
    hasTrackedRef.current = false;

    if (typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    if (!("IntersectionObserver" in window)) {
      trackEvent(ANALYTICS_EVENTS.NOTIFICATION_VIEWED, {
        notification_id: notification.id,
        notification_source: notification.source,
      });
      hasTrackedRef.current = true;
      return;
    }

    const element = cardRef.current;
    if (!element) return;

    const observer = new IntersectionObserver((entries) => {
      const [entry] = entries;
      if (!entry?.isIntersecting || hasTrackedRef.current) return;

      trackEvent(ANALYTICS_EVENTS.NOTIFICATION_VIEWED, {
        notification_id: notification.id,
        notification_source: notification.source,
      });
      hasTrackedRef.current = true;
      observer.disconnect();
    });

    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [notification.id, notification.source]);

  return (
    <div ref={cardRef}>
      <Card className="w-full rounded-2xl border-none bg-zinc-800 p-4">
        <div className="flex items-start gap-3">
          <div className="mt-1 flex-shrink-0 text-zinc-400">
            {getNotificationIcon(notification.source)}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h3 className="mb-1 text-medium text-white">
                  {notification.title}
                </h3>
                <p className="text-sm whitespace-pre-line text-zinc-300">
                  {notification.description}
                </p>
              </div>
              <span className="flex-shrink-0 text-xs text-zinc-400">
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
                        ? "bg-zinc-700 text-white hover:bg-zinc-600"
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
                    className="bg-zinc-700 text-white hover:bg-zinc-600"
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
                  className="text-zinc-400 hover:text-white"
                >
                  Mark as Read
                </Button>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};
