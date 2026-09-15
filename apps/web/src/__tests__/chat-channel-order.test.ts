import { describe, expect, it } from "vitest";
import type { NotificationPlatform } from "@/features/notification/constants";
import {
  linkedInPriorityOrder,
  moveChannel,
} from "@/features/settings/utils/chatChannelOrder";

const order: NotificationPlatform[] = ["telegram", "whatsapp", "slack"];

describe("moveChannel", () => {
  it("swaps a platform with the one above it", () => {
    expect(moveChannel(order, 1, "up")).toEqual([
      "whatsapp",
      "telegram",
      "slack",
    ]);
  });

  it("swaps a platform with the one below it", () => {
    expect(moveChannel(order, 1, "down")).toEqual([
      "telegram",
      "slack",
      "whatsapp",
    ]);
  });

  it("returns the same reference when the move falls off either end", () => {
    expect(moveChannel(order, 0, "up")).toBe(order);
    expect(moveChannel(order, 2, "down")).toBe(order);
  });

  it("does not mutate the input", () => {
    moveChannel(order, 1, "up");
    expect(order).toEqual(["telegram", "whatsapp", "slack"]);
  });
});

describe("linkedInPriorityOrder", () => {
  it("keeps the stored order and drops the unlinked platforms", () => {
    expect(linkedInPriorityOrder(order, ["slack", "telegram"])).toEqual([
      "telegram",
      "slack",
    ]);
  });

  it("appends a linked platform the stored order never mentioned", () => {
    expect(linkedInPriorityOrder(["slack"], ["slack", "discord"])).toEqual([
      "slack",
      "discord",
    ]);
  });
});
