"use client";

import {
  ArrowUpRight01Icon,
  ChatBotIcon,
  Delete02Icon,
  Mail01Icon,
  MessageMultiple02Icon,
  MessageNotificationIcon,
  PencilEdit02Icon,
  StarIcon,
} from "@icons";
import { SystemPurpose } from "@/features/chat/api/chatApi";
import type { ChatActions } from "@/features/chat/hooks/useChatActions";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { ACTION_ICON, ICON } from "../model/constants";
import { relativeTime } from "../model/format";
import type { BuildCtx, CommandAction, CommandItem } from "../model/types";

export interface ChatLike {
  conversation_id: string;
  title: string;
  description?: string;
  starred?: boolean;
  is_unread?: boolean;
  is_system_generated?: boolean;
  system_purpose?: SystemPurpose | null;
  updatedAt?: Date;
  messageCount?: number;
}

/** Mirror ChatTab: bot chats use ChatBotIcon, email-processing uses Mail. */
function chatIcon(conv: ChatLike) {
  if (conv.is_system_generated) {
    if (conv.system_purpose === SystemPurpose.EMAIL_PROCESSING)
      return <Mail01Icon {...ICON} />;
    return <ChatBotIcon {...ICON} />;
  }
  return <MessageMultiple02Icon {...ICON} />;
}

/**
 * Build a single chat row. `full` controls whether state-dependent actions
 * (star / read) are offered — server search hits lack that state, so they only
 * get rename + delete.
 */
export function makeChatItem(
  conv: ChatLike,
  ctx: BuildCtx,
  actions: ChatActions,
  full = true,
): CommandItem {
  const id = conv.conversation_id;
  const rename: CommandAction = {
    id: "rename",
    label: "Rename",
    icon: <PencilEdit02Icon {...ACTION_ICON} />,
    form: {
      placeholder: "New chat name",
      initialValue: conv.title,
      submitLabel: "Rename",
      submit: (value) => actions.rename(id, value),
    },
  };
  const remove: CommandAction = {
    id: "delete",
    label: "Delete chat",
    icon: <Delete02Icon {...ACTION_ICON} />,
    destructive: true,
    run: async () => {
      const ok = await ctx.host.confirm({
        title: "Delete chat",
        message: "Delete this chat? This cannot be undone.",
        confirmText: "Delete",
        variant: "destructive",
      });
      if (!ok) return;
      ctx.host.close();
      await actions.remove(id);
    },
  };
  const star: CommandAction = {
    id: "star",
    label: conv.starred ? "Remove star" : "Star chat",
    icon: <StarIcon {...ACTION_ICON} />,
    run: () => actions.toggleStar(id, Boolean(conv.starred)),
  };
  const read: CommandAction = {
    id: "read",
    label: conv.is_unread ? "Mark as read" : "Mark as unread",
    icon: <MessageNotificationIcon {...ACTION_ICON} />,
    run: () => actions.toggleRead(id, Boolean(conv.is_unread)),
  };

  return {
    id: `chat:${id}`,
    type: "chat",
    title: conv.title || "Untitled chat",
    subtitle: conv.updatedAt
      ? relativeTime(conv.updatedAt) +
        (conv.messageCount ? ` · ${conv.messageCount} messages` : "")
      : "Conversation",
    icon: chatIcon(conv),
    keywords: conv.description ?? "",
    dot: conv.is_unread ? { color: "blue", label: "Unread" } : undefined,
    accessory: conv.starred ? (
      <StarIcon width={14} height={14} className="text-amber-400" />
    ) : undefined,
    primary: {
      id: "open",
      label: "Open chat",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: ctx.navigate(`/c/${id}`),
    },
    actions: full ? [rename, star, read, remove] : [rename, remove],
  };
}

/** A message search hit — opens its conversation. */
export function makeMessageItem(
  msg: { conversation_id: string; message_id: string; snippet: string },
  ctx: BuildCtx,
): CommandItem {
  return {
    id: `message:${msg.message_id}`,
    type: "message",
    title: msg.snippet,
    subtitle: "Message",
    icon: <MessageMultiple02Icon {...ICON} />,
    primary: {
      id: "open",
      label: "Open conversation",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: () => {
        trackEvent(ANALYTICS_EVENTS.SEARCH_RESULT_CLICKED, {
          result_type: "message",
          conversation_id: msg.conversation_id,
          message_id: msg.message_id,
        });
        ctx.navigate(`/c/${msg.conversation_id}`)();
      },
    },
    actions: [],
  };
}
