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

const BREAK = "<NEW_MESSAGE_BREAK>";
const text = (chunk: string): DeliveryEvent => ({ kind: "text", chunk });
const TICK: DeliveryEvent = { kind: "tick" };
const KEPT: DeliveryEvent = { kind: "boundary", discarded: false };
const DISCARDED: DeliveryEvent = { kind: "boundary", discarded: true };
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
const del = (slot: number): DeliveryOp => ({ kind: "delete", slot });
const PAUSE: DeliveryOp = { kind: "pause" };

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
    events: [text("Done, it"), TICK, text(" is set."), TICK, KEPT, END],
    live: [edit(0, "Done, it"), edit(0, "Done, it is set.")],
    rest: [edit(0, "Done, it is set.")],
  },
  {
    name: "R2 three bubbles, each its own message from its first word",
    events: [
      text("One"),
      TICK,
      text(` more.${BREAK}Two`),
      TICK,
      text(`.${BREAK}Three.`),
      TICK,
      KEPT,
      END,
    ],
    live: [
      edit(0, "One"),
      edit(0, "One more."),
      send(1, "Two"),
      edit(1, "Two."),
      send(2, "Three."),
    ],
    rest: [
      edit(0, "One more."),
      PAUSE,
      send(1, "Two."),
      PAUSE,
      send(2, "Three."),
    ],
  },
  {
    name: "R4 a break split across two chunks",
    events: [text("One.<NEW_MES"), TICK, text("SAGE_BREAK>Two."), TICK, KEPT],
    live: [edit(0, "One."), send(1, "Two.")],
    rest: [edit(0, "One."), PAUSE, send(1, "Two.")],
  },
  {
    name: "R5 a retracted preamble is replaced in place, its later bubbles deleted",
    events: [
      text(`Sure.${BREAK}Checking`),
      TICK,
      DISCARDED,
      text("All set."),
      TICK,
      KEPT,
      END,
    ],
    live: [edit(0, "Sure."), send(1, "Checking"), del(1), edit(0, "All set.")],
    rest: [edit(0, "All set.")],
  },
  {
    name: "R6 leading, trailing and doubled breaks send no empty bubble",
    events: [text(`${BREAK}One.${BREAK}${BREAK}Two.${BREAK}`), TICK, KEPT, END],
    live: [edit(0, "One."), PAUSE, send(1, "Two.")],
    rest: [edit(0, "One."), PAUSE, send(1, "Two.")],
  },
  {
    name: "R7 a break inside a code block does not split it",
    events: [
      text("Run:\n```\na()\n"),
      TICK,
      text(`${BREAK}b()\n\`\`\`${BREAK}Done.`),
      TICK,
      KEPT,
    ],
    live: [
      edit(0, "Run:\n```\na()"),
      edit(0, "Run:\n```\na()\n\nb()\n```"),
      send(1, "Done."),
    ],
    rest: [edit(0, "Run:\n```\na()\n\nb()\n```"), PAUSE, send(1, "Done.")],
  },
  {
    name: "R8 a link-only bubble is a message of its own",
    events: [text(`Here.${BREAK}https://x.dev/a${BREAK}See it.`), TICK, KEPT],
    live: [
      edit(0, "Here."),
      PAUSE,
      send(1, "https://x.dev/a"),
      send(2, "See it."),
    ],
    rest: [
      edit(0, "Here."),
      PAUSE,
      send(1, "https://x.dev/a"),
      PAUSE,
      send(2, "See it."),
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
});

/** Replays the ops into the messages they leave, failing on any shown text taken back. */
function screen(ops: DeliveryOp[]): string[] {
  const messages = new Map<number, string>();
  for (const op of ops) {
    if (op.kind === "pause") continue;
    if (op.kind === "delete") {
      messages.delete(op.slot);
      continue;
    }
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
      const words = `Intro bubble.${BREAK}${long}`.split(/(?<= )/);
      // A preview every few words, as the throttle renders one about once a second.
      const events = words.flatMap((w, i) =>
        i % 7 === 0 ? [text(w), TICK] : [text(w)],
      );
      const { ops } = run(platform, true, [...events, KEPT, END]);
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
    const { ops } = run("discord", false, [
      text(`Intro bubble.${BREAK}${long}`),
      KEPT,
    ]);
    const messages = screen(ops);
    expect(messages[0]).toBe("Intro bubble.");
    expect(ops.filter((op) => op.kind === "pause")).toHaveLength(1);
    expect(messages.slice(1).join(" ").split(/\s+/).filter(Boolean)).toEqual(
      long.split(/\s+/).filter(Boolean),
    );
  });
});
