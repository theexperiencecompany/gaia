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
vi.mock("../../src/lib/logs.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  newLogPath: (name: string) => `/tmp/gaia-cli-test-${name}.log`,
}));
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, existsSync: vi.fn(() => true) };
});
// The watcher reads this machine's /var/log/dpkg.log; these tests fake apt itself.
vi.mock("../../src/lib/apt-activity.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/apt-activity.js")>()),
  watchAptActivity: () => () => undefined,
}));

import {
  dockerInstallPhase,
  ensurePrerequisites,
  INSTALL_CONFIRM_INPUT,
  MISSING_PREREQUISITES_KEY,
} from "../../src/lib/prerequisite-install.js";
import { checkModePorts } from "../../src/lib/prerequisites.js";
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
    if (!match) {
      return Promise.reject(
        Object.assign(new Error(`ENOENT ${key}`), { code: "ENOENT" }),
      );
    }
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
  Object.defineProperty(process.stdin, "isTTY", {
    value: false,
    configurable: true,
  });
  Object.defineProperty(process.stdout, "isTTY", {
    value: false,
    configurable: true,
  });
});

describe("ensureDocker on a fresh apt-based Linux box", () => {
  it("installs Docker without a terminal when --yes consented", async () => {
    let installed = false;
    const calls = routeExeca({
      "docker info": () => {
        if (!installed) {
          throw Object.assign(new Error("spawn docker ENOENT"), {
            code: "ENOENT",
          });
        }
        return { stdout: "ok" };
      },
      curl: () => ({ stdout: "" }),
      "sudo -n true": () => ({ stdout: "" }),
      "sudo -n sh": () => {
        installed = true;
        return { stdout: "" };
      },
    });

    const result = await ensurePrerequisites(createStore(), {
      assumeYes: true,
      needGit: false,
    });

    expect(result).toBe("ready");
    expect(calls.some(([cmd]) => cmd === "curl")).toBe(true);
    // The installer runs non-interactively with its output piped to a log,
    // never inherited onto the screen Ink draws.
    const install = (mockedExeca.mock.calls as unknown as ExecaCall[]).find(
      ([cmd, args]) => cmd === "sudo" && args?.[1] === "sh",
    );
    expect(install?.[2]).toMatchObject({ all: true });
    expect(install?.[2]).not.toHaveProperty("stdio");
  });

  it("reads which stage Docker's installer is in from the commands it traces", () => {
    expect(
      dockerInstallPhase(
        "+ sh -c DEBIAN_FRONTEND=noninteractive apt-get -y -qq install docker-ce docker-ce-cli >/dev/null",
      ),
    ).toEqual({
      stage: "downloading",
      packages: ["docker-ce", "docker-ce-cli"],
    });
    expect(dockerInstallPhase("+ sh -c apt-get -qq update >/dev/null")).toEqual(
      { stage: "preparing", detail: "package lists" },
    );
    expect(
      dockerInstallPhase(
        "+ sh -c DEBIAN_FRONTEND=noninteractive apt-get -y -qq install ca-certificates curl >/dev/null",
      ),
    ).toEqual({ stage: "preparing", detail: "what Docker needs" });
    expect(dockerInstallPhase("+ sh -c systemctl start docker")).toEqual({
      stage: "starting",
    });
    expect(dockerInstallPhase("Reading package lists...")).toBeNull();
  });

  it("refuses to install without a terminal or --yes, naming --yes", async () => {
    routeExeca({});
    const store = createStore();

    await expect(
      ensurePrerequisites(store, { needGit: false }),
    ).rejects.toThrow(/--yes/);
    expect(store.currentState.data.checks.docker).toBe("error");
  });

  /** Docker answers, but its socket refuses this user until the group applies. */
  const socketRefused = {
    "docker info": () => {
      throw Object.assign(new Error("exit 1"), {
        stderr:
          "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
      });
    },
    id: () => ({ stdout: "aryan sudo adm" }),
    "sudo -n true": () => ({ stdout: "" }),
    "sudo -n usermod": () => ({ stdout: "" }),
  };

  it("grants the docker group and relaunches under sg where the system has it", async () => {
    const calls = routeExeca({
      ...socketRefused,
      'sh -c command -v "$1" sh sg': () => ({ stdout: "/usr/bin/sg" }),
    });
    const store = createStore();

    const result = await ensurePrerequisites(store, {
      assumeYes: true,
      needGit: false,
    });

    expect(result).toBe("relaunch");
    expect(store.currentState.data.dockerGroupSwitch).toBe("sg");
    expect(
      calls.some(
        ([cmd, args]) =>
          cmd === "sudo" && args?.[1] === "usermod" && args.includes("docker"),
      ),
    ).toBe(true);
  });

  it("relaunches through sudo -g when there is no sg (Ubuntu 26.04)", async () => {
    routeExeca({
      ...socketRefused,
      "sudo -l -g docker --": () => ({ stdout: process.execPath }),
    });
    const store = createStore();

    const result = await ensurePrerequisites(store, {
      assumeYes: true,
      needGit: false,
    });

    expect(result).toBe("relaunch");
    expect(store.currentState.data.dockerGroupSwitch).toBe("sudo");
  });

  it("tells the user to start a new login session when nothing can switch groups", async () => {
    routeExeca(socketRefused);
    const store = createStore();

    await expect(
      ensurePrerequisites(store, { assumeYes: true, needGit: false }),
    ).rejects.toThrow(
      /log out and back in \(or run 'newgrp docker'\), then rerun/i,
    );
    expect(store.currentState.data.dockerGroupSwitch).toBeUndefined();
  });
});

