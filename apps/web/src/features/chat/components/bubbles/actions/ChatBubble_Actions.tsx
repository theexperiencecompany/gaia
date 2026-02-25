import { Button } from "@heroui/button";
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
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useReplyToMessage } from "@/stores/replyToMessageStore";

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
  const { updateConvoMessages } = useConversation();
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

  const copyToClipboard = () => {
    // Remove NEW_MESSAGE_BREAK tokens for cleaner copy
    const cleanText = text.replace(/<NEW_MESSAGE_BREAK>/g, "\n\n");
    navigator.clipboard.writeText(cleanText);
    toast.info("Copied to clipboard", {
      description: `${cleanText.slice(0, 30)}...`,
    });

    // toast.success("Copied to clipboard", {
    //   unstyled: true,
    //   classNames: {
    //     toast: "flex items-center p-3 rounded-xl gap-3 w-[350px] toast_custom",
    //     title: "text-black text-sm",
    //     description: "text-sm text-black",
    //   },
    //   duration: 3000,
    //   description: `${text.substring(0, 35)}...`,
    //   icon: <Task01Icon color="black" height="23" />,
    // });
  };

  const handlePinToggle = async () => {
    try {
      if (!convoIdParam) return;

      if (!message_id) return;

      // Pin/unpin the message
      await chatApi.togglePinMessage(convoIdParam, message_id, !pinned);

      toast.success(pinned ? "Message unpinned!" : "Message pinned!");

      // Fetch messages again to reflect the pin state
      await chatApi.fetchMessages(convoIdParam);

      updateConvoMessages();
    } catch (error) {
      toast.error("Could not pin this message");
      console.error("Could not pin this message", error);
    }
  };

  const handleThumbsUp = () => {
    trackEvent(ANALYTICS_EVENTS.CHAT_MESSAGE_FEEDBACK, {
      message_id,
      message_role: messageRole,
      message_content: text,
      conversation_id: convoIdParam,
      is_positive: true,
    });

    toast.success("Thanks for your feedback!");
  };

  const handleThumbsDown = () => {
    trackEvent(ANALYTICS_EVENTS.CHAT_MESSAGE_FEEDBACK, {
      message_id,
      message_role: messageRole,
      message_content: text,
      conversation_id: convoIdParam,
      is_positive: false,
    });

    toast.info("Thanks for your feedback!");
  };

  return (
    <>
      {!loading && (
        <div className="flex w-fit items-center">
          <Tooltip content="Reply" placement="bottom">
            <Button
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
              variant="light"
              onPress={handleReply}
            >
              <LinkBackwardIcon
                className="cursor-pointer"
                height="18"
                width="18"
              />
            </Button>
          </Tooltip>

          <Tooltip content="Copy to clipboard" placement="bottom">
            <Button
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
              variant="light"
              onPress={copyToClipboard}
            >
              <Copy01Icon className="cursor-pointer" height="20" width="20" />
            </Button>
          </Tooltip>

          <Tooltip content="Pin message" placement="bottom">
            <Button
              isIconOnly
              className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
              variant="light"
              radius="lg"
              onPress={handlePinToggle}
              color={pinned ? "primary" : "default"}
            >
              <PinIcon className={`cursor-pointer`} height="20" width="20" />
            </Button>
          </Tooltip>

          {messageRole === "assistant" && (
            <Tooltip content="Helpful response" placement="bottom">
              <Button
                isIconOnly
                className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
                variant="light"
                radius="lg"
                onPress={handleThumbsUp}
              >
                <ThumbsUpIcon
                  className={`cursor-pointer`}
                  height="20"
                  width="20"
                />
              </Button>
            </Tooltip>
          )}

          {messageRole === "assistant" && (
            <Tooltip content="Not helpful" placement="bottom">
              <Button
                isIconOnly
                className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
                variant="light"
                radius="lg"
                onPress={handleThumbsDown}
              >
                <ThumbsDownIcon
                  className={`cursor-pointer`}
                  height="20"
                  width="20"
                />
              </Button>
            </Tooltip>
          )}

          {onRetry && (
            <Tooltip content="Retry" placement="bottom">
              <Button
                isIconOnly
                isDisabled={isRetrying}
                className="aspect-square size-7.5 min-w-7.5 rounded-md p-0! text-zinc-500 hover:text-zinc-300"
                variant="light"
                radius="lg"
                onPress={onRetry}
              >
                <RedoIcon
                  className={`cursor-pointer ${isRetrying ? "animate-spin" : ""}`}
                  height="18"
                  width="18"
                />
              </Button>
            </Tooltip>
          )}
          {/*
          <TranslateDropdown
            text={text}
            index={index}
            trigger={
              <Button
                variant="light"
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
