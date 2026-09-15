import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import type { FileData } from "@/types/shared/fileTypes";

function resolveUserBubbleStyles(
  isEmojiOnly: boolean,
  emojiCount: number,
  fullWidth: boolean,
): { bubbleClassName: string; textClassName: string } {
  let bubbleClassName = "imessage-bubble imessage-from-me";
  let textClassName = `flex ${fullWidth ? "max-w-full" : "max-w-[30vw]"} text-wrap whitespace-pre-wrap select-text`;

  if (isEmojiOnly) {
    if (emojiCount === 1) {
      bubbleClassName = "select-none"; // No bubble background
      textClassName += " text-5xl leading-none";
    } else if (emojiCount === 2) textClassName += " text-4xl";
    else if (emojiCount === 3) textClassName += " text-3xl";
  }

  return { bubbleClassName, textClassName };
}

interface UseChatBubbleUserParams {
  text: ChatBubbleUserProps["text"];
  fileData: FileData[];
  selectedTool: ChatBubbleUserProps["selectedTool"];
  selectedWorkflow: ChatBubbleUserProps["selectedWorkflow"];
  selectedCalendarEvent: ChatBubbleUserProps["selectedCalendarEvent"];
  fullWidth: boolean;
}

export function useChatBubbleUser({
  text,
  fileData,
  selectedTool,
  selectedWorkflow,
  selectedCalendarEvent,
  fullWidth,
}: UseChatBubbleUserParams) {
  const hasContent =
    !!text ||
    fileData.length > 0 ||
    !!selectedTool ||
    !!selectedWorkflow ||
    !!selectedCalendarEvent;

  const user = useCurrentUser();

  // Calculate emoji state
  const isEmojiOnly = isOnlyEmojis(text);
  const emojiCount = isEmojiOnly ? getEmojiCount(text) : 0;

  // Determine styles based on emoji count
  const { bubbleClassName, textClassName } = resolveUserBubbleStyles(
    isEmojiOnly,
    emojiCount,
    fullWidth,
  );

  return { hasContent, user, isEmojiOnly, bubbleClassName, textClassName };
}
