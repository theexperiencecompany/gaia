import { m } from "motion/react";
import type { ReactNode } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

import type { Message } from "../types";
import type { OnboardingStage } from "../types/websocket";
import { OnboardingProcessing } from "./OnboardingProcessing";

const noop = () => {};

const BOT_DEFAULTS = {
  message_id: "",
  date: undefined,
  pinned: undefined,
  fileIds: undefined,
  fileData: undefined,
  selectedTool: undefined,
  toolCategory: undefined,
  selectedWorkflow: undefined,
  selectedCalendarEvent: undefined,
  isConvoSystemGenerated: undefined,
  follow_up_actions: undefined,
  image_data: undefined,
  memory_data: undefined,
  todo_progress: undefined,
  replyToMessage: undefined,
  setOpenImage: noop,
  setImageData: noop,
  disableActions: true,
} as const;

const USER_DEFAULTS = {
  message_id: "",
  date: undefined,
  pinned: undefined,
  fileIds: undefined,
  fileData: undefined,
  selectedTool: undefined,
  toolCategory: undefined,
  selectedWorkflow: undefined,
  selectedCalendarEvent: undefined,
  isConvoSystemGenerated: undefined,
  follow_up_actions: undefined,
  image_data: undefined,
  memory_data: undefined,
  todo_progress: undefined,
  replyToMessage: undefined,
  disableActions: true,
} as const;

function OnboardingBotBubble({
  text,
  children,
}: {
  text: string;
  children?: ReactNode;
}) {
  return (
    <ChatBubbleBot {...BOT_DEFAULTS} text={text}>
      {children}
    </ChatBubbleBot>
  );
}

function OnboardingUserBubble({ text }: { text: string }) {
  return <ChatBubbleUser {...USER_DEFAULTS} text={text} />;
}

interface OnboardingMessagesProps {
  messages: Message[];
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  isProcessingPhase?: boolean;
  hasGmail?: boolean;
  isIntelligenceComplete?: boolean;
  intelligenceConversationId?: string | null;
  onProcessingComplete?: (conversationId: string) => void;
  isProcessingSkipped?: boolean;
  inboxScanCount?: number;
  completedStages?: Set<OnboardingStage>;
  /** Sub-status text the active processing step should surface */
  processingStatusMessage?: string | null;
  /** Text to append to the processing message via <NEW_MESSAGE_BREAK> */
  processingContinuation?: string;
  /** Children to render below the processing bubble (e.g. todo cards) */
  processingContinuationChildren?: ReactNode;
}

export const OnboardingMessages = ({
  messages,
  messagesEndRef,
  isProcessingPhase = false,
  hasGmail = false,
  isIntelligenceComplete = false,
  intelligenceConversationId = null,
  onProcessingComplete,
  isProcessingSkipped = false,
  inboxScanCount,
  completedStages,
  processingStatusMessage,
  processingContinuation,
  processingContinuationChildren,
}: OnboardingMessagesProps) => {
  return (
    <>
      {messages.map((message, index) => (
        <m.div
          key={message.id}
          className="mb-4"
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.4,
            ease: [0.19, 1, 0.22, 1],
            delay: index * 0.05,
          }}
        >
          {message.type === "bot" ? (
            <OnboardingBotBubble
              text={
                message.id === "processing" && processingContinuation
                  ? `${message.content}<NEW_MESSAGE_BREAK>${processingContinuation}`
                  : message.content
              }
            >
              {isProcessingPhase &&
                index === messages.length - 1 &&
                !isProcessingSkipped && (
                  <m.div
                    className="ml-10.75"
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.5,
                      ease: "easeOut",
                      delay: 0.3,
                    }}
                  >
                    <OnboardingProcessing
                      hasGmail={hasGmail}
                      isIntelligenceComplete={isIntelligenceComplete}
                      intelligenceConversationId={intelligenceConversationId}
                      onComplete={onProcessingComplete ?? (() => {})}
                      inboxScanCount={inboxScanCount}
                      completedStages={completedStages}
                      statusMessage={processingStatusMessage}
                    />
                  </m.div>
                )}
              {message.id === "processing" && processingContinuationChildren}
            </OnboardingBotBubble>
          ) : (
            <div className="flex items-end justify-end gap-0">
              <OnboardingUserBubble text={message.content} />
            </div>
          )}
        </m.div>
      ))}

      <div ref={messagesEndRef} />
    </>
  );
};
