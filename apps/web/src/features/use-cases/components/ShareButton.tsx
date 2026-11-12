"use client";

import { Copy01Icon, Tick02Icon } from "@icons";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { copyText } from "@/lib/clipboard";
import { siteConfig } from "@/lib/seo";
import { toast } from "@/lib/toast";

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
  const shareUrl = `${siteConfig.url}${basePath}/${id}`;

  const handleCopyLink = async () => {
    try {
      await copyText(shareUrl);
      setCopied(true);
      toast.success("Link copied");
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      toast.error("Failed to copy");
      console.error("Failed to copy:", error);
    }
  };

  return (
    <GaiaButton
      variant="default-soft"
      className="font-light text-zinc-400"
      onPress={handleCopyLink}
    >
      {copied ? (
        <Tick02Icon width={18} height={18} />
      ) : (
        <Copy01Icon width={18} height={18} />
      )}
      {copied ? "Copied link" : "Share"}
    </GaiaButton>
  );
}
