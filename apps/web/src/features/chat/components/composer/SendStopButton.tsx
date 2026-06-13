"use client";

import { Button } from "@heroui/button";
import { ArrowUp02Icon, StopIcon } from "@icons";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";

interface SendStopButtonProps {
  /** Whether there is content ready to send. */
  hasContent: boolean;
  /** Submit handler invoked when not responding. */
  onSend: () => void;
  className?: string;
}

/**
 * The chat send button that flips into a stop button while the main
 * response is streaming. Single source of truth for both the web
 * composer and the desktop assistant popup — edit here, ships to both.
 */
export default function SendStopButton({
  hasContent,
  onSend,
  className = "h-9 min-h-9 w-9 max-w-9 min-w-9",
}: Readonly<SendStopButtonProps>) {
  const { stopStream } = useLoading();
  // Only the INITIAL response phase locks sending (send → main_response_complete).
  const isResponding = useIsMainResponseStreaming();

  const handlePress = () => {
    if (isResponding) {
      stopStream();
    } else {
      onSend();
    }
  };

  return (
    <Button
      isIconOnly
      aria-label={isResponding ? "Stop generation" : "Send message"}
      className={`${className} ${isResponding ? "cursor-pointer" : ""}`}
      color={!isResponding && hasContent ? "primary" : "default"}
      disabled={!isResponding && !hasContent}
      radius="full"
      type="submit"
      onPress={handlePress}
    >
      {isResponding ? (
        <StopIcon color="lightgray" width={20} height={20} fill="lightgray" />
      ) : (
        <ArrowUp02Icon color={hasContent ? "black" : "gray"} />
      )}
    </Button>
  );
}
