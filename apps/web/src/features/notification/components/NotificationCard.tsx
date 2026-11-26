"use client";

import {
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  LinkSquare02Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  GaiaButton,
  type GaiaButtonVariant,
} from "@/components/shared/GaiaButton";
import {
  NESTED_TONE,
  type SurfaceTone,
  surfaceVariants,
} from "@/components/shared/surfaceVariants";
import {
  BriefingFold,
  briefPath,
  FoldedBriefCard,
  foldedBrief,
  notificationBrief,
} from "@/features/briefing";
import { MarkdownRenderer } from "@/features/chat";
import { useNotificationActions } from "@/hooks/useNotificationActions";
import { cn } from "@/lib/utils";
import {
  ActionStyle,
  ActionType,
  type NotificationAction,
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

interface NotificationCardProps {
  notification: NotificationView;
  /**
   * Surface the card sits on: "raised" (zinc-800 card on the page background
   * or a zinc-900 panel) or "inset" (zinc-900 card inside a zinc-800 surface,
   * e.g. chat tool cards).
   */
  tone?: SurfaceTone;
  /** Clamp the body to two lines in dense contexts (popover, chat). */
  clampBody?: boolean;
  onMarkAsRead?: (id: string) => void | Promise<void>;
  onRefresh?: () => void;
}

const ACTION_BUTTON_VARIANT: Record<ActionStyle, GaiaButtonVariant> = {
  [ActionStyle.PRIMARY]: "accent-soft",
  [ActionStyle.DANGER]: "danger-soft",
  [ActionStyle.SECONDARY]: "default-soft",
};

// The folded brief below already carries the headline, so the header names the kind.
const BRIEF_LABEL = "Briefing";

/** Done actions show a check; a redirect shows where it goes, out of GAIA (a new tab or another site) or within it. */
function actionIcon(action: NotificationAction) {
  if (action.executed) return <CheckmarkCircle02Icon className="size-3.5" />;
  const redirect = action.config?.redirect;
  if (action.type !== ActionType.REDIRECT || !redirect) return undefined;
  const leavesApp =
    Boolean(redirect.open_in_new_tab) || /^https?:\/\//.test(redirect.url);
  return leavesApp ? (
    <LinkSquare02Icon className="size-3.5" />
  ) : (
    <ArrowRight01Icon className="size-3.5" />
  );
}

/** The folded card already opens its brief, so an action pointing at that same brief is left out. */
function opensBrief(action: NotificationAction, briefingId: string): boolean {
  return action.config?.redirect?.url === briefPath(briefingId);
}

export const NotificationCard = ({
  notification,
  tone = "raised",
  clampBody = false,
  onMarkAsRead,
  onRefresh,
}: NotificationCardProps) => {
  const { executeAction, loading, confirmationProps } = useNotificationActions({
    onSuccess: () => onRefresh?.(),
  });

  const { title, body } = notification.content;
  const card = notificationBrief(notification);
  const actions = (notification.content.actions ?? []).filter(
    (action) => !card || !opensBrief(action, card.briefing_id),
  );
  const isUnread = notification.status === NotificationStatus.DELIVERED;

  const handleActionPress = async (action: NotificationAction) => {
    await executeAction(notification.id, action);
  };

  const handleMarkAsRead = async () => {
    await onMarkAsRead?.(notification.id);
  };

  return (
    <div
      className={surfaceVariants({
        tone,
        className: "w-full rounded-2xl p-4",
      })}
    >
      <div className="min-w-0">
        <div className="flex min-h-6 items-center gap-2">
          <h3
            className={cn(
              "min-w-0 truncate text-sm font-medium",
              isUnread ? "text-zinc-100" : "text-zinc-400",
            )}
          >
            {card ? BRIEF_LABEL : title}
          </h3>
          {isUnread && (
            <span
              role="img"
              aria-label="Unread"
              className="size-1.5 shrink-0 rounded-full bg-accent"
            />
          )}
          <span
            className="ml-auto shrink-0 text-xs whitespace-nowrap text-zinc-500 tabular-nums"
            suppressHydrationWarning
          >
            {formatDistanceToNow(new Date(notification.created_at), {
              addSuffix: true,
            })}
          </span>
        </div>
        {card ? (
          <div className="mt-3 w-full max-w-56">
            <BriefingFold
              brief={foldedBrief(card)}
              briefingId={card.briefing_id}
            >
              {(trigger) => (
                <FoldedBriefCard
                  brief={foldedBrief(card)}
                  tone={NESTED_TONE[tone]}
                  trigger={trigger}
                />
              )}
            </BriefingFold>
          </div>
        ) : (
          <MarkdownRenderer
            content={body}
            className={cn(
              "mt-1 text-sm",
              clampBody && "line-clamp-2",
              isUnread ? "text-zinc-400" : "text-zinc-500",
            )}
            hideCodeToolbar
          />
        )}
      </div>

      {(actions.length > 0 || (isUnread && onMarkAsRead)) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {actions.map((action) => {
            const isExecuted = Boolean(action.executed);
            const isLoading = loading === action.id;

            return (
              <GaiaButton
                key={action.id}
                size="sm"
                variant={
                  ACTION_BUTTON_VARIANT[action.style ?? ActionStyle.SECONDARY]
                }
                shape="md"
                isDisabled={action.disabled || isExecuted || isLoading}
                isPending={isLoading}
                onPress={() => handleActionPress(action)}
              >
                {action.label}
                {actionIcon(action)}
              </GaiaButton>
            );
          })}
          {isUnread && onMarkAsRead && (
            <GaiaButton
              size="sm"
              variant="ghost"
              shape="md"
              tone="faint"
              onPress={handleMarkAsRead}
            >
              <CheckmarkCircle02Icon className="size-4" />
              Mark as read
            </GaiaButton>
          )}
        </div>
      )}

      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
};
