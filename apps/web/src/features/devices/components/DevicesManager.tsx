"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { ComputerIcon, Delete02Icon, Folder01Icon, Link04Icon } from "@icons";
import { BRIDGE_ADD_COMMAND, BRIDGE_CLI_NAME } from "../constants";
import { useDevices } from "../hooks/useDevices";
import type { Device } from "../types";

function DeviceRow({
  device,
  onRevoke,
  isRevoking,
}: {
  device: Device;
  onRevoke: (id: string) => void;
  isRevoking: boolean;
}) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <ComputerIcon className="mt-0.5 size-5 text-zinc-400" />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium">{device.name}</span>
              <Chip
                size="sm"
                color={device.online ? "success" : "default"}
                variant="flat"
              >
                {device.online ? "Online" : "Offline"}
              </Chip>
            </div>
            <p className="text-sm text-zinc-500">
              {device.platform ?? "unknown"}
              {device.daemon_version ? ` v${device.daemon_version}` : ""}
            </p>
          </div>
        </div>
        <Button
          size="sm"
          variant="flat"
          color="danger"
          isLoading={isRevoking}
          startContent={<Delete02Icon className="size-4" />}
          onPress={() => onRevoke(device.id)}
        >
          Revoke
        </Button>
      </div>

      {device.servers.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          {device.servers.map((server) => (
            <div
              key={server.integration_id}
              className="flex items-center gap-2 rounded-2xl bg-zinc-900 p-3 text-sm"
            >
              {server.server_key === "filesystem" ? (
                <Folder01Icon className="size-4 text-zinc-400" />
              ) : (
                <Link04Icon className="size-4 text-zinc-400" />
              )}
              <span>{server.display_name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function DevicesManager() {
  const { devices, isLoading, error, refetch, revokeDevice, revokingId } =
    useDevices();

  if (isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800 p-6 text-center text-sm text-zinc-400">
        <span>Couldn&apos;t load your devices.</span>
        <Button size="sm" variant="flat" onPress={() => void refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (devices.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-800 p-6 text-center text-sm text-zinc-400">
        No devices paired yet. Install the{" "}
        <span className="font-mono">{BRIDGE_CLI_NAME}</span> CLI and run{" "}
        <span className="font-mono">{BRIDGE_ADD_COMMAND}</span> to connect your
        machine.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {devices.map((device) => (
        <DeviceRow
          key={device.id}
          device={device}
          onRevoke={revokeDevice}
          isRevoking={revokingId === device.id}
        />
      ))}
    </div>
  );
}
