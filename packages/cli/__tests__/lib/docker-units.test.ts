import { describe, expect, it } from "vitest";
import { dockerStartState } from "../../src/lib/docker-units.js";

/** `systemctl show containerd.service docker.service -p Id -p ActiveState`, as systemd prints it. */
function show(containerd: string, docker: string): string {
  return `Id=containerd.service\nActiveState=${containerd}\n\nId=docker.service\nActiveState=${docker}\n`;
}

describe("dockerStartState", () => {
  it("waits on containerd before dockerd, since dockerd needs it", () => {
    expect(dockerStartState(show("activating", "inactive"))).toEqual({
      running: false,
      note: "containerd starting",
    });
  });

  it("names dockerd once containerd is up", () => {
    expect(dockerStartState(show("active", "activating"))).toEqual({
      running: false,
      note: "dockerd starting",
    });
    expect(dockerStartState(show("active", "inactive"))).toEqual({
      running: false,
      note: "dockerd starting",
    });
  });

  it("says when a unit failed instead of calling it starting", () => {
    expect(dockerStartState(show("active", "failed"))).toEqual({
      running: false,
      note: "dockerd failed",
    });
  });

  it("is running once both units are active", () => {
    expect(dockerStartState(show("active", "active"))).toEqual({
      running: true,
    });
  });
});
