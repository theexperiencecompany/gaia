"use client";
import { ChatBotIcon, Mail01Icon, StarIcon } from "@icons";
import React, { type FC, useState } from "react";
import { LinkButton } from "@/components/shared/LinkButton";
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
  // Persisted counterpart of the transient awaiting-approval pulse: a
  // background run's card survives reloads, where stream state does not.
  hasPendingApproval?: boolean;
}

export const ChatTab: FC<ChatTabProps> = ({
  name,
  id,
  starred,
  isSystemGenerated = false,
  systemPurpose,
  isUnread = false,
  hasPendingApproval = false,
}) => {
  const pathname = usePathname();
  const [buttonHovered, setButtonHovered] = useState(false);

  // Per-conversation: multiple conversations can stream concurrently.
  const isStreaming = useIsConversationStreaming(id);
  const isAwaitingApproval = useIsConversationAwaitingApproval(id);
  // A turn paused on an approval has left the streaming phase (SSE closed), so
  // the dot keys off both; hasPendingApproval covers reloads and background
  // runs where no stream state exists.
  const showApprovalDot = isAwaitingApproval || hasPendingApproval;
  const isBusy = isStreaming || showApprovalDot;

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
      <LinkButton
        href={`/c/${id}`}
        className={`w-full justify-start font-light text-sm ${isUnread ? "font-normal" : ""}`}
        size="sm"
        inset="tight"
        tone={isUnread ? "default" : isActive ? "dim" : "muted"}
        hoverTone={isUnread || isActive ? "none" : "dim"}
        variant={isActive ? "secondary" : "ghost"}
        onClick={() => setButtonHovered(false)}
      >
        {getIcon() &&
          React.cloneElement(getIcon()!, {
            width: 18,
            height: 18,
          })}
        <div className="flex w-full items-center justify-start gap-2">
          {/* Streaming indicator — amber when blocked on your approval, else
              the blue "actively streaming" pulse. */}
          {isBusy && (
            <div
              className={`size-2 shrink-0 rounded-full animate-pulse ${showApprovalDot ? "bg-warning" : "bg-accent"}`}
              title={
                showApprovalDot ? "Waiting for your approval" : "Streaming..."
              }
            />
          )}
          {/* Unread indicator */}
          {!isBusy && isUnread && (
            <div className="size-2.5 shrink-0 rounded-full bg-accent" />
          )}
          {/* min-w-0 + truncate so a long title shrinks/ellipsizes instead of
              squeezing the fixed-size indicator dot out of view. */}
          <span className="min-w-0 truncate">{name.replace('"', "")}</span>
        </div>
      </LinkButton>

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
