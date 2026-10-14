import { describe, expect, it } from "vitest";
import {
  getPlatformScript,
  PLATFORM_PREVIEW_ORDER,
  PROFESSION_SCRIPT_KEYS,
} from "@/features/onboarding/constants/platformPreviewMessages";

/**
 * The scripts are written as compact tuples and expanded by one builder, so
 * these pin the shape that expansion has to produce: the bubble fields the
 * chat demo reads, the delivery receipt only on the user's own lines, and the
 * telegram-only subtitle.
 */
describe("getPlatformScript", () => {
  it("expands a script's tuples into chat bubbles", () => {
    expect(getPlatformScript("founder", "telegram")).toEqual({
      title: "GAIA",
      subtitle: "bot",
      messages: [
        {
          from: "them",
          text: "morning! inbox is sorted, 3 investor replies drafted and waiting for your ok.",
          time: "8:12",
        },
        {
          from: "them",
          text: "also the board deck is due friday. i pulled last month's numbers into the template already.",
          time: "8:12",
        },
        {
          from: "me",
          text: "anything from the seed lead?",
          time: "8:14",
          status: "read",
        },
        {
          from: "them",
          text: "yep, she asked for the updated runway. i attached it to the draft, just hit send.",
          time: "8:14",
        },
      ],
    });
  });

  it("substitutes the first name into GAIA's lines only", () => {
    const { messages } = getPlatformScript("executive", "telegram", {
      firstName: "Ada",
    });
    expect(messages[0].text).toBe(
      "morning Ada! 3 reports landed overnight, i read them so you don't have to. one decision needs you.",
    );
    expect(messages[2].text).toBe("go with option B, tell them");
  });

  it("falls back to the other script for an unknown profession", () => {
    expect(getPlatformScript("astronaut", "whatsapp")).toEqual(
      getPlatformScript("other", "whatsapp"),
    );
    expect(getPlatformScript(undefined, "whatsapp")).toEqual(
      getPlatformScript("other", "whatsapp"),
    );
  });

  it("gives every profession a four-bubble script on every platform", () => {
    for (const profession of PROFESSION_SCRIPT_KEYS) {
      for (const platform of PLATFORM_PREVIEW_ORDER) {
        const { title, messages } = getPlatformScript(profession, platform);
        expect(title).toBe("GAIA");
        expect(messages).toHaveLength(4);
        for (const message of messages) {
          expect(message.time).toMatch(/^\d{1,2}:\d{2}$/);
          expect(message.text).toBeTruthy();
          expect(message.status).toBe(
            message.from === "me" ? "read" : undefined,
          );
        }
      }
    }
  });
});
