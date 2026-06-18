"use client";

import { Button } from "@heroui/button";
import { ArrowUp02Icon, Clock01Icon, StopIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect } from "react";
import { TextMorph } from "torph/react";
import { useComposerSendMode } from "@/features/chat/hooks/useComposerSendMode";
import { useLoading } from "@/features/chat/hooks/useLoading";

interface SendStopButtonProps {
  /** Whether there is content ready to send. */
  hasContent: boolean;
  /** Submit handler invoked when sending or queueing. */
  onSend: () => void;
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
  className = "h-9 min-h-9 w-9 max-w-9 min-w-9",
}: Readonly<SendStopButtonProps>) {
  const { stopStream } = useLoading();
  const { isStreaming, showQueue, showStop, mode } =
    useComposerSendMode(hasContent);

  // [QUEUE] debug: trace every button-mode transition while testing the queue UX.
  useEffect(() => {
    console.log(`[QUEUE] button mode = ${mode.toUpperCase()}`, {
      isStreaming,
      hasContent,
      showQueue,
      showStop,
    });
  }, [mode, isStreaming, hasContent, showQueue, showStop]);

  const handlePress = () => {
    console.log("[QUEUE] button press →", showStop ? "STOP" : "SUBMIT");
    if (showStop) {
      stopStream();
    } else {
      onSend();
    }
  };

  // Icons inherit `currentColor`, so the button's text color (transitioned)
  // animates the icon color on every state change.
  const contentColor = showStop
    ? "text-zinc-300"
    : hasContent
      ? "text-black"
      : "text-zinc-500";

  return (
    <Button
      isIconOnly={!showQueue}
      aria-label={
        showStop
          ? "Stop generation"
          : showQueue
            ? "Queue message"
            : "Send message"
      }
      className={`transition-all duration-300 ${contentColor} ${
        showQueue
          ? "h-9 min-h-9 gap-1.5 rounded-xl px-3"
          : `${className} ${showStop ? "cursor-pointer" : ""}`
      }`}
      color={!showStop && hasContent ? "primary" : "default"}
      disabled={!isStreaming && !hasContent}
      radius="full"
      type="submit"
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
          {mode === "stop" ? (
            <StopIcon
              color="currentColor"
              fill="currentColor"
              width={20}
              height={20}
            />
          ) : mode === "queue" ? (
            <>
              <Clock01Icon color="currentColor" width={18} height={18} />
              <TextMorph as="span" className="font-medium text-sm">
                Queue
              </TextMorph>
            </>
          ) : (
            <ArrowUp02Icon color="currentColor" />
          )}
        </m.span>
      </AnimatePresence>
    </Button>
  );
}
