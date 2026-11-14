"use client";

import { Button } from "@heroui/button";
import { ArrowUp02Icon, StopIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import {
  type ComposerSendMode,
  useComposerSendMode,
} from "@/features/chat/hooks/useComposerSendMode";
import { useStopStream } from "@/features/chat/hooks/useStopStream";

// One source of truth for the button's look: HeroUI background (`color`)
// and icon color (`currentColor`) decided together so they can't drift.
// Stop wins; otherwise typed content gets the primary fill, empty the muted default.
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
  send: "Send message",
} as const satisfies Record<ComposerSendMode, string>;

// The glyph for each mode, kept out of the JSX so the AnimatePresence wrapper stays flat.
function renderModeContent(mode: ComposerSendMode) {
  return mode === "stop" ? (
    <StopIcon color="currentColor" fill="currentColor" width={20} height={20} />
  ) : (
    <ArrowUp02Icon color="currentColor" />
  );
}

interface SendStopButtonProps {
  /** Whether there is content ready to send. */
  hasContent: boolean;
  /** Submit handler invoked when sending. */
  onSend: () => void;
  /** While true an attachment is still uploading, so send is held. */
  isUploading?: boolean;
  className?: string;
}

/**
 * The chat send button. While GAIA is busy it flips to Stop when the composer
 * is empty; typed content always sends. Single source of truth for both the web composer and the desktop assistant popup —
 * edit here, ships to both.
 */
export default function SendStopButton({
  hasContent,
  onSend,
  isUploading = false,
  className = "h-9 min-h-9 w-9 max-w-9 min-w-9",
}: Readonly<SendStopButtonProps>) {
  const stopStream = useStopStream();
  const { showStop, mode } = useComposerSendMode(hasContent);

  const handlePress = () => {
    if (showStop) {
      void stopStream();
    } else {
      onSend();
    }
  };

  const { bg, contentColor } = getButtonStyle(
    showStop,
    hasContent,
    isUploading,
  );

  const stopCursor = showStop ? "cursor-pointer" : "";

  return (
    <Button
      isIconOnly
      aria-label={MODE_ARIA_LABEL[mode]}
      className={`transition-all duration-300 ${contentColor} ${className} ${stopCursor}`}
      color={bg}
      // Stop is always pressable; send is gated on
      // readiness — there must be content AND no in-flight upload, otherwise the
      // submit is dropped by the composer's uploading guard.
      disabled={!showStop && (!hasContent || isUploading)}
      radius="full"
      // In stop mode the button aborts the stream rather than submitting, so it
      // must not trigger the composer form. Only send submits.
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
