// ChatBubbleBot.tsx
import {
  splitByBreaksPreservingFences,
  splitMessageByBreaks,
} from "@shared/utils";
import * as m from "motion/react-m";
import Image from "next/image";
import { type ReactNode, useCallback, useMemo, useRef } from "react";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import ChatBubble_Actions from "@/features/chat/components/bubbles/actions/ChatBubble_Actions";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import MemoryIndicator from "@/features/chat/components/memory/MemoryIndicator";
import { useLoading } from "@/features/chat/hooks/useLoading";
import {
  MESSAGE_BREAK_DURATION_SECONDS,
  MESSAGE_BREAK_EASE_OUT_QUART,
  MESSAGE_BREAK_STAGGER_SECONDS,
} from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import FollowUpActions from "./FollowUpActions";
import ImageBubble from "./ImageBubble";
import TextBubble from "./TextBubble";

export default function ChatBubbleBot(
  props: ChatBubbleBotProps & {
    disableActions?: boolean;
    hideAvatar?: boolean;
    isGroupedWithNext?: boolean;
    isGroupedWithPrev?: boolean;
    children?: ReactNode;
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
    isLastMessage,
    disableActions = false,
    hideAvatar = false,
    isGroupedWithNext = false,
    isGroupedWithPrev = false,
    children,
    onRetry,
    isRetrying,
  } = props;
  const { isLoading } = useLoading();

  const actionsRef = useRef<HTMLDivElement>(null);

  const handleMouseOver = useCallback(() => {
    if (actionsRef.current && !disableActions) {
      actionsRef.current.style.opacity = "1";
      actionsRef.current.style.visibility = "visible";
    }
  }, [disableActions]);

  const handleMouseOut = useCallback(() => {
    if (actionsRef.current && !disableActions) {
      actionsRef.current.style.opacity = "0";
      actionsRef.current.style.visibility = "hidden";
    }
  }, [disableActions]);

  const renderedComponent = useMemo(() => {
    if (image_data) return <ImageBubble {...props} image_data={image_data} />;

    return <TextBubble {...props} />;
  }, [image_data, props]);

  const itShouldShowTextBubble = shouldShowTextBubble(
    text,
    isConvoSystemGenerated,
    systemPurpose,
  );

  const logoDelay = useMemo(() => {
    if (!itShouldShowTextBubble) return 0;
    const cleanText = parseThinkingFromText(text?.toString() || "").cleanText;
    if (!cleanText) return 0;
    const parts = cleanText.includes(":::openui")
      ? splitByBreaksPreservingFences(cleanText)
      : splitMessageByBreaks(cleanText);
    return Math.max(0, parts.length - 1) * MESSAGE_BREAK_STAGGER_SECONDS;
  }, [text, itShouldShowTextBubble]);

  // Check if there's actual content to display
  const hasContent =
    image_data ||
    !!text ||
    (isConvoSystemGenerated &&
      systemPurpose === SystemPurpose.EMAIL_PROCESSING) ||
    props.tool_data?.length;

  // Don't render the full bubble structure if only loading with no content
  // Let ChatRenderer's loading indicator handle it
  if (loading && !hasContent) return null;

  const showBubbleChrome = itShouldShowTextBubble;

  return (
    (loading || hasContent) && (
      <div
        id={message_id}
        onMouseOver={handleMouseOver}
        onMouseOut={handleMouseOut}
        className={`relative flex flex-col ${isGroupedWithPrev ? "mt-1.5" : ""}`}
        style={{ contentVisibility: "auto", containIntrinsicSize: "0 120px" }}
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
              className={`${isLoading && isLastMessage ? "animate-spin" : ""} absolute bottom-0 left-0 z-5 transition duration-900`}
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
