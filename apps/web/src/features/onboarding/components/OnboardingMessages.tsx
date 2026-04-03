import { m } from "motion/react";
import type { ReactNode } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import { SocialProfilesRevealCard } from "@/features/onboarding/components/reveal/SocialProfilesRevealCard";
import { TodosRevealCard } from "@/features/onboarding/components/reveal/TodosRevealCard";
import { TriageRevealCard } from "@/features/onboarding/components/reveal/TriageRevealCard";
import { WorkflowsRevealCard } from "@/features/onboarding/components/reveal/WorkflowsRevealCard";
import { WritingStyleRevealCard } from "@/features/onboarding/components/reveal/WritingStyleRevealCard";

import type { Message } from "../types";
import type {
  PersonalizationData,
  SocialProfilesResults,
  TodoResults,
  TriageResults,
  WorkflowResults,
  WritingStyleResults,
} from "../types/websocket";
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

function renderRevealCard(
  revealStage: string,
  revealData: Record<string, unknown>,
): React.ReactNode {
  // Single cast to unknown so individual branches can narrow safely
  const data: unknown = revealData;

  switch (revealStage) {
    case "learning_style":
      if ("style_summary" in revealData) {
        return <WritingStyleRevealCard {...(data as WritingStyleResults)} />;
      }
      return null;
    case "finding_profiles":
      if ("profiles" in revealData) {
        return (
          <SocialProfilesRevealCard {...(data as SocialProfilesResults)} />
        );
      }
      return null;
    case "triaging":
      if ("important_emails" in revealData) {
        return <TriageRevealCard {...(data as TriageResults)} />;
      }
      return null;
    case "creating_todos":
      if ("todos" in revealData) {
        return <TodosRevealCard {...(data as TodoResults)} />;
      }
      return null;
    case "creating_workflows":
      if ("workflows" in revealData) {
        return <WorkflowsRevealCard {...(data as WorkflowResults)} />;
      }
      return null;
    case "holo_card": {
      if ("personalizationData" in revealData) {
        const { personalizationData } = data as {
          personalizationData: PersonalizationData;
        };
        return <HoloCardReveal personalizationData={personalizationData} />;
      }
      return null;
    }
    default:
      return null;
  }
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
  const revealMessages = messages.filter((msg) => msg.type === "reveal");

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
          {message.type === "reveal" ? (
            (() => {
              const card =
                message.revealStage && message.revealData
                  ? renderRevealCard(message.revealStage, message.revealData)
                  : null;
              if (!card) return null;
              return card;
            })()
          ) : message.type === "bot" ? (
            <OnboardingBotBubble
              text={
                message.id === "processing" && processingContinuation
                  ? `${message.content}<NEW_MESSAGE_BREAK>${processingContinuation}`
                  : message.content
              }
            >
              {isProcessingPhase &&
                index === messages.length - 1 &&
                revealMessages.length === 0 &&
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
