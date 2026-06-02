import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { ArrowUp02Icon } from "@icons";
import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useComposerFiles } from "@/stores/composerStore";

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
  const { selectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent } = useCalendarEventSelection();
  const { uploadedFiles } = useComposerFiles();
  const hasText = (searchbarText || "").trim().length > 0;
  const hasSelectedTool = selectedTool != null;
  const hasSelectedWorkflow = selectedWorkflow != null;
  const hasSelectedCalendarEvent = selectedCalendarEvent != null;
  const hasFiles = uploadedFiles.length > 0;
  // The send button never reflects stream loading — sending while a response is
  // streaming queues the next message (see useChatStream's pending-stream queue).
  const hasContent =
    hasText ||
    hasSelectedTool ||
    hasSelectedWorkflow ||
    hasSelectedCalendarEvent ||
    hasFiles;

  const getTooltipContent = () => {
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
      <Tooltip
        content={getTooltipContent()}
        placement="right"
        color="primary"
        showArrow
      >
        <Button
          isIconOnly
          aria-label="Send message"
          className="h-9 min-h-9 w-9 max-w-9 min-w-9"
          color={hasContent ? "primary" : "default"}
          disabled={!hasContent}
          radius="full"
          type="submit"
          onPress={() => handleFormSubmit()}
        >
          <ArrowUp02Icon color={hasContent ? "black" : "gray"} />
        </Button>
      </Tooltip>
    </div>
  );
}
