import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";

import { useCalendarEventSelection } from "@/features/chat/hooks/useCalendarEventSelection";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { ArrowUp02Icon, StopIcon } from "@/icons";

interface RightSideProps {
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  searchbarText: string | null | undefined;
  selectedTool?: string | null;
}

export default function RightSide({
  handleFormSubmit,
  searchbarText,
  selectedTool,
}: RightSideProps) {
  const { isLoading, stopStream } = useLoading();
  const { selectedWorkflow } = useWorkflowSelection();
  const { selectedCalendarEvent } = useCalendarEventSelection();
  const hasText = (searchbarText || "").trim().length > 0;
  const hasSelectedTool = selectedTool != null;
  const hasSelectedWorkflow = selectedWorkflow != null;
  const hasSelectedCalendarEvent = selectedCalendarEvent != null;
  const isDisabled =
    isLoading ||
    (!hasText &&
      !hasSelectedTool &&
      !hasSelectedWorkflow &&
      !hasSelectedCalendarEvent);

  const getTooltipContent = () => {
    if (isLoading) return "Stop generation";

    if (hasSelectedCalendarEvent && !hasText && !hasSelectedTool) {
      return `Send with calendar event: ${selectedCalendarEvent?.summary}`;
    }

    if (hasSelectedWorkflow && !hasText && !hasSelectedTool) {
      return `Send with ${selectedWorkflow?.title}`;
    }

    if (hasSelectedTool && !hasText) {
      // Format tool name to be more readable
      const formattedToolName = selectedTool
        ?.split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
      return `Send with ${formattedToolName}`;
    }

    if (!hasText && !hasSelectedTool && !hasSelectedWorkflow) {
      return "Message requires text";
    }

    return (
      <div className="flex items-center gap-2">
        Send Message
        <Kbd className="text-zinc-400" keys={["enter"]}></Kbd>
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

  return (
    <div className="ml-2 flex items-center gap-1">
      <Tooltip content={getTooltipContent()} placement="right" showArrow>
        <Button
          isIconOnly
          aria-label={isLoading ? "Stop generation" : "Send message"}
          className={`h-9 min-h-9 w-9 max-w-9 min-w-9 ${isLoading ? "cursor-pointer" : ""}`}
          color={
            isLoading
              ? "default"
              : hasText || hasSelectedTool || hasSelectedWorkflow
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
              color="lightgray"
              width={20}
              height={20}
              fill="lightgray"
            />
          ) : (
            <ArrowUp02Icon
              color={
                hasText || hasSelectedTool || hasSelectedWorkflow
                  ? "black"
                  : "gray"
              }
            />
          )}
        </Button>
      </Tooltip>
    </div>
  );
}
