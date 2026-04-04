import { m } from "motion/react";
import type { ReactNode } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

import type { Message } from "../types";
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
  processingProgress?: number;
  onEditMessage?: (fieldName: string) => void;
  stageMessages?: Record<string, string>;
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
  processingProgress,
  onEditMessage,
  stageMessages,
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
                      processingProgress={processingProgress}
                      stageMessages={stageMessages}
                    />
                  </m.div>
                )}
              {message.id === "processing" && processingContinuationChildren}
            </OnboardingBotBubble>
          ) : (
            <div className="group flex items-end justify-end gap-0">
              {message.questionFieldName &&
                onEditMessage &&
                !isProcessingPhase && (
                  <button
                    type="button"
                    onClick={() => onEditMessage(message.questionFieldName!)}
                    className="ml-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-zinc-600 hover:text-zinc-400 shrink-0 self-end mb-1"
                    aria-label="Edit this response"
                  >
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      aria-hidden="true"
                    >
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                )}
              <OnboardingUserBubble text={message.content} />
            </div>
          )}
        </m.div>
      ))}

      <div ref={messagesEndRef} />
    </>
  );
};
