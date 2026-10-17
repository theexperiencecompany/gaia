import { describe, expect, it } from "vitest";
import {
  applyComposeEvent,
  type ComposeEvent,
  createComposeProgress,
  describeComposeProgress,
} from "../../src/lib/compose-progress.js";
import { parseCloneProgress } from "../../src/lib/git.js";

/** Feed events in order; return each phase label seen. */
function run(events: ComposeEvent[]) {
  const state = createComposeProgress();
  const phases = events.map((event) =>
    describeComposeProgress(applyComposeEvent(state, event)),
  );
  return { state, phases };
}

// Shapes verbatim from `docker compose --progress json pull` (Compose v5.5).
const PULL: ComposeEvent[] = [
  { id: "Image redis:7.2.0-alpine", status: "Working", text: "Pulling" },
  { id: "Image busybox:1.36.0", status: "Working", text: "Pulling" },
  {
    id: "805f301826ef",
    parent_id: "Image busybox:1.36.0",
    status: "Working",
    text: "Downloading",
    details: "1.049MB",
    current: 1_048_576,
    total: 1_999_717,
  },
  {
    id: "9dd56d8e1ce8",
    parent_id: "Image redis:7.2.0-alpine",
    status: "Working",
    text: "Downloading",
    details: "5.243MB",
    current: 5_242_880,
    total: 12_043_699,
  },
  {
    id: "805f301826ef",
    parent_id: "Image busybox:1.36.0",
    status: "Done",
    text: "Pull complete",
  },
  { id: "Image busybox:1.36.0", status: "Done", text: "Pulled" },
];

describe("describeComposeProgress while pulling", () => {
  it("shows the size downloaded and images ready, never layer hashes or a total that is still growing", () => {
    const { phases, state } = run(PULL);

    expect(phases.at(-1)).toEqual({
      stage: "downloading",
      label: "Downloading GAIA's images: 7 MB so far (1 of 2 ready)",
      percent: 52,
    });
    expect(phases.every((p) => !p?.label.includes("805f301826ef"))).toBe(true);
    expect(state.finished).toEqual(["Downloaded busybox:1.36.0"]);
  });

  it("never moves the bar backwards when a new layer's size arrives", () => {
    const { phases } = run([
      ...PULL,
      {
        id: "aaaaaaaaaaaa",
        parent_id: "Image redis:7.2.0-alpine",
        status: "Working",
        text: "Downloading",
        current: 0,
        total: 900_000_000,
      },
    ]);

    expect(phases.at(-1)?.percent).toBe(52);
  });
});

describe("describeComposeProgress while building and starting", () => {
  it("counts build steps instead of echoing apt output", () => {
    const { phases } = run([
      {
        vertexes: [
          { digest: "a", name: "[internal] load build definition" },
          { digest: "b", name: "[1/3] FROM docker.io/library/busybox" },
          { digest: "c", name: "[2/3] RUN apt-get update" },
          { digest: "d", name: "[3/3] RUN echo two" },
        ],
      },
      { vertexes: [{ digest: "b", completed: "2026-10-17T17:24:51Z" }] },
    ]);

    expect(phases.at(-1)).toEqual({
      stage: "building",
      label: "Building GAIA from source: step 2 of 3",
      percent: 33,
    });
  });

  it("says the images are being saved once every step is done, not 'build complete' mid-build", () => {
    const { phases } = run([
      { id: "Image gaia-web", status: "Working", text: "Building" },
      { vertexes: [{ digest: "b", name: "[1/1] RUN true", completed: "x" }] },
    ]);

    expect(phases.at(-1)?.label).toBe(
      "Building GAIA from source: saving the images",
    );
  });

  it("counts services started, by their plain names", () => {
    const { phases, state } = run([
      {
        id: "Container gaia-selfhost-proxy-1",
        status: "Working",
        text: "Creating",
      },
      {
        id: "Container gaia-selfhost-gaia-backend-1",
        status: "Working",
        text: "Starting",
      },
      {
        id: "Container gaia-selfhost-proxy-1",
        status: "Done",
        text: "Started",
      },
    ]);

    expect(phases.at(-1)).toEqual({
      stage: "starting",
      label: "Starting GAIA: starting server (1 of 2 up)",
      percent: 50,
    });
    expect(state.finished).toEqual(["Started proxy"]);
  });

  // Order verbatim from a real `up` of the self-host stack (Compose v5.6): the
  // server is started, then compose holds the web app for its health check.
  it("names the service whose health check compose is waiting on", () => {
    const container = (service: string, text: string): ComposeEvent => ({
      id: `Container gaia-selfhost-${service}-1`,
      status: text === "Waiting" ? "Working" : "Done",
      text,
    });
    const { phases } = run([
      container("mongo", "Started"),
      container("mongo", "Waiting"),
      container("mongo", "Healthy"),
      container("gaia-backend", "Started"),
      container("gaia-backend", "Waiting"),
      { id: "Container gaia-selfhost-gaia-web-1", text: "Created" },
    ]);

    expect(phases.at(-1)).toEqual({
      stage: "starting",
      label: "Starting GAIA: waiting for server to be ready (2 of 3 up)",
      percent: 66,
    });
    expect(
      describeComposeProgress(
        applyComposeEvent(
          run([container("gaia-backend", "Waiting")]).state,
          container("gaia-backend", "Healthy"),
        ),
      )?.label,
    ).toBe("Starting GAIA: 1 of 1 services up");
  });

  it("says the images are unpacking once every layer is downloaded", () => {
    const layer = (id: string, text: string): ComposeEvent => ({
      id,
      parent_id: "Image ghcr.io/theexperiencecompany/gaia:v0.7.0",
      status: "Working",
      text,
      current: 4_000_000,
      total: 4_000_000,
    });
    const pulling: ComposeEvent = {
      id: "Image ghcr.io/theexperiencecompany/gaia:v0.7.0",
      status: "Working",
      text: "Pulling",
    };

    const downloading = run([
      pulling,
      layer("a1", "Downloading"),
      layer("b2", "Already exists"),
      { ...layer("c3", "Downloading"), current: 1_000_000 },
    ]);
    const unpacking = run([
      pulling,
      layer("a1", "Downloading"),
      layer("a1", "Download complete"),
      layer("b2", "Already exists"),
      layer("a1", "Extracting"),
    ]);

    expect(downloading.phases.at(-1)?.label).toMatch(
      /^Downloading GAIA's images: /,
    );
    expect(unpacking.phases.at(-1)?.label).toBe(
      "Unpacking GAIA's images: 4 MB downloaded (0 of 1 ready)",
    );
  });
});

