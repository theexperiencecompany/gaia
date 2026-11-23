import { describe, expect, it } from "vitest";
import type { NotificationPlatform } from "@/features/notification/constants";
import {
  linkedInPriorityOrder,
  withChannelFirst,
} from "@/features/settings/utils/chatChannelOrder";

const order: NotificationPlatform[] = ["telegram", "whatsapp", "slack"];

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

describe("withChannelFirst", () => {
  it("moves the chosen platform to the front and keeps the rest of the linked order", () => {
    expect(
      withChannelFirst(
        ["telegram", "whatsapp", "slack"],
        ["telegram", "whatsapp", "slack"],
        "slack",
      ),
    ).toEqual(["slack", "telegram", "whatsapp"]);
  });

  it("keeps unlinked platforms at the tail so relinking restores their place", () => {
    expect(
      withChannelFirst(
        ["discord", "telegram", "whatsapp"],
        ["telegram", "whatsapp"],
        "whatsapp",
      ),
    ).toEqual(["whatsapp", "telegram", "discord"]);
  });

  it("includes a linked platform the stored order never mentioned", () => {
    expect(
      withChannelFirst(["telegram"], ["telegram", "imessage"], "telegram"),
    ).toEqual(["telegram", "imessage"]);
  });

  it("does not mutate the input", () => {
    const stored: NotificationPlatform[] = ["telegram", "whatsapp"];
    withChannelFirst(stored, stored, "whatsapp");
    expect(stored).toEqual(["telegram", "whatsapp"]);
  });
});
