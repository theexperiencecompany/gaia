"use client";
import { Button } from "@heroui/button";
import { ChatBotIcon, Mail01Icon, StarIcon } from "@icons";
import Link from "next/link";
import React, { type FC, useState } from "react";
import { SystemPurpose } from "@/features/chat/api/chatApi";
import { usePathname } from "@/i18n/navigation";
import {
  useIsConversationAwaitingApproval,
  useIsConversationStreaming,
} from "@/stores/streamStore";
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
  const pathname = usePathname();
  const [buttonHovered, setButtonHovered] = useState(false);

  // Per-conversation: multiple conversations can stream concurrently.
  const isStreaming = useIsConversationStreaming(id);
  const isAwaitingApproval = useIsConversationAwaitingApproval(id);
  // A turn paused on an approval has already left the streaming phase (its SSE
  // closed), so the dot must key off both — otherwise it would vanish for exactly
  // the wait it exists to advertise.
  const isBusy = isStreaming || isAwaitingApproval;

  // Derive current conversation ID from pathname during render
  const pathParts = pathname.split("/");
  const currentConvoId = pathParts[pathParts.length - 1];

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
      onFocus={() => setButtonHovered(true)}
      onBlur={() => setButtonHovered(false)}
    >
      <Button
        className={`w-full justify-start px-2 font-light text-sm ${isUnread ? "text-white font-normal" : isActive ? "text-zinc-300" : "text-zinc-400 hover:text-zinc-300"}`}
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
        <div className="flex w-full items-center justify-start gap-2">
          {/* Streaming indicator — amber when blocked on your approval, else
              the blue "actively streaming" pulse. */}
          {isBusy && (
            <div
              className={`size-2 shrink-0 rounded-full animate-pulse ${isAwaitingApproval ? "bg-warning" : "bg-primary"}`}
              title={
                isAwaitingApproval
                  ? "Waiting for your approval"
                  : "Streaming..."
              }
            />
          )}
          {/* Unread indicator */}
          {!isBusy && isUnread && (
            <div className="size-2.5 shrink-0 rounded-full bg-primary" />
          )}
          {/* min-w-0 + truncate so a long title shrinks/ellipsizes instead of
              squeezing the fixed-size indicator dot out of view. */}
          <span className="min-w-0 truncate">{name.replace('"', "")}</span>
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
