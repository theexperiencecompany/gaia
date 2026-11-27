/**
 * A reaction the bot had not placed: owed by the server apart from the cursor, placed once
 * after a restart, never twice, and settled when the platform refuses it for good.
 *
 * The follower and its registry are real; the platform is a recorder and the events stream
 * a scripted source.
 */
import {
  type ConversationEventSource,
  ConversationFollower,
  ConversationFollowers,
  type DeliveryRecorder,
  type DeliveryReport,
  type FollowStart,
  type FollowSurface,
  REACTION_OUTCOME,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import {
  screenFrame,
  stateFrame,
  updateFrame,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type { Reaction } from "../../../../../libs/shared/ts/src/conversation/types";
import {
  type Call,
  cursorAt,
  feed,
  inbound,
  NON_EDITING,
  recorder,
  sent,
} from "./follower-platform";

describe("a reaction the bot had not placed", () => {
  const THUMBS: Reaction = { emoji: "👍", by: "chat_model" };
  const OWED = { message_id: "u1", emoji: "👍" };
  const reacts = (calls: Call[]) => calls.filter((call) => call.op === "react");
  /** A follow after floor owing reactions, keeping every report it makes. */
  const following = (
    floor: number,
    owedReactions: FollowStart["owedReactions"],
    surface: FollowSurface,
    placedReactions: FollowStart["placedReactions"] = [],
  ) => {
    const reports: DeliveryReport[] = [];
    const follower = new ConversationFollower(
      {
        floor,
        partialReply: null,
        owedReactions,
        placedReactions,
        record: async (report) => {
          reports.push(report);
        },
      },
      NON_EDITING,
      surface,
      "c1",
    );
    return { follower, reports };
  };

  it("is placed once after a restart between its logging and its placing, and reported placed", async () => {
    // The bot dies inside the react call: nothing after it runs.
    const before = recorder();
    const dying: FollowSurface = {
      ...before.surface,
      react: () => new Promise(() => undefined),
    };
    const first = following(0, [], dying);
    await feed(first.follower, [screenFrame([inbound("u1", 1, "11")])]);
    void first.follower.apply(updateFrame(inbound("u1", 1, "11", THUMBS)));
    const floor = first.reports.at(-1)?.delivered_seq ?? 0;

    // The server owes the reaction apart from the cursor, which already passed its message.
    const after = recorder();
    const restarted = following(floor, [OWED], after.surface);
    const screen = screenFrame([inbound("u1", 1, "11", THUMBS)]);
    await feed(restarted.follower, [screen, screen]);

    expect(floor).toBe(1);
    expect(reacts(after.calls)).toEqual([
      { op: "react", target: "11", emoji: "👍", replaces: null },
    ]);
    expect(restarted.reports.flatMap((r) => r.placed_reactions)).toEqual([
      OWED,
    ]);
    expect(restarted.follower.delivered.owed_reactions).toEqual([]);
  });

  it("is not placed again by the next follow once a follow reported it placed", async () => {
    const live = recorder();
    const first = following(0, [], live.surface);
    await feed(first.follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame(inbound("u1", 1, "11", THUMBS)),
    ]);
    const next = recorder();
    const restarted = following(
      first.reports.at(-1)?.delivered_seq ?? 0,
      [],
      next.surface,
    );
    await feed(restarted.follower, [
      screenFrame([inbound("u1", 1, "11", THUMBS)]),
    ]);

    expect(reacts(live.calls)).toHaveLength(1);
    expect(first.reports.flatMap((r) => r.placed_reactions)).toEqual([OWED]);
    expect(next.calls.filter((call) => call.op !== "typing")).toEqual([]);
  });

  it("is placed when it lands on a message at or below the floor during the follow", async () => {
    const { surface, calls } = recorder();
    const { follower, reports } = following(6, [], surface);
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")], 6),
      updateFrame(inbound("u1", 1, "11", THUMBS), 6),
    ]);

    expect(reacts(calls)).toEqual([
      { op: "react", target: "11", emoji: "👍", replaces: null },
    ]);
    expect(reports.flatMap((r) => r.placed_reactions)).toEqual([OWED]);
  });

  it("goes as text once when the platform refuses it for good, and is settled", async () => {
    const { surface, calls } = recorder();
    const refusing: FollowSurface = {
      ...surface,
      react: async () => REACTION_OUTCOME.ATTACH_FAILED,
    };
    const { follower, reports } = following(1, [OWED], refusing);
    const screen = screenFrame([inbound("u1", 1, "11", THUMBS)]);
    await feed(follower, [screen, screen]);

    expect(sent(calls)).toEqual([{ text: "👍", replyTo: null }]);
    expect(reports.flatMap((r) => r.placed_reactions)).toEqual([OWED]);
    expect(follower.delivered.owed_reactions).toEqual([]);
  });

  it("is settled without placing it again when an earlier follow here placed it", async () => {
    const { surface, calls } = recorder();
    const { follower, reports } = following(1, [OWED], surface, [OWED]);
    await feed(follower, [screenFrame([inbound("u1", 1, "11", THUMBS)])]);

    expect(reacts(calls)).toEqual([]);
    expect(reports.flatMap((r) => r.placed_reactions)).toEqual([OWED]);
  });

  it("is not placed again by a late wake whose cursor still owes it", async () => {
    const { surface, calls } = recorder();
    const reports: DeliveryReport[] = [];
    const record: DeliveryRecorder = async (_ctx, _id, report) => {
      reports.push(report);
    };
    const source: ConversationEventSource = async function* () {
      yield screenFrame([inbound("u1", 1, "11", THUMBS)]);
      yield stateFrame(1, "idle");
    };
    const followers = new ConversationFollowers(source, NON_EDITING, record);
    const ctx = { platform: NON_EDITING.platform, platformUserId: "7" };
    followers.follow(ctx, "c1", 1, cursorAt(0), surface);
    await followers.idle();
    // The wake was published when the reaction was owed: its cursor has not moved since.
    followers.resume(
      ctx,
      "c1",
      { ...cursorAt(1), owed_reactions: [OWED] },
      surface,
    );
    await followers.idle();

    expect(reacts(calls)).toHaveLength(1);
    expect(reports.flatMap((r) => r.placed_reactions)).toEqual([OWED, OWED]);
  });

  it("settles the emoji it replaced along with the one the message shows", async () => {
    const { surface, calls } = recorder();
    const { follower, reports } = following(
      1,
      [{ message_id: "u1", emoji: "👀" }, OWED],
      surface,
    );
    await feed(follower, [screenFrame([inbound("u1", 1, "11", THUMBS)])]);

    expect(reacts(calls)).toHaveLength(1);
    expect(reports.flatMap((r) => r.placed_reactions)).toEqual([
      { message_id: "u1", emoji: "👀" },
      OWED,
    ]);
  });
});
