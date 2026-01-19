"use client";
import { SystemPurpose } from "@/features/chat/api/chatApi";
import { ChatBotIcon, Mail01Icon, StarIcon } from "@/icons";
import { useChatStore } from "@/stores/chatStore";
import { Button } from "@heroui/button";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { type FC, useEffect, useState } from "react";
import ChatOptionsDropdown from "./ChatOptionsDropdown";

const ICON_WIDTH = "20";
const ICON_SIZE = "w-[17px] min-w-[17px]";

interface ChatTabProps {
  name: string;
  id: string;
  starred: boolean | undefined;
  isSystemGenerated?: boolean;
  systemPurpose?: SystemPurpose;
  isUnread?: boolean;
}

export const ChatTab: FC<ChatTabProps> = ({
  name,
  id,
  starred,
  isSystemGenerated = false,
  systemPurpose,
  isUnread = false,
}) => {
  const [currentConvoId, setCurrentConvoId] = useState<string | null>(null);
  const pathname = usePathname();
  const [buttonHovered, setButtonHovered] = useState(false);

  // Check if this conversation is currently streaming
  const streamingConversationId = useChatStore(
    (state) => state.streamingConversationId
  );
  const isStreaming = streamingConversationId === id;

  useEffect(() => {
    const pathParts = pathname.split("/");
    setCurrentConvoId(pathParts[pathParts.length - 1]);
  }, [pathname]);

  const isActive = currentConvoId === id;

  const getIcon = () => {
    const iconProps = {
      width: ICON_WIDTH,
      style: { minWidth: ICON_WIDTH },
    };

    if (isSystemGenerated) {
      if (systemPurpose === SystemPurpose.EMAIL_PROCESSING)
        return <Mail01Icon {...iconProps} />;

      if (systemPurpose === SystemPurpose.WORKFLOW_EXECUTION)
        return <ChatBotIcon {...iconProps} />;

      return <ChatBotIcon {...iconProps} />;
    }

    if (starred) return <StarIcon className={ICON_SIZE} {...iconProps} />;

    return undefined;
  };

  return (
    <div
      className="relative z-0 flex"
      onMouseOut={() => setButtonHovered(false)}
      onMouseOver={() => setButtonHovered(true)}
    >
      <Button
        className={`w-full justify-start px-2 font-light text-sm ${
          isUnread
            ? "text-white font-normal"
            : isActive
              ? "text-zinc-300"
              : "text-zinc-400 hover:text-zinc-300"
        }`}
        size="sm"
        as={Link}
        href={`/c/${id}`}
        variant={isActive ? "flat" : "light"}
        onPress={() => setButtonHovered(false)}
        startContent={
          getIcon() &&
          React.cloneElement(getIcon()!, {
            width: 18,
            height: 18,
          })
        }
      >
        <div className="flex items-center truncate justify-start w-full gap-2">
          {/* Streaming indicator - pulsing dot */}
          {isStreaming && (
            <div
              className="size-2 bg-primary rounded-full animate-pulse"
              title="Streaming..."
            />
          )}
          {/* Unread indicator */}
          {!isStreaming && isUnread && (
            <div className="size-2.5 bg-primary rounded-full" />
          )}
          <span>{name.replace('"', "")}</span>
        </div>
      </Button>

      <div className={`absolute right-0`}>
        <ChatOptionsDropdown
          buttonHovered={buttonHovered}
          chatId={id}
          chatName={name}
          starred={starred}
          isUnread={isUnread}
        />
      </div>
    </div>
  );
};
