// @vitest-environment jsdom

import type { ServerConfig } from "@shared/bridge-core/config.types";
import type {
  BridgeInvokeResult,
  BridgeStatus,
} from "@shared/bridge-core/ipc.types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThisMacCard } from "@/features/devices/components/ThisMacCard";
import { useBridge } from "@/features/devices/hooks/useBridge";

/**
 * "This Mac" is the desktop app's own device, driven over the bridge IPC
 * surface. Two behaviours must hold or the card is broken: (1) "Enable on this
 * Mac" is ONE action — pair AND bring the tunnel up, so the toggle lands on;
 * (2) a paired device lists its exposed servers and removing one calls the
 * host. Remove the auto-start or the server wiring and these go red.
 */

const bridge = {
  pair: vi.fn(),
  status: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  listServers: vi.fn(),
  addServer: vi.fn(),
  removeServer: vi.fn(),
  retryServer: vi.fn(),
  onStatusChanged: vi.fn(() => noop),
  onServersChanged: vi.fn(() => noop),
};

/** Stand-in unsubscribe for the status-change listener. */
function noop(): void {
  // no cleanup needed in the mocked bridge
}

vi.mock("@/lib/electron/api", () => ({
  getElectronAPI: () => ({ isElectron: true, bridge }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ok = <T,>(value: T): BridgeInvokeResult<T> => ({ ok: true, value });
const status = (
  paired: boolean,
  running: boolean,
  deviceId: string | null = null,
): BridgeStatus => ({ paired, running, deviceId });

// The card takes the bridge hook result as a prop; drive the real hook against
// the mocked window.api.bridge so the test exercises the actual wiring.
function Harness() {
  return <ThisMacCard bridge={useBridge()} platform="darwin" />;
}

beforeEach(() => {
  vi.clearAllMocks();
  bridge.onStatusChanged.mockReturnValue(noop);
  bridge.onServersChanged.mockReturnValue(noop);
  bridge.listServers.mockResolvedValue(ok<ServerConfig[]>([]));
});

describe("ThisMacCard", () => {
  it("enables in one click: pairs then starts the tunnel", async () => {
    bridge.status.mockResolvedValue(ok(status(false, false)));
    // Fresh pair is not yet serving; the card must start it itself.
    bridge.pair.mockResolvedValue(ok(status(true, false)));
    bridge.start.mockResolvedValue(ok(status(true, true)));

    render(<Harness />);

    const enable = await screen.findByRole("button", {
      name: /enable on this mac/i,
    });
    fireEvent.click(enable);

    await waitFor(() => expect(bridge.pair).toHaveBeenCalledTimes(1));
    expect(bridge.start).toHaveBeenCalledTimes(1);

    const toggle = (await screen.findByRole("switch", {
      name: /keep this mac connected/i,
    })) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
  });

  it("lists exposed servers and removes one", async () => {
    bridge.status.mockResolvedValue(ok(status(true, true)));
    bridge.listServers.mockResolvedValue(
      ok<ServerConfig[]>([
        {
          type: "stdio",
          key: "everything",
          name: "Everything server",
          command: "npx",
          args: [],
          env: {},
        },
      ]),
    );
    bridge.removeServer.mockResolvedValue(ok<ServerConfig[]>([]));

    render(<Harness />);

    await screen.findByText("Everything server");

    fireEvent.click(
      screen.getByRole("button", { name: /remove everything server/i }),
    );

    await waitFor(() =>
      expect(bridge.removeServer).toHaveBeenCalledWith("everything"),
    );
  });
});