/** A container event from `docker compose --progress json down`. */
function down(service: string, text: string): ComposeEvent {
  const status = text.endsWith("ing") ? "Working" : "Done";
  return { id: `Container gaia-selfhost-${service}-1`, status, text };
}

// Order verbatim from a real `down` of the self-host stack (Compose v5.5).
const DOWN: ComposeEvent[] = [
  down("proxy", "Stopping"),
  down("arq_worker", "Stopping"),
  down("proxy", "Stopped"),
  down("proxy", "Removing"),
  down("proxy", "Removed"),
  down("gaia-backend", "Stopping"),
  down("arq_worker", "Stopped"),
  down("gaia-backend", "Stopped"),
  down("rabbitmq", "Stopping"),
  down("mongo", "Stopping"),
  down("redis", "Stopping"),
  down("redis", "Stopped"),
  down("mongo", "Stopped"),
];

describe("describeComposeProgress while stopping", () => {
  it("names the one service a stop is still waiting on", () => {
    const { phases } = run(DOWN);

    expect(phases.at(-1)).toEqual({
      stage: "stopping",
      label: "Stopping GAIA: waiting on RabbitMQ (5 of 6 stopped)",
      percent: 83,
    });
  });

  it("names the first two it waits on and counts the rest", () => {
    const { phases } = run(DOWN.slice(0, 11));

    expect(phases.at(-1)?.label).toBe(
      "Stopping GAIA: waiting on RabbitMQ, MongoDB and 1 more (3 of 6 stopped)",
    );
  });

  it("counts a container that was already stopped once it is removed", () => {
    const { phases } = run([
      down("bot-telegram", "Removing"),
      down("bot-telegram", "Removed"),
    ]);

    expect(phases.at(-1)?.label).toBe("Stopping GAIA: 1 of 1 stopped");
  });

  it("never reads a stopping container as one starting", () => {
    const { phases } = run(DOWN.slice(0, 2));

    expect(phases.at(-1)?.label).toMatch(/^Stopping GAIA/);
  });
});

describe("parseCloneProgress", () => {
  it("reads the newest update in a chunk with its size, not object counts", () => {
    const chunk =
      "Receiving objects:  22% (49690/225855), 50.11 MiB | 9.80 MiB/s\rReceiving objects:  23% (52157/225855), 52.18 MiB | 10.20 MiB/s";

    expect(parseCloneProgress(chunk)).toEqual({
      percent: 19,
      label: "55 MB so far",
    });
  });

  it("moves to unpacking for deltas", () => {
    expect(parseCloneProgress("Resolving deltas:  50% (1/2)")).toEqual({
      percent: 92,
      label: "Unpacking the files",
    });
  });

  it("says GitHub is preparing the download before any byte arrives", () => {
    expect(
      parseCloneProgress(
        "remote: Counting objects: 100% (812/812), done.\rremote: Compressing objects:  41% (213/519)",
      ),
    ).toEqual({ percent: 0, label: "GitHub is preparing the download" });
  });
});
