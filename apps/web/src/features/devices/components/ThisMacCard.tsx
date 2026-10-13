"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Switch } from "@heroui/switch";
import { Tooltip } from "@heroui/tooltip";
import {
  ComputerIcon,
  Delete02Icon,
  Folder01Icon,
  Link04Icon,
  RedoIcon,
} from "@icons";
import type { DeviceServerView } from "@shared/bridge-core/ipc.types";
import type { UseBridge } from "../hooks/useBridge";
import { thisDeviceLabel } from "../hooks/useDesktopPlatform";
import { AddServerModal } from "./AddServerModal";
import { FileAccessSection } from "./FileAccessSection";

function StatusChip({
  paired,
  running,
}: {
  paired: boolean;
  running: boolean;
}) {
  if (!paired)
    return (
      <Chip size="sm" variant="flat" color="default">
        Not connected
      </Chip>
    );
  return (
    <Chip size="sm" variant="flat" color={running ? "success" : "warning"}>
      {running ? "Online" : "Paused"}
    </Chip>
  );
}

/** Per-server connect state: a spinner while the background test+register runs,
 * a Retry button (with the error in a tooltip) on failure, a success dot when
 * connected. */
function ServerStateIndicator({
  state,
  error,
  onRetry,
  disabled,
}: {
  state: DeviceServerView["state"];
  error?: string;
  onRetry: () => void;
  disabled: boolean;
}) {
  if (state === "connecting")
    return <Spinner size="sm" aria-label="Connecting" />;
  if (state === "error")
    return (
      <Tooltip content={error ?? "Failed to connect"} color="danger">
        <Button
          size="sm"
          variant="flat"
          color="warning"
          isDisabled={disabled}
          startContent={<RedoIcon width={14} height={14} />}
          onPress={onRetry}
        >
          Retry
        </Button>
      </Tooltip>
    );
  return (
    <span
      role="img"
      aria-label="Connected"
      className="size-2 rounded-full bg-success"
    />
  );
}

function ServerRow({
  server,
  onRemove,
  onRetry,
  disabled,
}: {
  server: DeviceServerView;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex items-center gap-2 rounded-2xl bg-zinc-900 p-3 text-sm">
      {server.type === "filesystem" ? (
        <Folder01Icon className="size-4 text-zinc-400" />
      ) : (
        <Link04Icon className="size-4 text-zinc-400" />
      )}
      <span className="min-w-0 flex-1 truncate">{server.name}</span>
      <ServerStateIndicator
        state={server.state}
        error={server.error}
        onRetry={() => onRetry(server.key)}
        disabled={disabled}
      />
      <Button
        isIconOnly
        size="sm"
        variant="light"
        color="danger"
        isDisabled={disabled}
        aria-label={`Remove ${server.name}`}
        onPress={() => onRemove(server.key)}
      >
        <Delete02Icon className="size-4" />
      </Button>
    </div>
  );
}

/**
 * "This computer" — the desktop app's own device, controlled in-app over the
 * bridge IPC surface (no CLI, no pairing code). Renders only inside the desktop
 * app (gated by the caller). Pairing is one click and the tunnel toggles live;
 * while connected GAIA can run commands and read/write files on the machine
 * (via run_on_device). On macOS the file-access section grants the OS-level
 * permissions those commands need (per-folder prompts + Full Disk Access).
 */
export function ThisMacCard({
  bridge,
  platform,
}: {
  bridge: UseBridge;
  platform: NodeJS.Platform | null;
}) {
  const {
    status,
    servers,
    busy,
    pair,
    setRunning,
    addServer,
    retryServer,
    removeServer,
  } = bridge;
  const label = thisDeviceLabel(platform);
  const noun = platform === "darwin" ? "this Mac" : "this computer";

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <ComputerIcon className="mt-0.5 size-5 text-zinc-400" />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium">{label}</span>
              <StatusChip paired={status.paired} running={status.running} />
            </div>
            <p className="text-sm text-zinc-500">
              While connected, GAIA can run commands and use MCP servers on{" "}
              {noun}.
            </p>
          </div>
        </div>
        {status.paired ? (
          <div className="flex items-center gap-2">
            {busy === "toggle" && <Spinner size="sm" />}
            <Switch
              size="sm"
              isSelected={status.running}
              isDisabled={busy === "toggle"}
              onValueChange={(next) => void setRunning(next)}
              aria-label={`Keep ${noun} connected`}
            />
          </div>
        ) : (
          <Button
            size="sm"
            color="primary"
            variant="flat"
            isLoading={busy === "pair"}
            onPress={() => void pair()}
          >
            Enable on {noun}
          </Button>
        )}
      </div>

      {status.paired && (
        <div className="mt-3 flex flex-col gap-2">
          {servers.map((server) => (
            <ServerRow
              key={server.key}
              server={server}
              onRemove={(key) => void removeServer(key)}
              onRetry={(key) => void retryServer(key)}
              disabled={busy === "server"}
            />
          ))}
          <div className="flex">
            <AddServerModal onAdd={addServer} isBusy={busy === "server"} />
          </div>
          {platform === "darwin" && <FileAccessSection />}
        </div>
      )}
    </div>
  );
}
