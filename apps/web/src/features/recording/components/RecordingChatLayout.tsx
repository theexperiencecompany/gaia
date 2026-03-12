"use client";

import { useEffect, useRef } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import { getMessageProps } from "@/features/chat/utils/messagePropsUtils";
import type { MessageType } from "@/types/features/convoTypes";
import type { ScenarioLoadingState } from "../hooks/useScenarioPlayer";

interface RecordingChatLayoutProps {
  messages: MessageType[];
  partialMessage: MessageType | null;
  loadingState: ScenarioLoadingState;
}

// No-op dispatchers — required by ChatBubbleBot but never triggered in recording
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const noopDispatch = (() => {}) as React.Dispatch<React.SetStateAction<any>>;
const noop = () => {};

const noopOptions = {
  setImageData: noopDispatch,
  setOpenGeneratedImage: noopDispatch,
  setOpenMemoryModal: noopDispatch,
};

export default function RecordingChatLayout({
  messages,
  partialMessage,
  loadingState,
}: RecordingChatLayoutProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, partialMessage?.response?.length, loadingState.isLoading]);

  const allMessages = partialMessage
    ? [...messages, partialMessage]
    : messages;

  // Index of last bot message in the full list — only that one shows the logo
  const lastBotIdx = allMessages.reduce(
    (last, msg, i) => (msg.type === "bot" ? i : last),
    -1,
  );

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ backgroundColor: "#111111" }}>
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-4 space-y-4"
        style={{ scrollbarWidth: "none" }}
      >
        {allMessages.map((msg, i) =>
          msg.type === "user" ? (
            <ChatBubbleUser
              key={msg.message_id}
              {...getMessageProps(msg, "user", noopOptions)}
              disableActions
            />
          ) : (
            <ChatBubbleBot
              key={msg.message_id}
              {...getMessageProps(msg, "bot", noopOptions)}
              loading={msg === partialMessage ? loadingState.isLoading : (msg.loading ?? false)}
              isLastMessage={i === lastBotIdx}
              onRetry={noop}
              disableActions
            />
          ),
        )}

        {loadingState.isLoading && !partialMessage && (
          <LoadingIndicator
            loadingText={loadingState.loadingText}
            loadingTextKey={loadingState.loadingTextKey}
            toolInfo={loadingState.toolInfo}
          />
        )}
      </div>
    </div>
  );
}
