// ChatBubbleBot.tsx
import Image from "next/image";
import { type ReactNode, useCallback, useMemo, useRef } from "react";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import ChatBubble_Actions from "@/features/chat/components/bubbles/actions/ChatBubble_Actions";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import MemoryIndicator from "@/features/chat/components/memory/MemoryIndicator";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import FollowUpActions from "./FollowUpActions";
import ImageBubble from "./ImageBubble";
import TextBubble from "./TextBubble";

export default function ChatBubbleBot(
  props: ChatBubbleBotProps & {
    disableActions?: boolean;
    children?: ReactNode;
  }
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
    children,
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

  const itShouldShowTextBubble = shouldShowTextBubble(
    text,
    isConvoSystemGenerated,
    systemPurpose
  );

  return (
    (loading || hasContent) && (
      <div
        id={message_id}
        onMouseOver={handleMouseOver}
        onMouseOut={handleMouseOut}
        className="relative flex flex-col"
      >
        <div className="flex items-end gap-1">
          <div className="relative bottom-0 min-w-10 shrink-0">
            {itShouldShowTextBubble && (
              <Image
                alt="GAIA Logo"
                src={"/images/logos/logo.webp"}
                width={30}
                height={30}
                className={`${isLoading && isLastMessage ? "animate-spin" : ""} relative z-5 transition duration-900`}
              />
            )}
          </div>

          <div className="chatbubblebot_parent flex-1">
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

        {itShouldShowTextBubble && (
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
                <span className="text-opacity-40 flex flex-col p-1 py-2 text-xs text-nowrap text-zinc-400 select-text">
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
