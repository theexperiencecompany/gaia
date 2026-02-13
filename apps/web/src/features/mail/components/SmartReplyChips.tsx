"use client";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";

import { useSmartReplies } from "@/features/mail/hooks/useSmartReplies";
import type { SmartReply } from "@/types/features/mailTypes";

interface SmartReplyChipsProps {
  messageId: string;
  onSelectReply: (reply: SmartReply) => void;
}

export function SmartReplyChips({
  messageId,
  onSelectReply,
}: SmartReplyChipsProps) {
  const { data, isLoading } = useSmartReplies(messageId, true);

  if (isLoading) {
    return (
      <div className="flex gap-2 py-2">
        <Skeleton className="h-8 w-24 rounded-full" />
        <Skeleton className="h-8 w-32 rounded-full" />
        <Skeleton className="h-8 w-28 rounded-full" />
      </div>
    );
  }

  if (!data?.smart_replies || data.smart_replies.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 py-2">
      {data.smart_replies.map((reply, index) => (
        <Chip
          key={`${reply.tone}-${index}`}
          variant="flat"
          color={
            reply.tone === "positive"
              ? "success"
              : reply.tone === "action-oriented"
                ? "primary"
                : "default"
          }
          className="cursor-pointer transition-transform hover:scale-105"
          onClick={() => onSelectReply(reply)}
        >
          {reply.title}
        </Chip>
      ))}
    </div>
  );
}
