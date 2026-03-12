"use client";

import { useEffect, useRef } from "react";
import { AnimatePresence } from "motion/react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import { getMessageProps } from "@/features/chat/utils/messagePropsUtils";
import type { MessageType } from "@/types/features/convoTypes";
import type { ScenarioLoadingState } from "../hooks/useScenarioPlayer";
import RecordingComposer from "./RecordingComposer";

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

// Eased scroll to targetY over duration ms. Cancels prior animation via rafRef.
function animateScrollTo(
  el: HTMLElement,
  targetY: number,
  duration: number,
  rafRef: React.MutableRefObject<number | null>,
  onComplete?: () => void,
) {
  if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
  const startY = el.scrollTop;
  const distance = targetY - startY;
  if (Math.abs(distance) < 2) {
    onComplete?.();
    return;
  }
  const startTime = performance.now();

  function step(now: number) {
    const t = Math.min((now - startTime) / duration, 1);
    // easeInOutQuart — feels slow and intentional
    const ease =
      t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2;
    el.scrollTop = startY + distance * ease;
    if (t < 1) rafRef.current = requestAnimationFrame(step);
    else {
      rafRef.current = null;
      onComplete?.();
    }
  }
  rafRef.current = requestAnimationFrame(step);
}

export default function RecordingChatLayout({
  messages,
  partialMessage,
  loadingState,
}: RecordingChatLayoutProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const cleanupTimerRef = useRef<(() => void) | null>(null);

  // Track tool_data additions on existing messages (doesn't change length)
  const toolDataKey = messages.reduce(
    (acc, m) => acc + (m.tool_data?.length ?? 0),
    0,
  );

  // New message committed or tool cards added → scroll to bottom.
  // Duration scales with distance so short reveals are snappy and tall
  // reveals (tool cards, follow-up actions) give the viewer time to read.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    cleanupTimerRef.current?.();

    const target = el.scrollHeight - el.clientHeight;
    const distance = Math.abs(target - el.scrollTop);

    if (distance < 2) return;

    // Scale: ~600ms for small scrolls, up to 2500ms for large reveals
    const duration = Math.min(2500, Math.max(600, distance * 3));
    animateScrollTo(el, target, duration, rafRef);

    return () => cleanupTimerRef.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, toolDataKey]);

  // Loading text changes — gentle scroll to keep indicator visible
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    animateScrollTo(el, el.scrollHeight - el.clientHeight, 800, rafRef);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingState.loadingTextKey]);

  // Streaming in progress — smooth follow instead of instant jump
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !partialMessage) return;
    animateScrollTo(el, el.scrollHeight - el.clientHeight, 300, rafRef);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partialMessage?.response?.length]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      cleanupTimerRef.current?.();
    };
  }, []);

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
        className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-4"
        style={{ scrollbarWidth: "none" }}
      >
        <div className="space-y-4">
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

          <AnimatePresence>
            {loadingState.isLoading && !partialMessage && (
              <LoadingIndicator
                key="loading-indicator"
                loadingText={loadingState.loadingText}
                loadingTextKey={loadingState.loadingTextKey}
                toolInfo={loadingState.toolInfo}
              />
            )}
          </AnimatePresence>
        </div>
      </div>
      <RecordingComposer />
    </div>
  );
}
