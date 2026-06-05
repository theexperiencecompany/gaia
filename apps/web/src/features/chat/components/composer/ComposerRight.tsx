import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { ArrowUp02Icon, StopIcon } from "@icons";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
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

  const getTooltipContent = () => {
    if (isResponding) return "Stop generation";

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
          isIconOnly
          aria-label={isResponding ? "Stop generation" : "Send message"}
          className={`h-9 min-h-9 w-9 max-w-9 min-w-9 ${isResponding ? "cursor-pointer" : ""}`}
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
          ) : (
            <ArrowUp02Icon color={hasContent ? "black" : "gray"} />
          )}
        </Button>
      </Tooltip>
    </div>
  );
}
