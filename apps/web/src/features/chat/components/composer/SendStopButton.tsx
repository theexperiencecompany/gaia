"use client";

import { Button } from "@heroui/button";
import { ArrowUp02Icon, Clock01Icon, StopIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { TextMorph } from "torph/react";
import {
  type ComposerSendMode,
  useComposerSendMode,
} from "@/features/chat/hooks/useComposerSendMode";
import { useLoading } from "@/features/chat/hooks/useLoading";

// One source of truth for the button's look: the HeroUI background (`color`) and
// the icon color (icons inherit `currentColor`, transitioned) are decided
// together so they can never drift apart. Stop wins; otherwise typed content
// gets the primary fill, an empty composer the muted default.
function getButtonStyle(
  showStop: boolean,
  hasContent: boolean,
  isUploading: boolean,
): { bg: "default" | "primary"; contentColor: string } {
  if (showStop) return { bg: "default", contentColor: "text-zinc-300" };
  // An in-flight upload holds the send, so it must read as muted/not-ready
  // rather than the live primary fill even though there is content.
  if (hasContent && !isUploading)
    return { bg: "primary", contentColor: "text-black" };
  return { bg: "default", contentColor: "text-zinc-500" };
}

const MODE_ARIA_LABEL = {
  stop: "Stop generation",
  queue: "Queue message",
  send: "Send message",
} as const satisfies Record<ComposerSendMode, string>;

// The glyph (and Queue label) for each mode. Kept out of the JSX so the
// AnimatePresence wrapper stays flat instead of nesting a ternary.
function renderModeContent(mode: ComposerSendMode) {
  switch (mode) {
    case "stop":
      return (
        <StopIcon
          color="currentColor"
          fill="currentColor"
          width={20}
          height={20}
        />
      );
    case "queue":
      return (
        <>
          <Clock01Icon color="currentColor" width={18} height={18} />
          <TextMorph as="span" className="font-medium text-sm">
            Queue
          </TextMorph>
        </>
      );
    default:
      return <ArrowUp02Icon color="currentColor" />;
  }
}

interface SendStopButtonProps {
  /** Whether there is content ready to send. */
  hasContent: boolean;
  /** Submit handler invoked when sending or queueing. */
  onSend: () => void;
  /** While true an attachment is still uploading, so send is held. */
  isUploading?: boolean;
  className?: string;
}

/**
 * The chat send button. While a stream is open it flips to Stop (empty
 * composer) or Queue (typed content, held behind the running turn). Single
 * source of truth for both the web composer and the desktop assistant popup —
 * edit here, ships to both.
 */
export default function SendStopButton({
  hasContent,
  onSend,
  isUploading = false,
  className = "h-9 min-h-9 w-9 max-w-9 min-w-9",
}: Readonly<SendStopButtonProps>) {
  const { stopStream } = useLoading();
  const { isStreaming, showQueue, showStop, mode } =
    useComposerSendMode(hasContent);

  const handlePress = () => {
    if (showStop) {
      stopStream();
    } else {
      onSend();
    }
  };

  const { bg, contentColor } = getButtonStyle(
    showStop,
    hasContent,
    isUploading,
  );

  // Queue widens into a labelled pill; stop/send stay icon-only square buttons.
  const stopCursor = showStop ? "cursor-pointer" : "";
  const shapeClass = showQueue
    ? "h-9 min-h-9 gap-1.5 rounded-xl px-3"
    : `${className} ${stopCursor}`;

  return (
    <Button
      isIconOnly={!showQueue}
      aria-label={MODE_ARIA_LABEL[mode]}
      className={`transition-all duration-300 ${contentColor} ${shapeClass}`}
      color={bg}
      // While streaming the button is Stop and stays active; otherwise it must
      // be empty of content AND have no in-flight upload before it can send.
      disabled={!isStreaming && (!hasContent || isUploading)}
      radius="full"
      // In stop mode the button aborts the stream rather than submitting, so it
      // must not trigger the composer form. Only send/queue submit.
      type={showStop ? "button" : "submit"}
      onPress={handlePress}
    >
      <AnimatePresence mode="wait" initial={false}>
        <m.span
          key={mode}
          className="flex items-center gap-1.5"
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.6 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
        >
          {renderModeContent(mode)}
        </m.span>
      </AnimatePresence>
    </Button>
  );
}
