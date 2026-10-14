"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Link01Icon } from "@icons";
import { useRef, useState } from "react";

import { createShortLink } from "@/features/short-links/api/shortLinksApi";
import { copyShortLink } from "@/features/short-links/utils/copyShortLink";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

interface ShareLinkButtonProps {
  targetType: ShortLinkTargetType;
  targetId: string;
}

/**
 * Copies the public heygaia.link of an artifact that was not handed one when
 * it was produced (a past workflow run), minting it on first use.
 */
export function ShareLinkButton({
  targetType,
  targetId,
}: ShareLinkButtonProps) {
  const [isLoading, setIsLoading] = useState(false);
  const latestRequestId = useRef(0);

  const handlePress = async () => {
    const requestId = ++latestRequestId.current;
    setIsLoading(true);
    try {
      await copyShortLink(await createShortLink(targetType, targetId));
    } finally {
      if (requestId === latestRequestId.current) setIsLoading(false);
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
