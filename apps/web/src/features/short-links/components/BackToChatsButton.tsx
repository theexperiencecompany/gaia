"use client";

import { Button } from "@heroui/button";
import { ArrowLeft01Icon } from "@icons";
import Link from "next/link";

import { useIsSignedIn } from "@/features/auth/hooks/useIsSignedIn";

/** Returns a signed-in viewer to their chats; renders nothing for anyone else. */
export function BackToChatsButton() {
  const isSignedIn = useIsSignedIn();
  if (!isSignedIn) return null;
  return (
    <Button
      as={Link}
      href="/c"
      size="sm"
      variant="flat"
      startContent={<ArrowLeft01Icon size={16} />}
    >
      Back to chats
    </Button>
  );
}