describe("ensureGit on a fresh apt-based Linux box", () => {
  it("installs git through apt when --yes consented", async () => {
    let installed = false;
    const calls = routeExeca({
      "git --version": () => {
        if (!installed) throw new Error("ENOENT git");
        return { stdout: "git version 2.51" };
      },
      "sudo -n true": () => ({ stdout: "" }),
      "docker info": () => ({ stdout: "ok" }),
      "sudo -n apt-get update": () => ({ stdout: "" }),
      "sudo -n apt-get install -y git": () => {
        installed = true;
        return { stdout: "" };
      },
    });
    const store = createStore();

    await ensurePrerequisites(store, { assumeYes: true, needGit: true });

    expect(store.currentState.data.checks.git).toBe("success");
    expect(
      calls.map(([cmd, args]) => [cmd, ...(args ?? [])].join(" ")),
    ).toEqual(expect.arrayContaining(["sudo -n apt-get install -y git"]));
  });

  it("refuses to install git without a terminal or --yes, and marks it failed", async () => {
    routeExeca({});
    const store = createStore();

    await expect(ensurePrerequisites(store, { needGit: true })).rejects.toThrow(
      /--yes/,
    );
    expect(store.currentState.data.checks.git).toBe("error");
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
describe("ensurePrerequisites asks once for everything missing", () => {
  it("offers Git and Docker in one confirmation, then installs both", async () => {
    Object.defineProperty(process.stdin, "isTTY", {
      value: true,
      configurable: true,
    });
    Object.defineProperty(process.stdout, "isTTY", {
      value: true,
      configurable: true,
    });
    let gitInstalled = false;
    let dockerInstalled = false;
    routeExeca({
      "git --version": () => {
        if (!gitInstalled) throw new Error("ENOENT git");
        return { stdout: "git version 2.51" };
      },
      "docker info": () => {
        if (!dockerInstalled) {
          throw Object.assign(new Error("spawn docker ENOENT"), {
            code: "ENOENT",
          });
        }
        return { stdout: "ok" };
      },
      curl: () => ({ stdout: "" }),
      "sudo -n true": () => ({ stdout: "" }),
      "sudo -n apt-get": () => {
        gitInstalled = true;
        return { stdout: "" };
      },
      "sudo -n sh": () => {
        dockerInstalled = true;
        return { stdout: "" };
      },
    });
    const store = createStore();
    const ask = vi.spyOn(store, "waitForInput").mockResolvedValue("install");

    const result = await ensurePrerequisites(store, { needGit: true });

    expect(result).toBe("ready");
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledWith(INSTALL_CONFIRM_INPUT);
    expect(store.currentState.data[MISSING_PREREQUISITES_KEY]).toEqual([
      "git",
      "docker",
    ]);
    expect(store.currentState.data.checks).toEqual({
      git: "success",
      docker: "success",
    });
  });

  it("names the command to run again once a declined install is done", async () => {
    Object.defineProperty(process.stdin, "isTTY", {
      value: true,
      configurable: true,
    });
    Object.defineProperty(process.stdout, "isTTY", {
      value: true,
      configurable: true,
    });
    routeExeca({});
    const store = createStore();
    vi.spyOn(store, "waitForInput").mockResolvedValue("decline");

    await expect(
      ensurePrerequisites(store, { needGit: false, rerunCommand: "gaia up" }),
    ).rejects.toThrow(
      /^Skipped installing Docker\. .*then run 'gaia up' again\.$/,
    );
  });

  it("names both manual installs when the user declines", async () => {
    Object.defineProperty(process.stdin, "isTTY", {
      value: true,
      configurable: true,
    });
    Object.defineProperty(process.stdout, "isTTY", {
      value: true,
      configurable: true,
    });
    routeExeca({});
    const store = createStore();
    vi.spyOn(store, "waitForInput").mockResolvedValue("decline");

    await expect(ensurePrerequisites(store, { needGit: true })).rejects.toThrow(
      /^Skipped installing Git and Docker\. Install them \(https:.*\), then run this command again\.$/,
    );
    expect(store.currentState.data.checks).toEqual({
      git: "error",
      docker: "error",
    });
  });
});
