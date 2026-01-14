import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";

import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { ArrowUp02Icon, StopIcon } from "@/icons";
import { useComposerFiles } from "@/stores/composerStore";

interface RightSideProps {
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  searchbarText: string | null | undefined;
  selectedTool?: string | null;
  // setvoiceModeActive: () => void;
}

export default function RightSide({
  handleFormSubmit,
  searchbarText,
  selectedTool,
  // setvoiceModeActive,
}: RightSideProps) {
  const { isLoading, stopStream } = useLoading();
  const { selectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent } = useCalendarEventSelection();
  const { uploadedFiles } = useComposerFiles();
  const hasText = (searchbarText || "").trim().length > 0;
  const hasSelectedTool = selectedTool != null;
  const hasSelectedWorkflow = selectedWorkflow != null;
  const hasSelectedCalendarEvent = selectedCalendarEvent != null;
  const hasFiles = uploadedFiles.length > 0;
  const isDisabled =
    isLoading ||
    (!hasText &&
      !hasSelectedTool &&
      !hasSelectedWorkflow &&
      !hasSelectedCalendarEvent &&
      !hasFiles);

  const getTooltipContent = () => {
    if (isLoading) return "Stop generation";

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

    if (
      !hasText &&
      !hasSelectedTool &&
      !hasSelectedWorkflow &&
      !hasFiles &&
      !hasSelectedCalendarEvent
    ) {
      return "Message requires content";
    }

    return (
      <div className="flex items-center gap-2">
        Send Message
        <Kbd className="text-foreground-400" keys={["enter"]}></Kbd>
      </div>
    );
  };

  const handleButtonPress = () => {
    if (isLoading) {
      stopStream();
    } else {
      handleFormSubmit();
    }
  };


  const isAvailable = hasText ||
                  hasSelectedTool ||
                  hasSelectedWorkflow ||
                  hasFiles ||
                  hasSelectedCalendarEvent ;
  return (
    <div className="ml-2 flex items-center gap-2">
      {/* <Tooltip content="Voice Mode" placement="left" color="primary" showArrow>
        <Button
          isIconOnly
          aria-label="Voice Mode"
          className="h-9 min-h-9 w-9 max-w-9 min-w-9"
          color="default"
          radius="full"
          type="button"
          onPress={() => setvoiceModeActive()}
        >
          <AudioWaveIcon className="text-foreground-400" />
        </Button>
      </Tooltip> */}

      <Tooltip
        content={getTooltipContent()}
        placement="right"
        color={isLoading ? "danger" : "primary"}
        showArrow
      >
        <Button
          isIconOnly
          aria-label={isLoading ? "Stop generation" : "Send message"}
          className={`h-9 min-h-9 w-9 max-w-9 min-w-9 ${isAvailable ? "bg-primary" : "bg-surface-200 dark:bg-surface-300"} ${isLoading ? "cursor-pointer bg-surface-200 dark:bg-surface-300" : ""}`}
          color={
            isLoading
              ? "default"
              : isAvailable
                ? "primary"
                : "default"
          }
          disabled={!isLoading && isDisabled}
          radius="full"
          type="submit"
          onPress={handleButtonPress}
        >
          {isLoading ? (
            <StopIcon
              className="text-foreground-600"
              width={20}
              height={20}
            />
          ) : (
            <ArrowUp02Icon
              className={
                hasText ||
                hasSelectedTool ||
                hasSelectedWorkflow ||
                hasFiles ||
                hasSelectedCalendarEvent
                  ? "text-surface-50"
                  : "text-foreground-600"
              }
            />
          )}
        </Button>
      </Tooltip>
    </div>
  );
}
