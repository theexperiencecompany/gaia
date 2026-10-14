"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Link01Icon } from "@icons";
import { useState } from "react";

import { createShortLink } from "@/features/short-links/api/shortLinksApi";
import { toast } from "@/lib/toast";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

interface ShareLinkButtonProps {
  targetType: ShortLinkTargetType;
  targetId: string;
}

/**
 * Copies the artifact's public heygaia.link to the clipboard, minting it on
 * first use. Anyone with the link can open it, so the toast says so.
 */
export function ShareLinkButton({
  targetType,
  targetId,
}: ShareLinkButtonProps) {
  const [isLoading, setIsLoading] = useState(false);

  const handlePress = async () => {
    setIsLoading(true);
    try {
      const url = await createShortLink(targetType, targetId);
      await navigator.clipboard.writeText(url);
      toast.success("Link copied", {
        description: "Anyone with this link can view it.",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Tooltip content="Copy public link" placement="bottom">
      <Button
        isIconOnly
        size="sm"
        variant="light"
        aria-label="Copy public link"
        isLoading={isLoading}
        onPress={handlePress}
      >
        <Link01Icon size={16} />
      </Button>
    </Tooltip>
  );
}
