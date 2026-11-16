import { Tooltip } from "@heroui/react";
import {
  Copy01Icon,
  LinkBackwardIcon,
  PinIcon,
  RedoIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "@icons";
import { useParams } from "next/navigation";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { chatApi } from "@/features/chat/api/chatApi";
import { copyWithFeedback } from "@/lib/clipboard";
import { toast } from "@/lib/toast";
import { syncSingleConversation } from "@/services/syncService";
import { useReplyToMessage } from "@/stores/composerStore";

interface ChatBubbleActionsProps {
  loading: boolean;
  text: string;
  pinned?: boolean;
  message_id: string;
  messageRole?: "user" | "assistant";
  onRetry?: () => void;
  isRetrying?: boolean;
}

export default function ChatBubble_Actions({
  message_id,
  loading,
  text,
  pinned = false,
  messageRole = "assistant",
  onRetry,
  isRetrying = false,
}: ChatBubbleActionsProps) {
  const { id: convoIdParam } = useParams<{ id: string }>();
  const { setReplyToMessage } = useReplyToMessage();

  const handleReply = () => {
    // Truncate content for preview (first 150 chars)
    const truncatedContent =
      text.length > 150 ? `${text.slice(0, 150)}...` : text;
    setReplyToMessage({
      id: message_id,
      content: truncatedContent,
      role: messageRole,
    });
  };

  const copyToClipboard = async () => {
    // Remove NEW_MESSAGE_BREAK tokens for cleaner copy
    const cleanText = text.replace(/<NEW_MESSAGE_BREAK>/g, "\n\n");
    if (!(await copyWithFeedback(cleanText))) return;
    toast.info("Copied to clipboard", {
      description: `${cleanText.slice(0, 30)}...`,
    });
  };

  const handlePinToggle = async () => {
    try {
      if (!convoIdParam) return;

      if (!message_id) return;

      // No client analytics here: conversation_service.py already records
      // chat:message_pinned / chat:message_unpinned once, server-side.
      await chatApi.togglePinMessage(convoIdParam, message_id, !pinned);

      toast.success(pinned ? "Message unpinned!" : "Message pinned!");

      // Pull the server's updated pin state into IndexedDB + the store.
      await syncSingleConversation(convoIdParam);
    } catch (error) {
      toast.error("Could not pin this message");
      console.error("Could not pin this message", error);
    }
  };

  const submitFeedback = (isPositive: boolean) => {
    chatApi.submitMessageFeedback(message_id, isPositive).catch(() => {
      /* silent by design */
    });
    if (isPositive) {
      toast.success("Thanks for your feedback!");
    } else {
      toast.info("Thanks for your feedback!");
    }
  };

  const handleThumbsUp = () => submitFeedback(true);
  const handleThumbsDown = () => submitFeedback(false);

  return (
    <>
      {!loading && (
        <div className="flex w-fit items-center">
          <Tooltip>
            <GaiaButton
              aria-label="Reply"
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md"
              variant="ghost"
              tone="faint"
              hoverTone="dim"
              onPress={handleReply}
            >
              <LinkBackwardIcon
                className="cursor-pointer"
                height="18"
                width="18"
              />
            </GaiaButton>
            <Tooltip.Content placement="bottom">Reply</Tooltip.Content>
          </Tooltip>

          <Tooltip>
            <GaiaButton
              aria-label="Copy to clipboard"
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md"
              variant="ghost"
              tone="faint"
              hoverTone="dim"
              onPress={copyToClipboard}
            >
              <Copy01Icon className="cursor-pointer" height="20" width="20" />
            </GaiaButton>
            <Tooltip.Content placement="bottom">
              Copy to clipboard
            </Tooltip.Content>
          </Tooltip>

          <Tooltip>
            <GaiaButton
              aria-label="Pin message"
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md"
              variant="ghost"
              tone="faint"
              hoverTone="dim"
              onPress={handlePinToggle}
            >
              <PinIcon className={`cursor-pointer`} height="20" width="20" />
            </GaiaButton>
            <Tooltip.Content placement="bottom">Pin message</Tooltip.Content>
          </Tooltip>

          {messageRole === "assistant" && (
            <Tooltip>
              <GaiaButton
                aria-label="Helpful response"
                isIconOnly
                className="aspect-square size-7.5 min-w-7.5 rounded-md"
                variant="ghost"
                tone="faint"
                hoverTone="dim"
                onPress={handleThumbsUp}
              >
                <ThumbsUpIcon
                  className={`cursor-pointer`}
                  height="20"
                  width="20"
                />
              </GaiaButton>
              <Tooltip.Content placement="bottom">
                Helpful response
              </Tooltip.Content>
            </Tooltip>
          )}

          {messageRole === "assistant" && (
            <Tooltip>
              <GaiaButton
                aria-label="Not helpful"
                isIconOnly
                className="aspect-square size-7.5 min-w-7.5 rounded-md"
                variant="ghost"
                tone="faint"
                hoverTone="dim"
                onPress={handleThumbsDown}
              >
                <ThumbsDownIcon
                  className={`cursor-pointer`}
                  height="20"
                  width="20"
                />
              </GaiaButton>
              <Tooltip.Content placement="bottom">Not helpful</Tooltip.Content>
            </Tooltip>
          )}

          {onRetry && (
            <Tooltip>
              <GaiaButton
                aria-label="Retry"
                isIconOnly
                isDisabled={isRetrying}
                className="aspect-square size-7.5 min-w-7.5 rounded-md"
                variant="ghost"
                tone="faint"
                hoverTone="dim"
                onPress={onRetry}
              >
                <div className={isRetrying ? "animate-spin" : ""}>
                  <RedoIcon className="cursor-pointer" height="18" width="18" />
                </div>
              </GaiaButton>
              <Tooltip.Content placement="bottom">Retry</Tooltip.Content>
            </Tooltip>
          )}
          {/*
          <TranslateDropdown
            text={text}
            index={index}
            trigger={
              <Button
                variant="tertiary"
                className="w-fit p-0 h-fit rounded-md"
                isIconOnly
                style={{ minWidth: "22px" }}
              >
                <TranslateIcon height="22" className="cursor-pointer" />
              </Button>
            }
          /> */}

          {/* <TextToSpeech text={text} /> */}
        </div>
      )}
    </>
  );
}
