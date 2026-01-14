import Image from "next/image";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { useUser } from "@/features/auth/hooks/useUser";
import SelectedCalendarEventIndicator from "@/features/chat/components/composer/SelectedCalendarEventIndicator";
import SelectedReplyIndicator from "@/features/chat/components/composer/SelectedReplyIndicator";
import SelectedToolIndicator from "@/features/chat/components/composer/SelectedToolIndicator";
import SelectedWorkflowIndicator from "@/features/chat/components/composer/SelectedWorkflowIndicator";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import ChatBubble_Actions from "../actions/ChatBubble_Actions";
import ChatBubbleFilePreview from "./ChatBubbleFilePreview";

export default function ChatBubbleUser({
  text,
  date,
  message_id,
  fileData = [],
  selectedTool,
  toolCategory,
  selectedWorkflow,
  selectedCalendarEvent,
  replyToMessage,
  disableActions = false,
}: ChatBubbleUserProps & { disableActions?: boolean }) {
  const hasContent =
    !!text ||
    fileData.length > 0 ||
    !!selectedTool ||
    !!selectedWorkflow ||
    !!selectedCalendarEvent;

  const user = useUser();

  if (!hasContent) return null;

  // Calculate emoji state
  const isEmojiOnly = isOnlyEmojis(text);
  const emojiCount = isEmojiOnly ? getEmojiCount(text) : 0;

  // Determine styles based on emoji count
  let bubbleClassName = "imessage-bubble imessage-from-me";
  let textClassName =
    "flex max-w-[30vw] text-wrap whitespace-pre-wrap select-text";

  if (isEmojiOnly) {
    if (emojiCount === 1) {
      bubbleClassName = "select-none"; // No bubble background
      textClassName += " text-5xl leading-none";
    } else if (emojiCount === 2) textClassName += " text-4xl";
    else if (emojiCount === 3) textClassName += " text-3xl";
  }

  return (
    <div className="flex w-full items-end justify-end gap-3">
      <div className="chat_bubble_container user group" id={message_id}>
        {fileData.length > 0 && <ChatBubbleFilePreview files={fileData} />}

        {selectedTool && (
          <div className="flex justify-end">
            <SelectedToolIndicator
              toolName={selectedTool}
              toolCategory={toolCategory}
            />
          </div>
        )}

        {selectedWorkflow && (
          <div className="flex justify-end">
            <SelectedWorkflowIndicator workflow={selectedWorkflow} />
          </div>
        )}

        {selectedCalendarEvent && (
          <div className="flex justify-end">
            <SelectedCalendarEventIndicator event={selectedCalendarEvent} />
          </div>
        )}

        {replyToMessage && (
          <div className="flex justify-end">
            <SelectedReplyIndicator
              replyToMessage={replyToMessage}
              isDisplayOnly={true}
              onNavigate={(messageId) => {
                const messageElement = document.getElementById(messageId);
                if (messageElement) {
                  messageElement.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                  });
                  messageElement.style.transition = "all 0.3s ease";
                  messageElement.style.scale = "1.02";
                  setTimeout(() => {
                    messageElement.style.scale = "1";
                  }, 300);
                }
              }}
            />
          </div>
        )}

        {text?.trim() && (
          <div className={bubbleClassName}>
            {!!text && <div className={textClassName}>{text}</div>}
          </div>
        )}

        <div
          className={`flex flex-col items-end justify-end gap-1 pb-3 transition-all ${disableActions ? "hidden" : "opacity-0 group-hover:opacity-100"}`}
        >
          {date && (
            <span className="flex flex-col text-xs text-foreground-400 select-text">
              {parseDate(date)}
            </span>
          )}

          {text && !disableActions && (
            <ChatBubble_Actions
              loading={false}
              text={text}
              message_id={message_id}
              messageRole="user"
            />
          )}
        </div>
      </div>
      <div className="min-w-10">
        <Avatar
          className={`relative rounded-full bg-surface-50 ${disableActions ? "bottom-0" : "bottom-18"}`}
        >
          <AvatarImage src={user?.profilePicture} alt="User Avatar" />
          <AvatarFallback>
            <Image
              src={"/images/avatars/default.webp"}
              width={35}
              height={35}
              alt="Default profile picture"
            />
          </AvatarFallback>
        </Avatar>
      </div>
    </div>
  );
}
