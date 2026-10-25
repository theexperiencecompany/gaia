/**
 * What Docker's first start is waiting on, read from systemd: containerd
 * comes up first, then dockerd on top of it.
 * @module lib/docker-units
 */

import { execa } from "execa";

/** In start order: dockerd needs containerd. */
const UNITS = [
  { id: "containerd.service", name: "containerd" },
  { id: "docker.service", name: "dockerd" },
] as const;

const POLL_MS = 1000;

/** systemd states on the way to active. */
const NOT_YET = new Set(["inactive", "activating", "reloading"]);

/** Where Docker's start is: a note while a unit is still coming up, or running. */
export type DockerStartState =
  | { running: false; note: string }
  | { running: true };

/** The ActiveState of each unit in `systemctl show -p Id -p ActiveState` output. */
function activeStates(output: string): Map<string, string> {
  const states = new Map<string, string>();
  for (const block of output.split(/\n\s*\n/)) {
    const fields = new Map(
      block
        .split("\n")
        .map((line) => line.split("=", 2) as [string, string | undefined]),
    );
    const id = fields.get("Id");
    const state = fields.get("ActiveState");
    if (id && state) states.set(id, state);
  }
  return states;
}

/** "containerd starting", "dockerd failed", or running once both units are active. */
export function dockerStartState(systemctlShow: string): DockerStartState {
  const states = activeStates(systemctlShow);
  for (const unit of UNITS) {
    const state = states.get(unit.id);
    if (state === "active") continue;
    // Not started yet reads the same as starting: dpkg or the script is about to start it.
    const doing =
      state === undefined || NOT_YET.has(state) ? "starting" : state;
    return { running: false, note: `${unit.name} ${doing}` };
  }
  return { running: true };
}

/**
 * Report Docker's start about once a second until the returned stop function
 * is called; a systemctl that fails ends the watch through onError.
 */
export function watchDockerStart(
  onState: (state: DockerStartState) => void,
  onError: (error: Error) => void,
): () => void {
  let polling = false;
  let stopped = false;
  const timer = setInterval(() => {
    if (polling) return;
    polling = true;
    execa("systemctl", [
      "show",
      ...UNITS.map((unit) => unit.id),
      "-p",
      "Id",
      "-p",
      "ActiveState",
    ]).then(
      ({ stdout }) => {
        polling = false;
        if (!stopped) onState(dockerStartState(stdout));
      },
      (error: unknown) => {
        clearInterval(timer);
        if (!stopped) onError(error as Error);
      },
    );
  }, POLL_MS);
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
