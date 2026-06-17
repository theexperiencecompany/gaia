import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { AudioWave01Icon } from "@icons";
import SendStopButton from "@/features/chat/components/composer/SendStopButton";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useComposerFiles } from "@/stores/composerStore";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";

interface RightSideProps {
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  searchbarText: string | null | undefined;
  selectedTool?: string | null;
  setvoiceModeActive: () => void;
  /** Hover intent on the voice button — prefetches the session token. */
  onVoiceModeHover?: () => void;
}

export default function RightSide({
  handleFormSubmit,
  searchbarText,
  selectedTool,
  setvoiceModeActive,
  onVoiceModeHover,
}: RightSideProps) {
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

  return (
    <div className="ml-2 flex items-center gap-2">
      <Tooltip content="Voice Mode" placement="left" color="primary" showArrow>
        <Button
          isIconOnly
          aria-label="Voice Mode"
          className="h-9 min-h-9 w-9 max-w-9 min-w-9"
          color="default"
          radius="full"
          type="button"
          onMouseEnter={onVoiceModeHover}
          onPress={() => setvoiceModeActive()}
        >
          <AudioWave01Icon className="text-zinc-400" />
        </Button>
      </Tooltip>

      <Tooltip
        content={getTooltipContent()}
        placement="right"
        color={isResponding ? "danger" : "primary"}
        showArrow
      >
        <SendStopButton hasContent={hasContent} onSend={handleFormSubmit} />
      </Tooltip>
    </div>
  );
}
