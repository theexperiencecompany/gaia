"use client";

import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon } from "@icons";

import { isWorkAnswered } from "@/features/chat/utils/workChip";
import { useChatStore } from "@/stores/chatStore";

/**
 * The status chip of a turn that handed work off while GAIA said nothing: it
 * reads "Working on it" until the answer lands in the conversation, then "Done".
 * It is the saved turn itself (kind `accepted`), so a reload shows it too.
 */
export default function WorkChip({ messageId }: { messageId: string }) {
  const answered = useChatStore((state) =>
    Object.values(state.messagesByConversation).some((messages) =>
      isWorkAnswered(messages, messageId),
    ),
  );

  return (
    <Chip
      size="sm"
      variant="flat"
      color={answered ? "success" : "default"}
      startContent={
        answered ? (
          <CheckmarkCircle02Icon className="size-3.5" />
        ) : (
          <Spinner size="sm" color="current" className="scale-75" />
        )
      }
    >
      {answered ? "Done" : "Working on it"}
    </Chip>
  );
}
