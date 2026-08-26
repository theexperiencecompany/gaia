"use client";

import {
  Archive02Icon,
  ArrowUpRight01Icon,
  FlashIcon,
  Maximize01Icon,
  NotificationIcon,
  Tick02Icon,
  ZapIcon,
} from "@icons";
import type { ReactNode } from "react";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import {
  ActionType,
  type NotificationAction,
  type NotificationRecord,
} from "@/types/features/notificationTypes";
import { ACTION_ICON, ICON } from "../model/constants";
import { relativeTime } from "../model/format";
import type { BuildCtx, CommandAction, CommandItem } from "../model/types";

const NOTIF_UNREAD = "delivered";

interface NotificationDeps {
  markAsRead: (id: string) => Promise<void>;
  archiveNotification: (id: string) => Promise<void>;
}

/** Icon by action type — reuses the NotificationActionType enum. */
function actionIcon(type: NotificationAction["type"]): ReactNode {
  switch (type) {
    case ActionType.REDIRECT:
      return <ArrowUpRight01Icon {...ACTION_ICON} />;
    case ActionType.API_CALL:
      return <FlashIcon {...ACTION_ICON} />;
    case ActionType.WORKFLOW:
      return <ZapIcon {...ACTION_ICON} />;
    case ActionType.MODAL:
      return <Maximize01Icon {...ACTION_ICON} />;
    default:
      return <ArrowUpRight01Icon {...ACTION_ICON} />;
  }
}

/** Turn a notification's own action into a runnable command action. */
function toCommandAction(
  notificationId: string,
  action: NotificationAction,
  ctx: BuildCtx,
): CommandAction {
  return {
    id: `notif-action:${action.id}`,
    label: action.label,
    icon: actionIcon(action.type),
    run: async () => {
      if (action.type === ActionType.REDIRECT) {
        const cfg = action.config.redirect;
        if (!cfg?.url) return;
        ctx.host.close();
        if (cfg.open_in_new_tab) window.open(cfg.url, "_blank", "noopener");
        else if (/^https?:\/\//.test(cfg.url)) window.location.href = cfg.url;
        else ctx.navigate(cfg.url)();
        return;
      }
      // api_call / workflow / modal all run server-side via executeAction.
      ctx.host.close();
      const result = await NotificationsAPI.executeAction(
        notificationId,
        action.id,
      );
      if (result.success) toast.success(result.message || "Action executed");
      else toast.error(result.message || "Action failed");
    },
  };
}

export const buildNotificationItems = (
  notifications: NotificationRecord[],
  ctx: BuildCtx,
  deps: NotificationDeps,
): CommandItem[] =>
  notifications.map((n) => {
    const isUnread = n.status === NOTIF_UNREAD;
    const notifActions = (n.content.actions ?? []).map((a) =>
      toCommandAction(n.id, a, ctx),
    );
    const openInbox: CommandAction = {
      id: "open",
      label: "Open notifications",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: ctx.navigate("/notifications"),
    };
    const read: CommandAction = {
      id: "read",
      label: "Mark as read",
      icon: <Tick02Icon {...ACTION_ICON} />,
      run: () => deps.markAsRead(n.id),
    };
    const archive: CommandAction = {
      id: "archive",
      label: "Archive",
      icon: <Archive02Icon {...ACTION_ICON} />,
      run: () => deps.archiveNotification(n.id),
    };

    // Primary = the notification's own first action when present, else open inbox.
    const [primaryAction, ...restNotifActions] = notifActions;
    const primary = primaryAction ?? openInbox;
    const secondary: CommandAction[] = [
      ...restNotifActions,
      ...(primaryAction ? [openInbox] : []),
      ...(isUnread ? [read] : []),
      archive,
    ];

    return {
      id: `notification:${n.id}`,
      type: "notification",
      title: n.content.title,
      subtitle: `${n.content.body} · ${relativeTime(new Date(n.created_at))}`,
      icon: <NotificationIcon {...ICON} />,
      keywords: n.type,
      dot: isUnread ? { color: "blue", label: "Unread" } : undefined,
      primary,
      actions: secondary,
    };
  });
