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
  it("shows the size downloaded of the size known, and images ready, never layer hashes", () => {
    const { phases, state } = run(PULL);

    expect(phases.at(-1)).toEqual({
      label: "Downloading GAIA: 7 MB of 14 MB (1 of 2 images ready)",
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
      label: "Starting GAIA: 1 of 2 services up",
      percent: 50,
    });
    expect(state.finished).toEqual(["Started proxy"]);
  });
});

describe("parseCloneProgress", () => {
  it("reads the newest update in a chunk with its size, not object counts", () => {
    const chunk =
      "Receiving objects:  22% (49690/225855), 50.11 MiB | 9.80 MiB/s\rReceiving objects:  23% (52157/225855), 52.18 MiB | 10.20 MiB/s";

    expect(parseCloneProgress(chunk)).toEqual({
      percent: 19,
      label: "52.18 MiB downloaded",
    });
  });

  it("moves to unpacking for deltas", () => {
    expect(parseCloneProgress("Resolving deltas:  50% (1/2)")).toEqual({
      percent: 92,
      label: "Unpacking the files",
    });
  });
});
