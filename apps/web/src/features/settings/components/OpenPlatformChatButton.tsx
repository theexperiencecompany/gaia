"use client";

import { Comment01Icon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
    <GaiaButton
      size="sm"
      variant="default-soft"
      onPress={openChat}
      isPending={isOpening}
      className="text-xs"
    >
      {!isOpening && <Comment01Icon className="size-4" />}
      Open chat
    </GaiaButton>
  );
}
