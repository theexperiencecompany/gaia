// ChatBubbleBot.tsx
import * as m from "motion/react-m";
import Image from "next/image";
import { type ReactNode, useMemo, useRef } from "react";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import ChatBubble_Actions from "@/features/chat/components/bubbles/actions/ChatBubble_Actions";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import MemoryIndicator from "@/features/chat/components/memory/MemoryIndicator";
import {
  logoDelayFor,
  MESSAGE_BREAK_DURATION_SECONDS,
  MESSAGE_BREAK_EASE_OUT_QUART,
  type PartChoreography,
  resolvePartChoreography,
} from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";
import { describeBotBubbleContent } from "./botBubbleContent";
import FollowUpActions from "./FollowUpActions";
import ImageBubble from "./ImageBubble";
import TextBubble from "./TextBubble";
import { useActionsHover } from "./useActionsHover";

export default function ChatBubbleBot(
  props: ChatBubbleBotProps & {
    disableActions?: boolean;
    hideAvatar?: boolean;
    isGroupedWithNext?: boolean;
    isGroupedWithPrev?: boolean;
    children?: ReactNode;
    /** Per-part reveal cadence; see TextBubble. */
    partChoreography?: PartChoreography;
  },
) {
  const {
    text,
    loading = false,
    message_id,
    pinned,
    image_data,
    date,
    memory_data,
    onOpenMemoryModal,
    isConvoSystemGenerated,
    systemPurpose,
    follow_up_actions,
    error,
    disableActions = false,
    hideAvatar = false,
    isGroupedWithNext = false,
    isGroupedWithPrev = false,
    children,
    onRetry,
    isRetrying,
  } = props;
  const partChoreography = resolvePartChoreography(props.partChoreography);

  const actionsRef = useRef<HTMLDivElement>(null);
  const { handleMouseOver, handleMouseOut } = useActionsHover(
    actionsRef,
    disableActions,
  );

  // Not memoized on purpose: `props` is rebuilt by getMessageProps every
  // render, so a useMemo keyed on it never hits. Real render protection lives
  // one level up in ChatMessageItem's memo (stable idle message refs).
  const renderedComponent = image_data ? (
    <ImageBubble {...props} image_data={image_data} />
  ) : (
    <TextBubble {...props} partChoreography={partChoreography} />
  );

  const itShouldShowTextBubble = shouldShowTextBubble(
    text,
    isConvoSystemGenerated,
    systemPurpose,
  );

  const logoDelay = useMemo(
    () =>
      itShouldShowTextBubble
        ? logoDelayFor(
            parseThinkingFromText(text?.toString() || "").cleanText,
            partChoreography.staggerSeconds,
          )
        : 0,
    [text, itShouldShowTextBubble, partChoreography.staggerSeconds],
  );

  // A failed turn with no response text still shows the quiet error bubble.
  const { hasError, hasContent } = describeBotBubbleContent({
    text: text?.toString(),
    showsTextBubble: itShouldShowTextBubble,
    error,
    imageData: image_data,
    isConvoSystemGenerated,
    systemPurpose,
    toolDataLength: props.tool_data?.length,
    emailProcessingPurpose: SystemPurpose.EMAIL_PROCESSING,
  });

  // Don't render the full bubble structure if only loading with no content
  // Let ChatRenderer's loading indicator handle it
  if (loading && !hasContent) return null;

  // The error bubble gets the same chrome as a text bubble (avatar + actions,
  // so Retry is reachable).
  const showBubbleChrome = itShouldShowTextBubble || hasError;

  return (
    (loading || hasContent) && (
      <div
        id={message_id}
        onMouseOver={handleMouseOver}
        onMouseOut={handleMouseOut}
        onFocus={handleMouseOver}
        onBlur={handleMouseOut}
        className={`relative flex flex-col ${isGroupedWithPrev ? "mt-1.5" : ""}`}
      >
        {/*
          Alignment is structural, not per-message. Every bot bubble reserves
          the avatar lane via a constant left pad (same width as the `ml-10.75`
          actions row below), so grouped bubbles can never drift sideways. The
          logo is an absolute overlay pinned to that lane — it never affects
          layout flow — and only the last bubble of a consecutive group (i.e.
          not grouped-with-next) actually renders it.
        */}
        <div className="relative">
          {!hideAvatar && !isGroupedWithNext && showBubbleChrome && (
            <m.div
              className="absolute bottom-0 left-0 z-5 transition duration-900"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{
                duration: MESSAGE_BREAK_DURATION_SECONDS,
                ease: MESSAGE_BREAK_EASE_OUT_QUART,
                delay: logoDelay,
              }}
            >
              <Image
                alt="GAIA Logo"
                src={"/images/logos/logo.webp"}
                width={30}
                height={30}
              />
            </m.div>
          )}

          <div
            className={`chatbubblebot_parent ${hideAvatar ? "" : "pl-10.75"}`}
          >
            <div className="flex w-full flex-col gap-2">
              {memory_data && onOpenMemoryModal && (
                <MemoryIndicator
                  memoryData={memory_data}
                  onOpenModal={onOpenMemoryModal}
                />
              )}
              <div className="chat_bubble_container">{renderedComponent}</div>
            </div>
          </div>
        </div>

        {showBubbleChrome && (
          <div className="ml-10.75 flex flex-col">
            {!!follow_up_actions && follow_up_actions?.length > 0 && (
              <FollowUpActions
                actions={follow_up_actions}
                loading={!!loading}
              />
            )}

            <div
              ref={actionsRef}
              className={`flex flex-col transition-all ${disableActions ? "hidden" : loading ? "opacity-0!" : "opacity-100"}`}
              style={{
                opacity: disableActions ? 1 : 0,
                visibility: disableActions ? "visible" : "hidden",
              }}
            >
              {date && !disableActions && (
                <span
                  className="text-opacity-40 flex flex-col p-1 py-2 text-xs text-nowrap text-zinc-400 select-text"
                  suppressHydrationWarning
                >
                  {parseDate(date)}
                </span>
              )}

              {!disableActions &&
                (image_data ? (
                  <ChatBubble_Actions_Image image_data={image_data} />
                ) : (
                  <ChatBubble_Actions
                    loading={loading}
                    message_id={message_id}
                    pinned={pinned}
                    text={text}
                    messageRole="assistant"
                    onRetry={onRetry}
                    isRetrying={isRetrying}
                  />
                ))}
            </div>
          </div>
        )}

        {children}
      </div>
    )
  );
}
