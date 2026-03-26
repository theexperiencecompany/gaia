/**
 * Tests for Discord-specific rich embed rendering.
 *
 * `richMessageToEmbed` converts a platform-agnostic `RichMessage` into a
 * Discord.js `EmbedBuilder`. These tests exercise every field that the
 * function maps, including color, timestamp, thumbnailUrl, authorIconUrl,
 * and the rendering of links as an embed field.
 *
 * `richMessageToMarkdown` (Slack/Telegram) is tested separately in
 * `apps/bots/__tests__/shared/adapter/rich-renderer.test.ts`.
 */

import type { RichMessage } from "@gaia/shared";
import { describe, expect, it } from "vitest";
import { richMessageToEmbed } from "../../discord/src/adapter";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function makeMsg(overrides: Partial<RichMessage> = {}): RichMessage {
  return {
    type: "embed",
    title: "Test Title",
    fields: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// richMessageToEmbed
// ---------------------------------------------------------------------------

describe("richMessageToEmbed", () => {
  it("renders title and description", () => {
    const msg = makeMsg({ description: "Some description text" });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.title).toBe("Test Title");
    expect(data.description).toBe("Some description text");
  });

  it("maps color integer to embed color", () => {
    // RichMessage.color is already a 24-bit integer (e.g. 0xff0000 = 16711680)
    const msg = makeMsg({ color: 0xff0000 });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.color).toBe(0xff0000);
  });

  it("sets timestamp when provided", () => {
    const msg = makeMsg({ timestamp: true });
    const data = richMessageToEmbed(msg).toJSON();

    // EmbedBuilder.setTimestamp() stores an ISO string
    expect(data.timestamp).toBeDefined();
    expect(() => new Date(data.timestamp as string)).not.toThrow();
  });

  it("omits timestamp when not provided", () => {
    const msg = makeMsg({ timestamp: false });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.timestamp).toBeUndefined();
  });

  it("sets thumbnailUrl when provided", () => {
    const msg = makeMsg({ thumbnailUrl: "https://example.com/thumb.png" });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.thumbnail?.url).toBe("https://example.com/thumb.png");
  });

  it("omits thumbnail when thumbnailUrl is absent", () => {
    const msg = makeMsg();
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.thumbnail).toBeUndefined();
  });

  it("sets authorIconUrl when authorName and authorIconUrl are provided", () => {
    const msg = makeMsg({
      authorName: "GAIA Bot",
      authorIconUrl: "https://example.com/icon.png",
    });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.author?.name).toBe("GAIA Bot");
    expect(data.author?.icon_url).toBe("https://example.com/icon.png");
  });

  it("sets author without icon when only authorName is provided", () => {
    const msg = makeMsg({ authorName: "GAIA Bot" });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.author?.name).toBe("GAIA Bot");
    expect(data.author?.icon_url).toBeUndefined();
  });

  it("omits author when authorName is absent", () => {
    const msg = makeMsg();
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.author).toBeUndefined();
  });

  it("renders links as an embed field", () => {
    const msg = makeMsg({
      links: [{ label: "Click here", url: "https://example.com" }],
    });
    const data = richMessageToEmbed(msg).toJSON();

    const linkField = data.fields?.find((f) => f.name.includes("Useful Links"));
    expect(linkField).toBeDefined();
    expect(linkField?.value).toContain("[Click here](https://example.com)");
  });

  it("renders multiple links joined with pipe separator in a single field", () => {
    const msg = makeMsg({
      links: [
        { label: "Docs", url: "https://docs.example.com" },
        { label: "App", url: "https://app.example.com" },
      ],
    });
    const data = richMessageToEmbed(msg).toJSON();

    const linkField = data.fields?.find((f) => f.name.includes("Useful Links"));
    expect(linkField).toBeDefined();
    expect(linkField?.value).toContain("[Docs](https://docs.example.com)");
    expect(linkField?.value).toContain("[App](https://app.example.com)");
    expect(linkField?.value).toContain(" | ");
  });

  it("omits links field when links array is empty", () => {
    const msg = makeMsg({ links: [] });
    const data = richMessageToEmbed(msg).toJSON();

    const linkField = data.fields?.find((f) => f.name.includes("Useful Links"));
    expect(linkField).toBeUndefined();
  });

  it("renders structured fields with name, value, and inline flag", () => {
    const msg = makeMsg({
      fields: [
        { name: "Status", value: "Active", inline: true },
        { name: "Region", value: "US-East", inline: false },
      ],
    });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.fields).toHaveLength(2);
    expect(data.fields?.[0]).toMatchObject({
      name: "Status",
      value: "Active",
      inline: true,
    });
    expect(data.fields?.[1]).toMatchObject({
      name: "Region",
      value: "US-East",
      inline: false,
    });
  });

  it("defaults inline to false when not specified on a field", () => {
    const msg = makeMsg({
      fields: [{ name: "Key", value: "Value" }],
    });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.fields?.[0].inline).toBe(false);
  });

  it("sets footer text when provided", () => {
    const msg = makeMsg({ footer: "Powered by GAIA" });
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.footer?.text).toBe("Powered by GAIA");
  });

  it("omits optional fields on a minimal RichMessage", () => {
    const msg = makeMsg();
    const data = richMessageToEmbed(msg).toJSON();

    expect(data.description).toBeUndefined();
    expect(data.color).toBeUndefined();
    expect(data.timestamp).toBeUndefined();
    expect(data.thumbnail).toBeUndefined();
    expect(data.author).toBeUndefined();
    expect(data.footer).toBeUndefined();
    expect(data.fields ?? []).toHaveLength(0);
  });
});
