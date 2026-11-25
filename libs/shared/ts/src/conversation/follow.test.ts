import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type ConversationFollowPorts,
  createConversationFollower,
} from "./follow";
import {
  insertFrame,
  patchFrame,
  screenFrame,
  stateFrame,
  userItem,
} from "./testing";
import type { ConversationFrame, FrameGap } from "./types";
import { applyFrame, EMPTY_CONVERSATION_VIEW } from "./view";

const line = (frame: ConversationFrame) => JSON.stringify({ frame });

/** A follower over scripted connections: each one hands over its lines, then closes. */
function following(connections: readonly (readonly string[])[]) {
  const asked: (number | null)[] = [];
  let view = EMPTY_CONVERSATION_VIEW;
  const ports: ConversationFollowPorts = {
    subscribe: async (_conversationId, onData, _signal, after) => {
      const lines = connections[asked.length];
      asked.push(after);
      // Past the script the server holds the stream open: nothing more is read.
      if (!lines) await new Promise(() => undefined);
      else for (const raw of lines) onData(raw);
    },
    isNotFound: () => false,
    statusOf: () => undefined,
    apply: (_conversationId, frame): FrameGap | null => {
      const outcome = applyFrame(view, frame);
      view = outcome.view;
      return outcome.status === "applied" ? null : outcome;
    },
    retitle: vi.fn(),
    prepare: async () => undefined,
    onInvalidFrame: vi.fn(),
    onReopen: vi.fn(),
    onDrop: vi.fn(),
  };
  const release = createConversationFollower(ports).open("c1");
  return { asked, ports, release };
}

const settle = async (connections: number) => {
  for (let tick = 0; tick < connections * 4; tick += 1)
    await vi.advanceTimersByTimeAsync(60_000);
};

afterEach(() => vi.useRealTimers());

describe("the head a follow reconnects after", () => {
  it("opens on the whole screen, then reconnects after the log head its item frames reached", async () => {
    vi.useFakeTimers();
    const { asked, release } = following([
      [
        line(screenFrame([userItem("u1", 1)])),
        line(stateFrame(9, "idle")),
        line(insertFrame(userItem("u2", 2), 3)),
      ],
      [line(screenFrame([], 5))],
    ]);
    await settle(3);
    release();

    expect(asked).toEqual([null, 3, 5]);
  });

  it("reconnects after the head before an entry when cut off between that entry's two frames", async () => {
    vi.useFakeTimers();
    // One entry at seq 4 changes two items: the server names 4 only on the last of its frames.
    const { asked, release } = following([
      [
        line(screenFrame([userItem("u1", 1), userItem("u2", 2)], 3)),
        line(
          patchFrame(
            "u1",
            [{ op: "set", path: ["at"], value: "2026-11-12T10:00:09+00:00" }],
            3,
          ),
        ),
      ],
      [line(insertFrame(userItem("u4", 4), 4))],
    ]);
    await settle(3);
    release();

    expect(asked).toEqual([null, 3, 4]);
  });

  it("opens on the whole screen again after a change that had no place in its copy", async () => {
    vi.useFakeTimers();
    const unplaced = patchFrame(
      "u1",
      [{ op: "set", path: ["message", 0, "text"], value: "x" }],
      2,
    );
    const { asked, ports, release } = following([
      [line(screenFrame([userItem("u1", 1)])), line(unplaced)],
    ]);
    await settle(2);
    release();

    expect(asked).toEqual([null, null]);
    expect(ports.onReopen).toHaveBeenCalledOnce();
  });

  it("opens on the whole screen again after a frame this build could not read", async () => {
    vi.useFakeTimers();
    const { asked, release } = following([
      [
        line(screenFrame([userItem("u1", 1)])),
        JSON.stringify({ frame: { kind: "not_yet_known" } }),
        line(insertFrame(userItem("u2", 2))),
      ],
    ]);
    await settle(2);
    release();

    expect(asked).toEqual([null, null]);
  });
});
