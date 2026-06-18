import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { ArrowUp02Icon, Clock01Icon, StopIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect } from "react";
import { TextMorph } from "torph/react";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useChatStore } from "@/stores/chatStore";
import { useComposerFiles } from "@/stores/composerStore";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";

interface RightSideProps {
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  searchbarText: string | null | undefined;
  selectedTool?: string | null;
  setvoiceModeActive: () => void;
}

export default function RightSide({
  handleFormSubmit,
  searchbarText,
  selectedTool,
  setvoiceModeActive: _setvoiceModeActive,
}: RightSideProps) {
  const { stopStream } = useLoading();
  const { selectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent } = useCalendarEventSelection();
  const { uploadedFiles } = useComposerFiles();
  // True only during the comms agent's initial response (send → main_response_complete).
  const isResponding = useIsMainResponseStreaming();
  const streamingConversationId = useChatStore(
    (state) => state.streamingConversationId,
  );
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const hasText = (searchbarText || "").trim().length > 0;
  const hasSelectedTool = selectedTool != null;
  const hasSelectedWorkflow = selectedWorkflow != null;
  const hasSelectedCalendarEvent = selectedCalendarEvent != null;
  const hasFiles = uploadedFiles.length > 0;
  const hasContent =
    hasText ||
    hasSelectedTool ||
    hasSelectedWorkflow ||
    hasSelectedCalendarEvent ||
    hasFiles;

  // A stream is open for the active conversation across BOTH phases of a turn: the
  // initial response (isResponding) and the held window after it (stream still open
  // while a background executor runs). Any send during this whole window is held in
  // the queue by streamFunction, so the button must reflect that the entire time —
  // not just after the initial response finishes.
  const isStreaming =
    isResponding ||
    (streamingConversationId != null &&
      streamingConversationId === activeConversationId);
  // Typed content during a stream is always queued; an empty composer offers Stop.
  const showQueue = isStreaming && hasContent;
  const showStop = isStreaming && !hasContent;

  const getTooltipContent = () => {
    if (showStop) return "Stop generation";

    if (showQueue) {
      return (
        <div className="flex items-center gap-2">
          Queue message
          <Kbd className="text-zinc-400" keys={["enter"]} />
        </div>
      );
    }

    if (hasSelectedCalendarEvent && !hasText && !hasSelectedTool && !hasFiles) {
      return `Send with calendar event: ${selectedCalendarEvent?.summary}`;
    }

    if (hasSelectedWorkflow && !hasText && !hasSelectedTool && !hasFiles) {
      return `Send with ${selectedWorkflow?.title}`;
    }

    if (hasSelectedTool && !hasText && !hasFiles) {
      // Format tool name to be more readable
      const formattedToolName = selectedTool
        ?.split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
      return `Send with ${formattedToolName}`;
    }

    if (
      hasFiles &&
      !hasText &&
      !hasSelectedTool &&
      !hasSelectedWorkflow &&
      !hasSelectedCalendarEvent
    ) {
      return `Send with ${uploadedFiles.length} file${uploadedFiles.length > 1 ? "s" : ""}`;
    }

    if (!hasContent) {
      return "Message requires content";
    }

    return (
      <div className="flex items-center gap-2">
        Send Message
        <Kbd className="text-zinc-400" keys={["enter"]} />
      </div>
    );
  };

  const handleButtonPress = () => {
    console.log("[QUEUE] button press →", showStop ? "STOP" : "SUBMIT", {
      showStop,
      showQueue,
      hasContent,
      isStreaming,
    });
    if (showStop) {
      stopStream();
    } else {
      handleFormSubmit();
    }
  };

  let buttonColor: "default" | "primary" = "default";
  if (!showStop && hasContent) {
    buttonColor = "primary";
  }

  const mode = showStop ? "stop" : showQueue ? "queue" : "send";

  // [QUEUE] debug: trace every button-mode transition + the flags that drove it.
  useEffect(() => {
    console.log(`[QUEUE] button mode = ${mode.toUpperCase()}`, {
      isResponding,
      streamingConversationId,
      activeConversationId,
      isStreaming,
      hasContent,
      showQueue,
      showStop,
    });
  }, [
    mode,
    isResponding,
    streamingConversationId,
    activeConversationId,
    isStreaming,
    hasContent,
    showQueue,
    showStop,
  ]);

  // Icons inherit `currentColor`, so the button's text color (transitioned via
  // transition-colors) animates the icon color on every state change.
  const contentColor = showStop
    ? "text-zinc-300"
    : hasContent
      ? "text-black"
      : "text-zinc-500";

  return (
    <div className="ml-2 flex items-center gap-2">
      <Tooltip
        content={getTooltipContent()}
        placement="right"
        color={showStop ? "danger" : "primary"}
        showArrow
      >
        <Button
          isIconOnly={!showQueue}
          aria-label={
            showStop
              ? "Stop generation"
              : showQueue
                ? "Queue message"
                : "Send message"
          }
          className={`h-9 min-h-9 transition-all duration-300 ${contentColor} ${
            showQueue
              ? "gap-1.5 rounded-xl px-3"
              : `w-9 max-w-9 min-w-9 ${showStop ? "cursor-pointer" : ""}`
          }`}
          color={buttonColor}
          disabled={!isStreaming && !hasContent}
          radius="full"
          type="submit"
          onPress={handleButtonPress}
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
      </Tooltip>
    </div>
  );
}
