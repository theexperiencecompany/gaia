// ChatBubbleBot.tsx
import Image from "next/image";
import { useCallback, useMemo, useRef } from "react";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import ChatBubble_Actions from "@/features/chat/components/bubbles/actions/ChatBubble_Actions";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import { IntegrationConnectionPrompt } from "@/features/chat/components/integration/IntegrationConnectionPrompt";
import MemoryIndicator from "@/features/chat/components/memory/MemoryIndicator";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { parseDate } from "@/utils/date/dateUtils";

import FollowUpActions from "./FollowUpActions";
import ImageBubble from "./ImageBubble";
import TextBubble from "./TextBubble";

export default function ChatBubbleBot(props: ChatBubbleBotProps) {
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
    integration_connection_required,
    follow_up_actions,
    isLastMessage,
  } = props;
  const { isLoading } = useLoading();

  const actionsRef = useRef<HTMLDivElement>(null);

  const handleMouseOver = useCallback(() => {
    if (actionsRef.current) {
      actionsRef.current.style.opacity = "1";
      actionsRef.current.style.visibility = "visible";
    }
  }, []);

  const handleMouseOut = useCallback(() => {
    if (actionsRef.current) {
      actionsRef.current.style.opacity = "0";
      actionsRef.current.style.visibility = "hidden";
    }
  }, []);

  const renderedComponent = useMemo(() => {
    // Integration connection prompt takes priority
    if (integration_connection_required)
      return (
        <IntegrationConnectionPrompt data={integration_connection_required} />
      );

    if (image_data) return <ImageBubble {...props} image_data={image_data} />;

    return <TextBubble {...props} />;
  }, [image_data, props, integration_connection_required]);

  return (
    (loading ||
      image_data ||
      !!text ||
      props.integration_connection_required ||
      (isConvoSystemGenerated &&
        systemPurpose === SystemPurpose.EMAIL_PROCESSING)) && (
      <div
        id={message_id}
        onMouseOver={handleMouseOver}
        onMouseOut={handleMouseOut}
        className="relative flex flex-col pb-9"
      >
        <div className="flex items-end gap-1">
          <div className="relative bottom-0 min-w-[40px] flex-shrink-0">
            {shouldShowTextBubble(
              text,
              isConvoSystemGenerated,
              systemPurpose,
            ) && (
              <Image
                alt="GAIA Logo"
                src={"/images/logos/logo.webp"}
                width={30}
                height={30}
                className={`${isLoading && isLastMessage ? "animate-spin" : ""} relative z-[5] transition duration-900`}
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

        <div className="ml-[43px] flex flex-col">
          {!!follow_up_actions && follow_up_actions?.length > 0 && (
            <FollowUpActions actions={follow_up_actions} loading={!!loading} />
          )}

          <div
            ref={actionsRef}
            className={`absolute -bottom-5 flex flex-col transition-all ${loading ? "opacity-0!" : "opacity-100"}`}
            style={{ opacity: 0, visibility: "hidden" }}
          >
            {date && (
              <span className="text-opacity-40 flex flex-col p-1 py-2 text-xs text-nowrap text-zinc-400 select-text">
                {parseDate(date)}
              </span>
            )}

            {image_data ? (
              <ChatBubble_Actions_Image image_data={image_data} />
            ) : (
              <ChatBubble_Actions
                loading={loading}
                message_id={message_id}
                pinned={pinned}
                text={text}
              />
            )}
          </div>
        </div>
      </div>
    )
  );
}
