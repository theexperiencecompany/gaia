/**
 * The bot delivery state machine, frame sequence in, platform operations out.
 *
 * Each case is one R-case reply as the stream frames a bot receives, and the
 * exact ordered sends, edits, deletes and pauses each platform class makes of it.
 * "tick" is the throttled preview a live platform renders between chunks.
 */
import {
  type DeliveryEvent,
  type DeliveryOp,
  type DeliveryState,
  initialDeliveryState,
  PLATFORM_LIMITS,
  PLATFORM_MARKDOWN,
  type PlatformName,
  stepDelivery,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

const shown = (...bubbles: string[]): DeliveryEvent => ({
  kind: "bubbles",
  bubbles,
});
const TICK: DeliveryEvent = { kind: "tick" };
const END: DeliveryEvent = { kind: "end" };

const edit = (slot: number, t: string): DeliveryOp => ({
  kind: "edit",
  slot,
  text: t,
});
const send = (slot: number, t: string): DeliveryOp => ({
  kind: "send",
  slot,
  text: t,
});
const PAUSE: DeliveryOp = { kind: "pause" };
const sealed = (bubbles: number): DeliveryOp => ({
  kind: "delivered",
  bubbles,
});

/** Runs a frame sequence and returns every operation, in order, plus the final state. */
function run(
  platform: PlatformName,
  live: boolean,
  events: DeliveryEvent[],
): { ops: DeliveryOp[]; state: DeliveryState } {
  const config = { live, platform, render: PLATFORM_MARKDOWN[platform] };
  let state = initialDeliveryState();
  const ops: DeliveryOp[] = [];
  for (const event of events) {
    const step = stepDelivery(state, event, config);
    state = step.state;
    ops.push(...step.ops);
  }
  return { ops, state };
}

interface Case {
  name: string;
  events: DeliveryEvent[];
  live: DeliveryOp[];
  rest: DeliveryOp[];
}

const CASES: Case[] = [
  {
    name: "R1 one short bubble",
    events: [shown("Done, it"), TICK, shown("Done, it is set."), TICK, END],
    live: [edit(0, "Done, it"), edit(0, "Done, it is set."), sealed(1)],
    rest: [edit(0, "Done, it is set."), sealed(1)],
  },
  {
    name: "R2 three bubbles, each its own message from its first word",
    events: [
      shown("One"),
      TICK,
      shown("One more.", "Two"),
      TICK,
      shown("One more.", "Two.", "Three."),
      TICK,
      END,
    ],
    live: [
      edit(0, "One"),
      edit(0, "One more."),
      sealed(1),
      send(1, "Two"),
      edit(1, "Two."),
      sealed(2),
      send(2, "Three."),
      sealed(3),
    ],
    rest: [
      edit(0, "One more."),
      sealed(1),
      PAUSE,
      send(1, "Two."),
      sealed(2),
      PAUSE,
      send(2, "Three."),
      sealed(3),
    ],
  },
  {
    name: "R8 a link-only bubble is a message of its own",
    events: [shown("Here.", "https://x.dev/a", "See it."), TICK, END],
    live: [
      edit(0, "Here."),
      sealed(1),
      PAUSE,
      send(1, "https://x.dev/a"),
      sealed(2),
      send(2, "See it."),
      sealed(3),
    ],
    rest: [
      edit(0, "Here."),
      sealed(1),
      PAUSE,
      send(1, "https://x.dev/a"),
      sealed(2),
      PAUSE,
      send(2, "See it."),
      sealed(3),
    ],
  },
  {
    name: "R9 a reaction-only reply sends nothing",
    events: [END],
    live: [],
    rest: [],
  },
];

describe("stepDelivery", () => {
  it.each(CASES)("$name, on a live platform", ({ events, live }) => {
    expect(run("telegram", true, events).ops).toEqual(live);
  });

  it.each(CASES)(
    "$name, on a platform that shows the reply at the end",
    ({ events, rest }) => {
      expect(run("whatsapp", false, events).ops).toEqual(rest);
    },
  );

  it.each([
    ["telegram", true],
    ["whatsapp", false],
  ] as const)(
    "R5 refuses bubbles that take back shown text, on %s",
    (platform, live) => {
      expect(() =>
        run(platform, live, [
          shown("Sure.", "Checking"),
          TICK,
          shown("All set."),
        ]),
      ).toThrow("a reply's bubbles shrank: shown text is never taken back");
    },
  );
});

/** Replays the ops into the messages they leave, failing on any shown text taken back. */
function screen(ops: DeliveryOp[]): string[] {
  const messages = new Map<number, string>();
  for (const op of ops) {
    if (op.kind === "pause" || op.kind === "delivered") continue;
    const before = messages.get(op.slot);
    if (op.kind === "edit" && before !== undefined) {
      expect(op.text.startsWith(before.trimEnd())).toBe(true);
    }
    messages.set(op.slot, op.text);
  }
  return [...messages.entries()].sort(([a], [b]) => a - b).map(([, t]) => t);
}

describe("R3 a bubble longer than the platform allows", () => {
  const sentence = "This sentence is part of a long plan and ends cleanly. ";
  const long = Array.from(
    { length: 12 },
    (_, i) => `Section ${i}. ${sentence.repeat(14)}`,
  ).join("\n\n");

  it.each<PlatformName>(["telegram", "slack"])(
    "%s splits it while it streams, without taking back any shown text",
    (platform) => {
      const words = long.split(/(?<= )/);
      // A preview every few words, as the throttle renders one about once a second.
      const events = words.flatMap((_, i) => {
        const bubbles = shown(
          "Intro bubble.",
          words
            .slice(0, i + 1)
            .join("")
            .trimEnd(),
        );
        return i % 7 === 0 ? [bubbles, TICK] : [bubbles];
      });
      const { ops } = run(platform, true, [
        shown("Intro bubble."),
        ...events,
        END,
      ]);
      const messages = screen(ops);

      expect(messages[0]).toBe("Intro bubble.");
      expect(messages.length).toBeGreaterThan(2);
      for (const message of messages) {
        expect(PLATFORM_MARKDOWN[platform](message).length).toBeLessThanOrEqual(
          PLATFORM_LIMITS[platform],
        );
      }
      expect(messages.slice(1).join(" ").split(/\s+/).filter(Boolean)).toEqual(
        long.split(/\s+/).filter(Boolean),
      );
    },
  );

  it("splits it the same way on the platforms that show it at the end", () => {
    const { ops } = run("discord", false, [shown("Intro bubble.", long), END]);
    const messages = screen(ops);
    expect(messages[0]).toBe("Intro bubble.");
    expect(ops.filter((op) => op.kind === "pause")).toHaveLength(1);
    expect(messages.slice(1).join(" ").split(/\s+/).filter(Boolean)).toEqual(
      long.split(/\s+/).filter(Boolean),
    );
  });
});

describe("a streaming code block whose first line outgrows one message", () => {
  it.each<PlatformName>(["telegram", "slack"])(
    "%s cuts it into messages instead of re-splitting the same text forever",
    (platform) => {
      const code = "x".repeat(PLATFORM_LIMITS[platform] * 2);
      // The loop is synchronous, so a test timeout could never fire: a render budget fails it.
      let renders = 0;
      const render = (text: string): string => {
        renders += 1;
        if (renders > 500)
          throw new Error("the preview stopped making progress");
        return PLATFORM_MARKDOWN[platform](text);
      };

      const config = { live: true, platform, render };
      const { state } = stepDelivery(
        initialDeliveryState(),
        shown(`\`\`\`\n${code}`),
        config,
      );
      const { ops } = stepDelivery(state, TICK, config);
      const messages = screen(ops);

      expect(messages.length).toBeGreaterThan(1);
      expect(messages.length).toBeLessThan(6);
      expect(messages.join("").replaceAll(/[`\n]/g, "")).toBe(code);
    },
  );
});
