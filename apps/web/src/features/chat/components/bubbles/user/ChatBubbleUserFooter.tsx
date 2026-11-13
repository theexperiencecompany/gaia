import { Button } from "@heroui/button";
import { RedoIcon } from "@icons";

import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import ChatBubble_Actions from "../actions/ChatBubble_Actions";

interface ChatBubbleUserFooterProps {
  text: ChatBubbleUserProps["text"];
  date: ChatBubbleUserProps["date"];
  message_id: ChatBubbleUserProps["message_id"];
  queued: ChatBubbleUserProps["queued"];
  failed: ChatBubbleUserProps["failed"];
  onRetry: ChatBubbleUserProps["onRetry"];
  isRetrying: ChatBubbleUserProps["isRetrying"];
  disableActions: boolean;
  hideAvatar: boolean;
}

export function ChatBubbleUserFooter({
  text,
  date,
  message_id,
  queued,
  failed,
  onRetry,
  isRetrying,
  disableActions,
  hideAvatar,
}: ChatBubbleUserFooterProps) {
  if (disableActions) return null;

  // Queued: show a persistent "Queued" label, no date or actions.
  if (queued)
    return (
      <div
        className={`flex flex-col items-end gap-1 ${hideAvatar ? "pr-1" : "pr-13"} pb-1`}
      >
        <span className="text-xs text-zinc-400 select-none">Queued</span>
      </div>
    );

  // Undelivered: a persistent label + retry, not the hover-only actions
  // row — a send that never landed must be visible without hovering.
  if (failed)
    return (
      <div
        className={`flex items-center gap-2 ${hideAvatar ? "pr-1" : "pr-13"} pb-1`}
      >
        <span className="text-xs text-zinc-400 select-none">Not delivered</span>
        {onRetry && (
          <Button
            className="h-7 min-w-0 px-2 text-xs"
            isDisabled={isRetrying}
            onPress={onRetry}
            radius="full"
            size="sm"
            startContent={
              <div className={isRetrying ? "animate-spin" : ""}>
                <RedoIcon height={13} width={13} />
              </div>
            }
            variant="flat"
          >
            Retry
          </Button>
        )}
      </div>
    );

  // Actions row below bubble, aligned under content (not avatar)
  return (
    <div
      className={`flex flex-col items-end gap-1 ${hideAvatar ? "pr-1" : "pr-13"} pb-1 opacity-0 transition-all group-hover:opacity-100`}
    >
      {date && (
        <span
          className="flex flex-col text-xs text-zinc-400 select-text"
          suppressHydrationWarning
        >
          {parseDate(date)}
        </span>
      )}
      {text && (
        <ChatBubble_Actions
          loading={false}
          text={text}
          message_id={message_id}
          messageRole="user"
          onRetry={onRetry}
          isRetrying={isRetrying}
        />
      )}
    </div>
  );
}
