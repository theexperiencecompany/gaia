import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  ComposeError,
  explainComposeFailure,
} from "../../src/lib/compose-failure.js";
import {
  applyComposeEvent,
  createComposeProgress,
} from "../../src/lib/compose-progress.js";

const UP = { rebuildCommand: "gaia up --build" };

/** Errors a compose run collected from these JSON events. */
function errorsOf(events: object[]): string[] {
  const state = createComposeProgress();
  for (const event of events) applyComposeEvent(state, event);
  return state.errors;
}

describe("explainComposeFailure", () => {
  // The arm64 pull of gaia-web:latest on an ARM server (cli-audit 14).
  it("names a missing CPU architecture, not an unpublished release", () => {
    const errors = errorsOf([
      {
        id: "Image ghcr.io/theexperiencecompany/gaia-web:latest",
        status: "Error",
        text: "Error",
        details:
          "no matching manifest for linux/arm64/v8 in the manifest list entries",
      },
      {
        error: true,
        message:
          "Error response from daemon: no matching manifest for linux/arm64/v8 in the manifest list entries",
      },
    ]);

    const failure = explainComposeFailure(errors, [], UP);

    expect(failure.cause).toBe(
      "GAIA's web app image (gaia-web) at latest has no build for this computer's processor (arm64).",
    );
    expect(failure.cause).not.toMatch(/published/);
    expect(failure.next).toContain("gaia up --build");
    expect(failure.next).not.toContain("gaia update");
  });

  // Verbatim from docker compose v5.5 against a tag that does not exist.
  it("names an unpublished release", () => {
    const errors = errorsOf([
      {
        id: "Image ghcr.io/theexperiencecompany/gaia-web:v0.6.0",
        status: "Error",
        text: "Error",
        details:
          'failed to resolve reference "ghcr.io/theexperiencecompany/gaia-web:v0.6.0": ghcr.io/theexperiencecompany/gaia-web:v0.6.0: not found',
      },
    ]);

    const failure = explainComposeFailure(errors, [], UP);

    expect(failure.cause).toBe(
      "GAIA v0.6.0 isn't published: GAIA's web app image (gaia-web) doesn't exist in the registry.",
    );
    expect(failure.next).toContain("gaia up --build");
  });

  // cli-audit 12: a resume after an earlier --build run.
  it("names a locally built image that was never built here", () => {
    const failure = explainComposeFailure(
      [
        "Error response from daemon: No such image: gaia-selfhost-gaia-backend:latest",
      ],
      [],
      UP,
    );

    expect(failure.cause).toBe(
      "The image gaia-selfhost-gaia-backend:latest was never built on this machine.",
    );
    expect(failure.next).toBe("Build the images here: gaia up --build.");
  });

  it("names a taken port", () => {
    const failure = explainComposeFailure(
      [
        "Error response from daemon: driver failed programming external connectivity on endpoint gaia-selfhost-proxy-1: Bind for 0.0.0.0:3000 failed: port is already allocated",
      ],
      [],
      UP,
    );

    expect(failure.cause).toBe("Port 3000 is already used by another program.");
    expect(failure.next).toContain("--web-port");
  });

  it("names a service that never became healthy", () => {
    const failure = explainComposeFailure(
      [
        "dependency failed to start: container gaia-selfhost-mongo-1 is unhealthy",
      ],
      [],
      UP,
    );

    expect(failure.cause).toBe("GAIA's MongoDB didn't start.");
    expect(failure.service).toBe("mongo");
  });

  it.each([
    ["write /var/lib/docker/tmp: no space left on device", "The disk is full."],
    [
      'Get "https://ghcr.io/v2/": dial tcp: lookup ghcr.io: no such host',
      "GAIA's images could not be downloaded (network error).",
    ],
    [
      "toomanyrequests: You have reached your pull rate limit.",
      "The image registry is limiting downloads from this network.",
    ],
  ])("names %s", (message, cause) => {
    expect(explainComposeFailure([message], [], UP).cause).toBe(cause);
  });

  it("quotes compose's last error for anything it cannot name, never a cut mid-word", () => {
    const failure = explainComposeFailure(
      ["Error response from daemon: something new went wrong"],
      ["Container gaia-selfhost-redis-1 Created"],
      UP,
    );

    expect(failure.cause).toBe(
      "Docker Compose failed: Error response from daemon: something new went wrong",
    );
  });
});

describe("ComposeError", () => {
  it("reads as cause, the log path, then the next step last, with no compose dump", () => {
    const error = new ComposeError(
      { cause: "The disk is full.", next: "Free some space." },
      path.join(os.homedir(), ".gaia/logs/compose-up-1.log"),
    );

    expect(error.message).toBe(
      "The disk is full.\nFull log: ~/.gaia/logs/compose-up-1.log\nFree some space.",
    );
  });
});
