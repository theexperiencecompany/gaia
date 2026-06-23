"use client";

import { Avatar } from "@heroui/avatar";
import { Chip } from "@heroui/chip";
import { UserCircle02Icon } from "@icons";

import type { Integration } from "@/features/integrations/types";
import { useUserStore } from "@/stores/userStore";

interface IntegrationHeaderChipsProps {
  integration: Integration;
  isConnected: boolean;
  isOwnIntegration: boolean;
  isForkedIntegration: boolean;
}

/** Connection status + creator attribution chips shown under the icon. */
export function IntegrationHeaderChips({
  integration,
  isConnected,
  isOwnIntegration,
  isForkedIntegration,
}: IntegrationHeaderChipsProps) {
  const currentUserName = useUserStore((state) => state.name);
  const currentUserPicture = useUserStore((state) => state.profilePicture);

  return (
    <div className="flex items-center gap-2 flex-row mb-2">
      {isConnected && (
        <Chip size="sm" variant="flat" color="success" radius="sm">
          Connected
        </Chip>
      )}
      {integration.source === "custom" && (
        <div className="flex items-center gap-1">
          {isForkedIntegration && integration.creator && (
            <Chip
              size="sm"
              variant="flat"
              radius="sm"
              className="text-xs font-light relative text-foreground-500"
              startContent={
                integration.creator.picture ? (
                  <Avatar
                    src={integration.creator.picture || undefined}
                    name={integration.creator.name || undefined}
                    size="sm"
                    className="h-4 w-4"
                  />
                ) : (
                  <UserCircle02Icon width={16} height={16} />
                )
              }
            >
              <div className="flex items-center gap-1.5 text-xs pl-0.5">
                <span>Created by {integration.creator.name || "Unknown"}</span>
              </div>
            </Chip>
          )}
          {isOwnIntegration && (
            <Chip
              size="sm"
              variant="flat"
              color="default"
              radius="sm"
              className="text-xs text-zinc-400 font-light relative right-1"
              startContent={
                <Avatar
                  src={currentUserPicture || undefined}
                  name={currentUserName || undefined}
                  size="sm"
                  className="h-4 w-4"
                />
              }
            >
              Created by You
            </Chip>
          )}
        </div>
      )}
    </div>
  );
}
