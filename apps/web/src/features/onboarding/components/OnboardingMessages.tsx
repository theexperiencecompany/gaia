import { m } from "motion/react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import { InboxRevealCard } from "@/features/onboarding/components/reveal/InboxRevealCard";
import { SocialProfilesRevealCard } from "@/features/onboarding/components/reveal/SocialProfilesRevealCard";
import { TodosRevealCard } from "@/features/onboarding/components/reveal/TodosRevealCard";
import { TriageRevealCard } from "@/features/onboarding/components/reveal/TriageRevealCard";
import { WorkflowsRevealCard } from "@/features/onboarding/components/reveal/WorkflowsRevealCard";
import { WritingStyleRevealCard } from "@/features/onboarding/components/reveal/WritingStyleRevealCard";

import type { Message } from "../types";
import type {
  InboxScanResults,
  PersonalizationData,
  SocialProfilesResults,
  TodoResults,
  TriageResults,
  WorkflowResults,
  WritingStyleResults,
} from "../types/websocket";
import { OnboardingProcessing } from "./OnboardingProcessing";

interface OnboardingMessagesProps {
  messages: Message[];
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  isProcessingPhase?: boolean;
  hasGmail?: boolean;
  isIntelligenceComplete?: boolean;
  intelligenceConversationId?: string | null;
  onProcessingComplete?: (conversationId: string) => void;
}

function renderRevealCard(
  revealStage: string,
  revealData: Record<string, unknown>,
): React.ReactNode {
  switch (revealStage) {
    case "scanning_inbox":
      return (
        <InboxRevealCard {...(revealData as unknown as InboxScanResults)} />
      );
    case "learning_style":
      return (
        <WritingStyleRevealCard
          {...(revealData as unknown as WritingStyleResults)}
        />
      );
    case "finding_profiles":
      return (
        <SocialProfilesRevealCard
          {...(revealData as unknown as SocialProfilesResults)}
        />
      );
    case "triaging":
      return <TriageRevealCard {...(revealData as unknown as TriageResults)} />;
    case "creating_todos":
      return <TodosRevealCard {...(revealData as unknown as TodoResults)} />;
    case "creating_workflows":
      return (
        <WorkflowsRevealCard {...(revealData as unknown as WorkflowResults)} />
      );
    case "holo_card": {
      const { personalizationData } = revealData as unknown as {
        personalizationData: PersonalizationData;
      };
      return <HoloCardReveal personalizationData={personalizationData} />;
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
            ease: "easeOut",
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
              return (
                <ChatBubbleBot
                  message_id={""}
                  date={undefined}
                  pinned={undefined}
                  fileIds={undefined}
                  fileData={undefined}
                  selectedTool={undefined}
                  toolCategory={undefined}
                  selectedWorkflow={undefined}
                  selectedCalendarEvent={undefined}
                  isConvoSystemGenerated={undefined}
                  follow_up_actions={undefined}
                  image_data={undefined}
                  memory_data={undefined}
                  todo_progress={undefined}
                  replyToMessage={undefined}
                  setOpenImage={() => {}}
                  setImageData={() => {}}
                  text={message.content}
                  disableActions={true}
                  {...message}
                >
                  {card}
                </ChatBubbleBot>
              );
            })()
          ) : message.type === "bot" ? (
            <ChatBubbleBot
              message_id={""}
              date={undefined}
              pinned={undefined}
              fileIds={undefined}
              fileData={undefined}
              selectedTool={undefined}
              toolCategory={undefined}
              selectedWorkflow={undefined}
              selectedCalendarEvent={undefined}
              isConvoSystemGenerated={undefined}
              follow_up_actions={undefined}
              image_data={undefined}
              memory_data={undefined}
              todo_progress={undefined}
              replyToMessage={undefined}
              setOpenImage={() => {}}
              setImageData={() => {}}
              text={message.content}
              disableActions={true}
              {...message}
            >
              {isProcessingPhase &&
                index === messages.length - 1 &&
                revealMessages.length === 0 && (
                  <m.div
                    className="ml-[43px]"
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
                    />
                  </m.div>
                )}
            </ChatBubbleBot>
          ) : (
            <ChatBubbleUser
              text={message.content}
              message_id={""}
              date={undefined}
              pinned={undefined}
              fileIds={undefined}
              fileData={undefined}
              selectedTool={undefined}
              toolCategory={undefined}
              todo_progress={undefined}
              selectedWorkflow={undefined}
              selectedCalendarEvent={undefined}
              isConvoSystemGenerated={undefined}
              follow_up_actions={undefined}
              image_data={undefined}
              memory_data={undefined}
              replyToMessage={undefined}
              disableActions={true}
            />
          )}
        </m.div>
      ))}

      <div ref={messagesEndRef} />
    </>
  );
};
