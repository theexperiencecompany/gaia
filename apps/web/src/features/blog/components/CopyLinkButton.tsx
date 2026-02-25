"use client";

import { Button } from "@heroui/button";
import { useState } from "react";
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
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      toast.success("Link copied to clipboard!");

      // Reset the copied state after 2 seconds
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return (
    <Button
      onPress={handleCopyLink}
      variant="light"
      size="sm"
      radius="sm"
      className={className}
      aria-label="Copy link to this post"
    >
      <span>{copied ? "Copied!" : "Copy Link"}</span>
    </Button>
  );
}
