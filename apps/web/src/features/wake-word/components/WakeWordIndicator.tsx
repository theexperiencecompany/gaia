"use client";

import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { Mic02Icon, MicOff02Icon } from "@icons";
import { useHeyGaia } from "../hooks/useHeyGaia";

interface WakeWordIndicatorProps {
  enabled: boolean;
  onDetected?: () => void;
}

/**
 * Small floating indicator showing the wake-word listener state. Drops into
 * any layout — typically the bottom-right of the chat surface.
 */
export function WakeWordIndicator({
  enabled,
  onDetected,
}: WakeWordIndicatorProps) {
  const { state, lastDetection, error } = useHeyGaia({ enabled });

  if (lastDetection && onDetected) onDetected();

  const tooltipContent = error
    ? `Wake word error: ${error.message}`
    : state === "listening"
      ? "Listening for 'Hey GAIA'"
      : state === "detecting"
        ? "Detected!"
        : state === "cooldown"
          ? "Cooling down"
          : "Wake word disabled";

  return (
    <Tooltip content={tooltipContent} placement="left">
      <div className="rounded-2xl bg-zinc-800 p-2">
        {state === "idle" || !enabled ? (
          <MicOff02Icon className="size-5 text-zinc-400" />
        ) : state === "detecting" ? (
          <Spinner size="sm" color="success" />
        ) : (
          <Mic02Icon className="size-5 text-emerald-400" />
        )}
      </div>
    </Tooltip>
  );
}
