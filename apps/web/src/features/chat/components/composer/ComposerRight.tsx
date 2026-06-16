import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { ArrowUp02Icon, Clock04Icon, StopIcon } from "@icons";
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
  // Only the INITIAL response phase locks the composer (send → main_response_complete).
  // Once the agent has acknowledged the task, the composer unlocks so the user
  // can queue the next message while a background executor keeps running.
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

  // The "held" window: the active conversation's stream is still open but the
  // initial response already finished (so the composer is unlocked). A send here
  // is held in the queue until the stream closes — surface that as a Queue button.
  const isHeldWindow =
    !isResponding &&
    streamingConversationId != null &&
    streamingConversationId === activeConversationId;
  const showQueue = isHeldWindow && hasContent;

  const getTooltipContent = () => {
    if (isResponding) return "Stop generation";

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
    if (isResponding) {
      stopStream();
    } else {
      handleFormSubmit();
    }
  };

  let buttonColor: "default" | "primary" = "default";
  if (!isResponding && hasContent) {
    buttonColor = "primary";
  }

  return (
    <div className="ml-2 flex items-center gap-2">
      <Tooltip
        content={getTooltipContent()}
        placement="right"
        color={isResponding ? "danger" : "primary"}
        showArrow
      >
        <Button
          isIconOnly={!showQueue}
          aria-label={
            isResponding
              ? "Stop generation"
              : showQueue
                ? "Queue message"
                : "Send message"
          }
          className={
            showQueue
              ? "h-9 min-h-9 gap-1.5 px-3"
              : `h-9 min-h-9 w-9 max-w-9 min-w-9 ${isResponding ? "cursor-pointer" : ""}`
          }
          color={buttonColor}
          disabled={!isResponding && !hasContent}
          radius="full"
          type="submit"
          onPress={handleButtonPress}
        >
          {isResponding ? (
            <StopIcon
              color="lightgray"
              width={20}
              height={20}
              fill="lightgray"
            />
          ) : showQueue ? (
            <>
              <Clock04Icon color="black" width={18} height={18} />
              <TextMorph as="span" className="font-medium text-black text-sm">
                Queue
              </TextMorph>
            </>
          ) : (
            <ArrowUp02Icon color={hasContent ? "black" : "gray"} />
          )}
        </Button>
      </Tooltip>
    </div>
  );
}
