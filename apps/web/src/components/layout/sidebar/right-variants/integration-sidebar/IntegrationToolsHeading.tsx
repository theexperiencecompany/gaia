"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Settings01Icon } from "@icons";

interface IntegrationToolsHeadingProps {
  toolCount: number;
  isConnected: boolean;
  showToolsSkeleton: boolean;
  isSettling: boolean;
  onOpenPermissions: () => void;
}

/** The "Available tools" heading: the tool count and Permissions button, or a placeholder title while tools load. */
export function IntegrationToolsHeading({
  toolCount,
  isConnected,
  showToolsSkeleton,
  isSettling,
  onOpenPermissions,
}: IntegrationToolsHeadingProps) {
  if (showToolsSkeleton) {
    return (
      <h2 className="mt-3 text-sm font-medium text-zinc-300 relative right-1">
        {isSettling ? "Setting up tools" : "Available tools"}
      </h2>
    );
  }
  if (toolCount === 0) return null;

  return (
    <div className="relative right-1 mt-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-zinc-300">Available tools</h2>
          {/* Sized off its own height so a one-digit count is a circle
              rather than the default pill, and longer counts grow. */}
          <Chip
            size="sm"
            variant="flat"
            radius="full"
            classNames={{
              base: "h-5 min-w-5 px-0",
              content: "px-1.5 text-xs",
            }}
          >
            {toolCount}
          </Chip>
        </div>
        {isConnected && (
          <Button
            size="sm"
            variant="light"
            className="h-7 shrink-0 px-2 text-xs text-zinc-400"
            startContent={<Settings01Icon className="size-3.5" />}
            onPress={onOpenPermissions}
          >
            Permissions
          </Button>
        )}
      </div>
    </div>
  );
}
