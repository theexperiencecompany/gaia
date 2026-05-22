"use client";

import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { Mic02Icon, MicOff02Icon } from "@icons";
import { useEffect } from "react";
import { useHeyGaia } from "../hooks/useHeyGaia";

type WakeWordState = ReturnType<typeof useHeyGaia>["state"];

interface WakeWordIndicatorProps {
  enabled: boolean;
  onDetected?: () => void;
}

function tooltipFor(state: WakeWordState, error: Error | null): string {
  if (error) return `Wake word error: ${error.message}`;
  switch (state) {
    case "listening":
      return "Listening for 'Hey GAIA'";
    case "detecting":
      return "Detected!";
    case "cooldown":
      return "Cooling down";
    default:
      return "Wake word disabled";
  }
}

function StatusIcon({
  state,
  enabled,
}: Readonly<{ state: WakeWordState; enabled: boolean }>) {
  if (state === "idle" || !enabled) {
    return <MicOff02Icon className="size-5 text-zinc-400" />;
  }
  if (state === "detecting") {
    return <Spinner size="sm" color="success" />;
  }
  return <Mic02Icon className="size-5 text-emerald-400" />;
}

/**
 * Small floating indicator showing the wake-word listener state. Drops into
 * any layout — typically the bottom-right of the chat surface.
 */
export function WakeWordIndicator({
  enabled,
  onDetected,
}: Readonly<WakeWordIndicatorProps>) {
  const { state, lastDetection, error } = useHeyGaia({ enabled });

  useEffect(() => {
    if (lastDetection && onDetected) onDetected();
  }, [lastDetection, onDetected]);

  return (
    <Tooltip content={tooltipFor(state, error)} placement="left">
      <div className="rounded-2xl bg-zinc-800 p-2">
        <StatusIcon state={state} enabled={enabled} />
      </div>
    </Tooltip>
  );
}
