"use client";

import { Button } from "@heroui/button";
import { Comment01Icon } from "@icons";
import { useOpenPlatformChat } from "@/features/settings/hooks/useOpenPlatformChat";

interface OpenPlatformChatButtonProps {
  platform: string;
}

/** Opens a linked Telegram, WhatsApp or iMessage bot's DM chat in the web app. */
export function OpenPlatformChatButton({
  platform,
}: OpenPlatformChatButtonProps) {
  const { openChat, isOpening } = useOpenPlatformChat(platform);

  return (
    <Button
      size="sm"
      variant="flat"
      onPress={openChat}
      isLoading={isOpening}
      startContent={isOpening ? null : <Comment01Icon className="size-4" />}
      className="text-xs"
    >
      Open chat
    </Button>
  );
}
