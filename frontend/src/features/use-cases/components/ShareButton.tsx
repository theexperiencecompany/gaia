"use client";

import { Button } from "@heroui/button";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

interface ShareButtonProps {
  slug: string;
}

export default function ShareButton({ slug }: ShareButtonProps) {
  const [copied, setCopied] = useState(false);
  const shareUrl = `https://heygaia.io/use-cases/${slug}`;

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
          <Check width={18} height={18} />
        ) : (
          <Copy width={18} height={18} />
        )
      }
      onPress={handleCopyLink}
    >
      {copied ? "Copied" : "Copy Link"}
    </Button>
  );
}
