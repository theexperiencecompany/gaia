import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import { execa, type ResultPromise } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  return { ...actual, platform: vi.fn(() => "linux") };
});
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, existsSync: vi.fn(() => true) };
});

import { checkModePorts, ensureDocker } from "../../src/lib/prerequisites.js";
import { createStore } from "../../src/ui/store.js";

const mockedExeca = vi.mocked(execa);

type ExecaCall = [string, string[]?, unknown?];

/** Route execa calls by command line; unmatched calls fail like a missing binary. */
function routeExeca(
  routes: Record<string, () => Partial<Awaited<ResultPromise>>>,
): ExecaCall[] {
  const calls: ExecaCall[] = [];
  mockedExeca.mockImplementation(((cmd: string, args?: string[]) => {
    calls.push([cmd, args]);
    const key = [cmd, ...(args ?? [])].join(" ");
    const match = Object.keys(routes).find((prefix) => key.startsWith(prefix));
    if (!match) return Promise.reject(new Error(`ENOENT ${key}`));
    try {
      return Promise.resolve(routes[match]?.());
    } catch (error) {
      return Promise.reject(error);
    }
  }) as unknown as typeof execa);
  return calls;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(os.platform).mockReturnValue("linux");
  vi.mocked(fs.existsSync).mockReturnValue(true);
  Object.defineProperty(process.stdin, "isTTY", { value: false });
  Object.defineProperty(process.stdout, "isTTY", { value: false });
});

describe("ensureDocker on a fresh apt-based Linux box", () => {
  it("installs Docker without a terminal when --yes consented", async () => {
    let installed = false;
    const calls = routeExeca({
      "docker --version": () => {
        if (!installed) throw new Error("ENOENT docker");
        return { stdout: "Docker version 29" };
      },
      "docker info": () => ({ stdout: "ok" }),
      curl: () => ({ stdout: "" }),
      sudo: () => {
        installed = true;
        return { stdout: "" };
      },
      sh: () => {
        installed = true;
        return { stdout: "" };
      },
    });

    const result = await ensureDocker(createStore(), { assumeYes: true });

    expect(result).toBe("ready");
    expect(calls.some(([cmd]) => cmd === "curl")).toBe(true);
  });

  it("refuses to install without a terminal or --yes, naming --yes", async () => {
    routeExeca({});

    await expect(ensureDocker(createStore())).rejects.toThrow(/--yes/);
  });

  /** Docker answers, but its socket refuses this user until the group applies. */
  const socketRefused = {
    "docker --version": () => ({ stdout: "Docker version 29" }),
    "docker info": () => {
      throw Object.assign(new Error("exit 1"), {
        stderr:
          "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
      });
    },
    id: () => ({ stdout: "aryan sudo adm" }),
    "sudo usermod": () => ({ stdout: "" }),
  };

  it("grants the docker group and relaunches under sg where the system has it", async () => {
    const calls = routeExeca({
      ...socketRefused,
      'sh -c command -v "$1" sh sg': () => ({ stdout: "/usr/bin/sg" }),
    });
    const store = createStore();

    const result = await ensureDocker(store, { assumeYes: true });

    expect(result).toBe("relaunch");
    expect(store.currentState.data.dockerGroupSwitch).toBe("sg");
    expect(
      calls.some(
        ([cmd, args]) =>
          cmd === "sudo" && args?.[0] === "usermod" && args.includes("docker"),
      ),
    ).toBe(true);
  });

  it("relaunches through sudo -g when there is no sg (Ubuntu 26.04)", async () => {
    routeExeca({
      ...socketRefused,
      "sudo -l -g docker --": () => ({ stdout: process.execPath }),
    });
    const store = createStore();

    const result = await ensureDocker(store, { assumeYes: true });

    expect(result).toBe("relaunch");
    expect(store.currentState.data.dockerGroupSwitch).toBe("sudo");
  });

  it("tells the user to start a new login session when nothing can switch groups", async () => {
    routeExeca(socketRefused);
    const store = createStore();

    await expect(ensureDocker(store, { assumeYes: true })).rejects.toThrow(
      /log out and back in \(or run 'newgrp docker'\), then rerun/i,
    );
    expect(store.currentState.data.dockerGroupSwitch).toBeUndefined();
  });
});

describe("checkModePorts", () => {
  it("does not report the self-host proxy's own published port as a conflict", async () => {
    // Hold a real port, as the running proxy would, and report it as GAIA's.
    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const heldPort = (server.address() as net.AddressInfo).port;
    routeExeca({
      "docker ps": () => ({ stdout: `0.0.0.0:${heldPort}->80/tcp` }),
    });

    try {
      const results = await checkModePorts("selfhost", { 3000: heldPort });
      const web = results.find((r) => r.port === heldPort);
      expect(web?.available).toBe(true);
    } finally {
      server.close();
    }
  });

  it("still reports a port held by something else", async () => {
    const server = net.createServer();
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const heldPort = (server.address() as net.AddressInfo).port;
    routeExeca({ "docker ps": () => ({ stdout: "" }) });

    try {
      const results = await checkModePorts("selfhost", { 3000: heldPort });
      const web = results.find((r) => r.port === heldPort);
      expect(web?.available).toBe(false);
    } finally {
      server.close();
    }
  });
});
