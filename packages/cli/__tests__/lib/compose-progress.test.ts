import { describe, expect, it } from "vitest";
import {
  applyComposeEvent,
  createComposeProgress,
  describeComposeProgress,
} from "../../src/lib/compose-progress.js";
import type {
  ComposeEvent,
  ComposePhase,
} from "../../src/lib/compose-progress.types.js";
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
  it("shows the bytes downloaded of the layers' summed total, and images ready, never layer hashes", () => {
    const { phases, state } = run(PULL);

    expect(phases.at(-1)).toEqual({
      stage: "downloading",
      label: "Downloading GAIA's images: 7 / 14 MB (1 of 2 ready)",
      detail: "1 of 2 images ready",
      percent: 51,
      amount: {
        done: 1_999_717 + 5_242_880,
        total: 1_999_717 + 12_043_699,
        unit: "bytes",
        estimated: false,
      },
    });
    expect(phases.every((p) => !p?.label.includes("805f301826ef"))).toBe(true);
    expect(state.finished).toEqual(["Downloaded busybox:1.36.0"]);
  });

  it("marks the total an estimate while a layer has not said its size", () => {
    const { phases } = run([
      ...PULL,
      {
        id: "bbbbbbbbbbbb",
        parent_id: "Image redis:7.2.0-alpine",
        status: "Working",
        text: "Waiting",
      },
    ]);

    const amount = phases.at(-1)?.amount;
    expect(amount?.estimated).toBe(true);
    // The unsized layer counts as the average of the sized two.
    expect(amount?.total).toBe(Math.round((1_999_717 + 12_043_699) * 1.5));
  });

  it("leaves a layer that already exists out of the download's total", () => {
    const { phases } = run([
      ...PULL,
      {
        id: "cccccccccccc",
        parent_id: "Image redis:7.2.0-alpine",
        status: "Done",
        text: "Already exists",
      },
    ]);

    expect(phases.at(-1)?.amount).toMatchObject({
      total: 1_999_717 + 12_043_699,
      estimated: false,
    });
  });

  it("never shrinks the total once it has been shown", () => {
    const state = createComposeProgress();
    for (const event of PULL) applyComposeEvent(state, event);
    applyComposeEvent(state, {
      id: "dddddddddddd",
      parent_id: "Image redis:7.2.0-alpine",
      status: "Working",
      text: "Waiting",
    });
    const before = describeComposeProgress(state)?.amount?.total ?? 0;
    applyComposeEvent(state, {
      id: "dddddddddddd",
      parent_id: "Image redis:7.2.0-alpine",
      status: "Working",
      text: "Downloading",
      current: 0,
      total: 1_000,
    });

    expect(describeComposeProgress(state)?.amount?.total).toBe(before);
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
      detail: "starting server",
      percent: 50,
      amount: { done: 1, total: 2, unit: "services", estimated: false },
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
      detail: "waiting for server to be ready",
      percent: 66,
      amount: { done: 2, total: 3, unit: "services", estimated: false },
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

describe("describeComposeProgress with the pull's size read from the registry", () => {
  const image = "Image ghcr.io/theexperiencecompany/gaia:v0.7.0";
  const layer = (id: string, text: string, current?: number): ComposeEvent => ({
    id,
    parent_id: image,
    status: "Working",
    text,
    ...(current === undefined ? {} : { current, total: 1 }),
  });
  const expected = new Map([
    ["aaaaaaaaaaaa", 600e6],
    ["bbbbbbbbbbbb", 300e6],
    ["cccccccccccc", 100e6],
  ]);

  function phaseAfter(events: ComposeEvent[]) {
    const state = createComposeProgress(expected);
    let phase: ComposePhase | null = null;
    for (const event of [
      { id: image, status: "Working", text: "Pulling" },
      ...events,
    ]) {
      phase = describeComposeProgress(applyComposeEvent(state, event));
    }
    return phase;
  }

  it("shows the whole pull's size from the start, not only the layers begun", () => {
    const phase = phaseAfter([layer("aaaaaaaaaaaa", "Downloading", 150e6)]);

    expect(phase?.amount).toEqual({
      done: 150e6,
      total: 1000e6,
      unit: "bytes",
      estimated: false,
    });
    expect(phase?.percent).toBe(15);
  });

  it("counts a finished layer whole, and leaves out one already here", () => {
    const phase = phaseAfter([
      layer("aaaaaaaaaaaa", "Downloading", 150e6),
      layer("aaaaaaaaaaaa", "Download complete"),
      layer("cccccccccccc", "Already exists"),
      layer("bbbbbbbbbbbb", "Downloading", 30e6),
    ]);

    expect(phase?.amount).toMatchObject({ done: 630e6, total: 900e6 });
    expect(phase?.label).toBe(
      "Downloading GAIA's images: 630 / 900 MB (0 of 1 ready)",
    );
  });
});
