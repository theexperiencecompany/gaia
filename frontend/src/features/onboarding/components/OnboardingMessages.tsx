import { motion } from "framer-motion";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

import type { Message } from "../types";
import OnboardingIntegrationButtons from "./OnboardingIntegrationButtons";

interface OnboardingMessagesProps {
  messages: Message[];
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  isOnboardingComplete?: boolean;
}

export const OnboardingMessages = ({
  messages,
  messagesEndRef,
  isOnboardingComplete = false,
}: OnboardingMessagesProps) => {
  return (
    <>
      {messages.map((message, index) => (
        <motion.div
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
          {message.type === "bot" ? (
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
              setOpenImage={() => {}}
              setImageData={() => {}}
              text={message.content}
              disableActions={true}
              {...message}
            >
              {isOnboardingComplete && index === messages.length - 1 && (
                <motion.div
                  className="ml-[43px]"
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.5,
                    ease: "easeOut",
                    delay: 0.3,
                  }}
                >
                  <OnboardingIntegrationButtons />
                </motion.div>
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
              selectedWorkflow={undefined}
              selectedCalendarEvent={undefined}
              isConvoSystemGenerated={undefined}
              follow_up_actions={undefined}
              image_data={undefined}
              memory_data={undefined}
              disableActions={true}
            />
          )}
        </motion.div>
      ))}

      <div ref={messagesEndRef} />
    </>
  );
};
