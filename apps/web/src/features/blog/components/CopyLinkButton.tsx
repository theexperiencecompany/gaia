"use client";

import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { copyText } from "@/lib/clipboard";
import { toast } from "@/lib/toast";

interface CopyLinkButtonProps {
  className?: string;
}

export default function CopyLinkButton({
  className = "",
}: CopyLinkButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopyLink = async () => {
    try {
      await copyText(window.location.href);
      setCopied(true);
      toast.success("Link copied to clipboard!");

      // Reset the copied state after 2 seconds
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return (
    <GaiaButton
      onPress={handleCopyLink}
      variant="ghost"
      size="sm"
      className={className}
      aria-label="Copy link to this post"
    >
      <span>{copied ? "Copied!" : "Copy Link"}</span>
    </GaiaButton>
  );
}
