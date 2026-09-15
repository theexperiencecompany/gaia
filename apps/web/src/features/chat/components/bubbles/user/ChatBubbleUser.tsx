import Image from "next/image";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import SelectedCalendarEventIndicator from "@/features/chat/components/composer/SelectedCalendarEventIndicator";
import SelectedReplyIndicator from "@/features/chat/components/composer/SelectedReplyIndicator";
import SelectedToolIndicator from "@/features/chat/components/composer/SelectedToolIndicator";
import SelectedWorkflowIndicator from "@/features/chat/components/composer/SelectedWorkflowIndicator";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useChatBubbleUser } from "@/features/chat/hooks/useChatBubbleUser";
import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import type { FileData } from "@/types/shared/fileTypes";

import ChatBubbleFilePreview from "./ChatBubbleFilePreview";
import { ChatBubbleUserFooter } from "./ChatBubbleUserFooter";

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
  const { hasContent, user, isEmojiOnly, bubbleClassName, textClassName } =
    useChatBubbleUser({
      text,
      fileData,
      selectedTool,
      selectedWorkflow,
      selectedCalendarEvent,
      fullWidth,
    });

  if (!hasContent) return null;

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

        <ChatBubbleUserFooter
          text={text}
          date={date}
          message_id={message_id}
          queued={queued}
          failed={failed}
          onRetry={onRetry}
          isRetrying={isRetrying}
          disableActions={disableActions}
          hideAvatar={hideAvatar}
        />
      </div>
    </div>
  );
}
