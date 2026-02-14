"use client";

import { Button } from "@heroui/button";
import { Copy01Icon, Tick02Icon } from "@icons";
import { useState } from "react";
import { toast } from "sonner";

interface ShareButtonProps {
  /** ID or slug to use in the URL */
  id: string;
  basePath?: string;
}

export default function ShareButton({
  id,
  basePath = "/use-cases",
}: ShareButtonProps) {
  const [copied, setCopied] = useState(false);
  const shareUrl = `https://heygaia.io${basePath}/${id}`;

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Link copied");
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      toast.error("Failed to copy");
      console.error("Failed to copy:", error);
    }
  };

  return (
    <Button
      variant="flat"
      className="font-light text-zinc-400"
      startContent={
        copied ? (
          <Tick02Icon width={18} height={18} />
        ) : (
          <Copy01Icon width={18} height={18} />
        )
      }
      onPress={handleCopyLink}
    >
      {copied ? "Copied" : "Copy Link"}
    </Button>
  );
}
