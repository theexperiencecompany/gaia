"use client";

import { Avatar, Chip } from "@heroui/react";
import { UserCircle02Icon } from "@icons";
import { toneVariants } from "@/components/shared/tone";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import type { Integration } from "@/features/integrations/types";

interface IntegrationHeaderChipsProps {
  integration: Integration;
  isConnected: boolean;
  isOwnIntegration: boolean;
  isForkedIntegration: boolean;
}

/** First letters of the first two words, matching v2's `name`-derived fallback. */
function initialsOf(name?: string | null) {
  if (!name) return undefined;
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/** Connection status + creator attribution chips shown under the icon. */
export function IntegrationHeaderChips({
  integration,
  isConnected,
  isOwnIntegration,
  isForkedIntegration,
}: IntegrationHeaderChipsProps) {
  const { name: currentUserName, profilePicture: currentUserPicture } =
    useCurrentUser();

  return (
    <div className="flex items-center gap-2 flex-row mb-2">
      {isConnected && (
        <Chip size="sm" variant="soft" color="success">
          Connected
        </Chip>
      )}
      {integration.source === "custom" && (
        <div className="flex items-center gap-1">
          {isForkedIntegration && integration.creator && (
            <Chip
              size="sm"
              variant="soft"
              className={toneVariants({
                tone: "muted",
                className: "text-xs font-light relative",
              })}
            >
              {integration.creator.picture ? (
                <Avatar size="sm" className="h-4 w-4">
                  <Avatar.Image src={integration.creator.picture} />
                  <Avatar.Fallback>
                    {initialsOf(integration.creator.name)}
                  </Avatar.Fallback>
                </Avatar>
              ) : (
                <UserCircle02Icon width={16} height={16} />
              )}
              <Chip.Label>
                <div className="flex items-center gap-1.5 text-xs pl-0.5">
                  <span>
                    Created by {integration.creator.name || "Unknown"}
                  </span>
                </div>
              </Chip.Label>
            </Chip>
          )}
          {isOwnIntegration && (
            <Chip
              size="sm"
              variant="soft"
              color="default"
              className={toneVariants({
                tone: "muted",
                className: "text-xs font-light relative right-1",
              })}
            >
              <Avatar size="sm" className="h-4 w-4">
                <Avatar.Image src={currentUserPicture || undefined} />
                <Avatar.Fallback>{initialsOf(currentUserName)}</Avatar.Fallback>
              </Avatar>
              <Chip.Label>Created by You</Chip.Label>
            </Chip>
          )}
        </div>
      )}
    </div>
  );
}
