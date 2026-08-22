import { Button } from "@heroui/button";
import { RedoIcon } from "@icons";
import Image from "next/image";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useUser } from "@/features/auth/hooks/useUser";
import SelectedCalendarEventIndicator from "@/features/chat/components/composer/SelectedCalendarEventIndicator";
import SelectedReplyIndicator from "@/features/chat/components/composer/SelectedReplyIndicator";
import SelectedToolIndicator from "@/features/chat/components/composer/SelectedToolIndicator";
import SelectedWorkflowIndicator from "@/features/chat/components/composer/SelectedWorkflowIndicator";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import type { FileData } from "@/types/shared/fileTypes";
import { parseDate } from "@/utils/date/dateUtils";

import ChatBubble_Actions from "../actions/ChatBubble_Actions";
import ChatBubbleFilePreview from "./ChatBubbleFilePreview";

const DEFAULT_FILE_DATA: FileData[] = [];

function scrollToMessage(messageId: string) {
  const messageElement = document.getElementById(messageId);
  if (!messageElement) return;
  messageElement.scrollIntoView({ behavior: "smooth", block: "center" });
  messageElement.style.transition = "scale 0.3s ease";
  messageElement.style.scale = "1.02";
  setTimeout(() => {
    messageElement.style.scale = "1";
  }, 300);
}

function resolveUserBubbleStyles(
  isEmojiOnly: boolean,
  emojiCount: number,
  fullWidth: boolean,
): { bubbleClassName: string; textClassName: string } {
  let bubbleClassName = "imessage-bubble imessage-from-me";
  let textClassName = `flex ${fullWidth ? "max-w-full" : "max-w-[30vw]"} text-wrap whitespace-pre-wrap select-text`;

  if (isEmojiOnly) {
    if (emojiCount === 1) {
      bubbleClassName = "select-none"; // No bubble background
      textClassName += " text-5xl leading-none";
    } else if (emojiCount === 2) textClassName += " text-4xl";
    else if (emojiCount === 3) textClassName += " text-3xl";
  }

  return { bubbleClassName, textClassName };
}

interface BubbleIndicatorsProps {
  fileData: FileData[];
  selectedTool: ChatBubbleUserProps["selectedTool"];
  toolCategory: ChatBubbleUserProps["toolCategory"];
  selectedWorkflow: ChatBubbleUserProps["selectedWorkflow"];
  selectedCalendarEvent: ChatBubbleUserProps["selectedCalendarEvent"];
  replyToMessage: ChatBubbleUserProps["replyToMessage"];
}

function BubbleIndicators({
  fileData,
  selectedTool,
  toolCategory,
  selectedWorkflow,
  selectedCalendarEvent,
  replyToMessage,
}: BubbleIndicatorsProps) {
  return (
    <>
      {fileData.length > 0 && <ChatBubbleFilePreview files={fileData} />}

      {selectedTool && (
        <div className="flex justify-end top-1.5 relative">
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
            onNavigate={scrollToMessage}
          />
        </div>
      )}
    </>
  );
}

export default function ChatBubbleUser({
  text,
  date,
  message_id,
  fileData = DEFAULT_FILE_DATA,
  selectedTool,
  toolCategory,
  selectedWorkflow,
  selectedCalendarEvent,
  replyToMessage,
  queued,
  failed,
  disableActions = false,
  onRetry,
  isRetrying,
  loading,
  hideAvatar = false,
  fullWidth = false,
}: ChatBubbleUserProps & {
  disableActions?: boolean;
  hideAvatar?: boolean;
  fullWidth?: boolean;
}) {
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
  const { bubbleClassName, textClassName } = resolveUserBubbleStyles(
    isEmojiOnly,
    emojiCount,
    fullWidth,
  );

  return (
    <div
      className="group flex w-full justify-end gap-3"
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 80px" }}
    >
      <div className="flex flex-col items-end gap-1">
        {/* Bubble content + avatar aligned at bottom */}
        <div className="flex items-end gap-1" id={message_id}>
          <div
            className={`chat_bubble_container user transition-opacity duration-300 ${
              queued ? "opacity-50" : "opacity-100"
            }`}
          >
            <BubbleIndicators
              fileData={fileData}
              selectedTool={selectedTool}
              toolCategory={toolCategory}
              selectedWorkflow={selectedWorkflow}
              selectedCalendarEvent={selectedCalendarEvent}
              replyToMessage={replyToMessage}
            />

            {text?.trim() && (
              <div className={bubbleClassName}>
                {isEmojiOnly ? (
                  <div className={textClassName}>{text}</div>
                ) : (
                  <div className="max-w-[30vw] select-text text-[15px]">
                    <MarkdownRenderer
                      content={text}
                      isStreaming={loading}
                      lightBackground
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {!hideAvatar && (
            <div className="min-w-10">
              <Avatar className="rounded-full bg-black">
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
          )}
        </div>

        {/* Queued: show a persistent "Queued" label, no date or actions. */}
        {!disableActions && queued && (
          <div
            className={`flex flex-col items-end gap-1 ${hideAvatar ? "pr-1" : "pr-13"} pb-1`}
          >
            <span className="text-xs text-zinc-400 select-none">Queued</span>
          </div>
        )}

        {/* Undelivered: a persistent label + retry, not the hover-only actions
            row — a send that never landed must be visible without hovering. */}
        {!disableActions && !queued && failed && (
          <div
            className={`flex items-center gap-2 ${hideAvatar ? "pr-1" : "pr-13"} pb-1`}
          >
            <span className="text-xs text-zinc-400 select-none">
              Not delivered
            </span>
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
        )}

        {/* Actions row below bubble, aligned under content (not avatar) */}
        {!disableActions && !queued && !failed && (
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
        )}
      </div>
    </div>
  );
}
