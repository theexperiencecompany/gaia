"use client";

import { Button } from "@heroui/button";
import { AnimatePresence, motion } from "framer-motion";
import type React from "react";
import { useEffect } from "react";
import { Cancel01Icon, LinkBackwardIcon } from "@/icons";
import type { ReplyToMessageData } from "@/stores/replyToMessageStore";

interface SelectedReplyIndicatorProps {
  replyToMessage: ReplyToMessageData | null;
  onRemove?: () => void;
  onNavigate?: (messageId: string) => void;
  /** When true, shows a smaller display-only version with connector line (for chat bubbles) */
  isDisplayOnly?: boolean;
}

/**
 * Truncates content to a maximum length with ellipsis.
 */
const truncateContent = (content: string, maxLength = 70): string => {
  if (content.length <= maxLength) return content;
  return `${content.slice(0, maxLength).trim()}...`;
};

/**
 * 90-degree elbow connector line for threaded reply visualization.
 * Goes from right edge of indicator, down to the message below.
 */
const ReplyConnectorLine: React.FC = () => (
  <div className="absolute -right-7 top-12 -translate-y-1/2 scale-200">
    <svg
      width="14"
      height="20"
      viewBox="0 0 14 20"
      fill="none"
      className="text-zinc-700"
    >
      <title>Reply Connector Line</title>
      <path
        d="M0 3 L5 3 Q11 3 11 9 L11 20"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  </div>
);

const SelectedReplyIndicator: React.FC<SelectedReplyIndicatorProps> = ({
  replyToMessage,
  onRemove,
  onNavigate,
  isDisplayOnly = false,
}) => {
  // Handle Escape key to close the indicator
  useEffect(() => {
    if (!replyToMessage || !onRemove) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onRemove();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [replyToMessage, onRemove]);

  const handleClick = () => {
    if (replyToMessage && onNavigate) {
      onNavigate(replyToMessage.id);
    }
  };

  // Display-only mode: similar to composer version but slightly smaller, with connector line
  if (isDisplayOnly && replyToMessage) {
    return (
      <div className="relative mb-1 mr-6">
        <div
          className="flex items-center gap-2 cursor-pointer px-2.5 py-1.5 rounded-2xl border-dashed border-zinc-500 border-1.5 hover:bg-zinc-700/50 transition-colors max-w-70"
          onClick={handleClick}
        >
          <div className="shrink-0 text-zinc-400">
            <LinkBackwardIcon width={19} height={19} />
          </div>

          <div className="flex flex-col gap-0.5 overflow-hidden">
            <span className="text-xs text-zinc-400 font-semibold">
              {replyToMessage.role === "user" ? "You" : "GAIA"}
            </span>
            <span className="truncate text-sm text-zinc-200">
              {truncateContent(replyToMessage.content, 40)}
            </span>
          </div>
        </div>
        <ReplyConnectorLine />
      </div>
    );
  }

  return (
    <div className="px-2">
      <AnimatePresence>
        {replyToMessage && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            // exit={{ opacity: 0, scale: 0.9, y: 10 }}
            transition={{
              type: "spring",
              damping: 20,
              stiffness: 300,
              duration: 0.2,
            }}
            className="flex mt-2 w-full items-center cursor-pointer justify-between rounded-2xl px-3 py-2 transition-all hover:bg-zinc-700 border-dashed border-zinc-500 border-1.5 group"
            onClick={handleClick}
          >
            <div className="flex items-center gap-2">
              <div className="shrink-0 text-zinc-400">
                <LinkBackwardIcon width={18} height={18} />
              </div>

              <div className="flex flex-col gap-0.5 overflow-hidden w-fit">
                <span className="text-xs text-zinc-400 font-semibold">
                  {replyToMessage.role === "user" ? "You" : "GAIA"}
                </span>
                <span className="truncate text-sm text-zinc-200 w-fit">
                  {truncateContent(replyToMessage.content)}
                </span>
              </div>
            </div>

            <div>
              {onRemove && (
                <Button
                  type="button"
                  onPress={onRemove}
                  isIconOnly
                  size="sm"
                  radius="full"
                >
                  <Cancel01Icon width={14} height={14} />
                </Button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SelectedReplyIndicator;
