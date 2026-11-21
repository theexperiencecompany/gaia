"use client";

import { Tooltip } from "@heroui/react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { appName } from "../marketplace/appModel";
import { AppIcon } from "./AppIcon";
import { PropertyRow } from "./PropertyRow";
import { isRepeating, type Task } from "./taskModel";

/** An app's logo, named on hover. */
function AppLogo({ id }: { id: string }) {
  const name = appName(id);
  return (
    <Tooltip delay={200}>
      <Tooltip.Trigger
        aria-label={name}
        render={(props) => <span {...props} className="flex" />}
      >
        <AppIcon id={id} size={15} />
      </Tooltip.Trigger>
      <Tooltip.Content placement="top">{name}</Tooltip.Content>
    </Tooltip>
  );
}

/**
 * The apps GAIA uses for this task (integration_ids). One that is not connected
 * (missing_integrations, or blocked_on_integrations when a run hit it) turns into
 * the action that connects it; a task the lost connection paused runs again after.
 */
export default function TaskApps({
  task,
  update,
}: {
  task: Task;
  update: (patch: Partial<Task>) => void;
}) {
  if (task.integrations.length === 0) return null;
  const missing = task.disconnected ?? [];
  const connected = task.integrations.filter((id) => !missing.includes(id));
  const next = missing[0];
  const wasConnected = task.pauseReason === "integration_expired";
  // Paused for want of an app, lost or never connected: connecting the last one starts it.
  const isWaitingOnApps =
    wasConnected || task.pauseReason === "integration_missing";

  const connect = () => {
    const rest = missing.filter((id) => id !== next);
    const isClear = rest.length === 0 && isWaitingOnApps;
    update({
      disconnected: rest,
      ...(isClear && {
        pauseReason: undefined,
        state: isRepeating(task.when) ? "standing" : "running",
      }),
    });
  };

  return (
    <PropertyRow
      label="Apps"
      hint="The apps GAIA uses for this task. If one gets disconnected, GAIA pauses the task until you connect it again."
    >
      <div className="flex min-w-0 items-center gap-2">
        {connected.map((id) => (
          <AppLogo key={id} id={id} />
        ))}
        {next && (
          <GaiaButton
            size="sm"
            variant="warning-soft"
            inset="tight"
            onPress={connect}
            className="h-7 min-w-0 gap-1.5 text-[13px]"
          >
            <AppIcon id={next} size={14} />
            {wasConnected ? "Reconnect" : "Connect"} {appName(next)}
          </GaiaButton>
        )}
      </div>
    </PropertyRow>
  );
}
