"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Link01Icon, Unlink01Icon } from "@icons";
import type { KeyboardEvent, MouseEvent } from "react";
import { useState } from "react";

import {
  createShortLink,
  stopSharingShortLink,
} from "@/features/short-links/api/shortLinksApi";
import { copyShortLink } from "@/features/short-links/utils/copyShortLink";
import { toast } from "@/lib/toast";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

const DEFAULT_STOPPED_NOTE =
  "The link no longer opens, and GAIA won't share this again unless you copy a new link.";

interface ShareLinkControlsProps {
  targetType: ShortLinkTargetType;
  targetId: string;
  /** What stopping cannot take back, shown before and after stopping. */
  stopWarning?: string;
}

type PendingAction = "copy" | "stop" | null;

function stopPropagation(event: MouseEvent | KeyboardEvent) {
  event.stopPropagation();
}

/**
 * Copy an artifact's public heygaia.link (sharing it if it isn't yet), or stop
 * sharing it. Stops press propagation so it can sit inside a pressable card or
 * row without also opening it.
 */
export function ShareLinkControls({
  targetType,
  targetId,
  stopWarning,
}: ShareLinkControlsProps) {
  const [pending, setPending] = useState<PendingAction>(null);

  const handleCopy = async () => {
    setPending("copy");
    try {
      await copyShortLink(await createShortLink(targetType, targetId));
    } finally {
      setPending(null);
    }
  };

  const handleStop = async () => {
    setPending("stop");
    try {
      await stopSharingShortLink(targetType, targetId);
      toast.success("Sharing stopped", {
        description: stopWarning
          ? `${DEFAULT_STOPPED_NOTE} ${stopWarning}`
          : DEFAULT_STOPPED_NOTE,
      });
    } finally {
      setPending(null);
    }
  };

  return (
    <span
      role="presentation"
      className="flex items-center gap-0.5"
      onClick={stopPropagation}
      onKeyDown={stopPropagation}
    >
      <Tooltip content="Copy public link" placement="bottom">
        <Button
          isIconOnly
          size="sm"
          variant="light"
          aria-label="Copy public link"
          isLoading={pending === "copy"}
          isDisabled={pending === "stop"}
          onPress={handleCopy}
        >
          <Link01Icon size={16} />
        </Button>
      </Tooltip>
      <Tooltip
        content={
          stopWarning ? (
            <div className="max-w-64 py-1">
              <p className="text-sm">Stop sharing</p>
              <p className="text-xs text-zinc-400">{stopWarning}</p>
            </div>
          ) : (
            "Stop sharing"
          )
        }
        placement="bottom"
      >
        <Button
          isIconOnly
          size="sm"
          variant="light"
          aria-label="Stop sharing"
          isLoading={pending === "stop"}
          isDisabled={pending === "copy"}
          onPress={handleStop}
        >
          <Unlink01Icon size={16} />
        </Button>
      </Tooltip>
    </span>
  );
}
