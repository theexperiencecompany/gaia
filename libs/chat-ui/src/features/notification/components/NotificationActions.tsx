"use client";

import { Delete02Icon } from "@icons";
import {
  LeadingActions,
  SwipeAction,
  TrailingActions,
} from "react-swipeable-list";
import type { Notification } from "@/types/notifications";
import { getActionColor, getActionIcon } from "@/utils/notifications";

interface NotificationActionsProps {
  notification: Notification;
  onAction: (
    notification: Notification,
    actionType: string,
    actionId?: string,
  ) => void;
}

export const NotificationLeadingActions = ({
  notification,
  onAction,
}: NotificationActionsProps) => {
  // Use primary action for leading swipe if available
  if (!notification.actions.primary) return null;

  const label = notification.actions.primary.label;

  return (
    <LeadingActions>
      <SwipeAction
        onClick={() =>
          onAction(notification, label, notification.actions.primary?.actionId)
        }
      >
        <div
          className={`flex h-full w-full items-center justify-center rounded-l-3xl ${getActionColor(label)} px-4`}
        >
          {getActionIcon(label)}
          <span className="text-white">{label}</span>
        </div>
      </SwipeAction>
    </LeadingActions>
  );
};

export const NotificationTrailingActions = ({
  notification,
  onAction,
}: NotificationActionsProps) => {
  return (
    <TrailingActions>
      {notification.actions.secondary && (
        <SwipeAction
          onClick={() =>
            onAction(
              notification,
              notification.actions.secondary?.label || "",
              notification.actions.secondary?.actionId,
            )
          }
        >
          <div
            className={`flex h-full w-full items-center justify-center ${getActionColor(notification.actions.secondary.label)} px-4`}
          >
            {getActionIcon(notification.actions.secondary.label)}
            <span className="text-white">
              {notification.actions.secondary.label}
            </span>
          </div>
        </SwipeAction>
      )}
      <SwipeAction
        destructive={true}
        onClick={() => onAction(notification, "dismiss")}
      >
        <div className="flex h-full w-full items-center justify-center rounded-r-3xl bg-red-600/90 px-4">
          <Delete02Icon className="mr-2 h-4 w-4 text-white" />
          <span className="text-white">Dismiss</span>
        </div>
      </SwipeAction>
    </TrailingActions>
  );
};
