/**
 * The Telegram card widget: which cards it draws, what its buttons send back,
 * and the 1024-byte answer and chat state a tap round trip writes. Built from
 * the real approval builder where a card needs invoke buttons.
 */
import {
  type Card,
  encodeCardActionData,
  encodeCardReplyData,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import { toolCardsFor } from "../../../../libs/shared/ts/src/bots/cards/registry";
import {
  renderCardWidget,
  widgetAnswer,
  widgetState,
} from "../../telegram/src/widgets/card-widget";

/** `openLink`'s limit on a URL's length, from the Bot API widget reference. */
const LINK_MAX_CHARS = 256;
const ANSWER_MAX_BYTES = 1024;
const HTTPS_ORIGIN = "https://gaia.test/";

function makeCard(overrides: Partial<Card> = {}): Card {
  return { title: "PostHog", blocks: [], actions: [], ...overrides };
}

function linkOfLength(length: number): string {
  return HTTPS_ORIGIN + "a".repeat(length - HTTPS_ORIGIN.length);
}

function linkCard(url: string): Card {
  return makeCard({ actions: [{ kind: "link", label: "Open", url }] });
}

function pendingApprovalCard(): Card {
  const [posted] = toolCardsFor({
    tool_name: "approval_request",
    data: {
      approval_id: "a1",
      tool_call_id: "t1",
      gated_tool_name: "gmail_send",
      integration_name: "Gmail",
      summary: "Send the deck to Vee",
      args_preview: {},
      status: "pending",
      feedback: null,
      timeout_seconds: 3600,
      bot_actions: { approve: "act-approve", deny: "act-deny" },
    },
  });
  if (!posted) throw new Error("approval built no card");
  return posted.card;
}

/** Text zlib cannot shrink, so the widget's compressed budget is what it hits. */
function incompressibleText(length: number): string {
  let seed = 1;
  let text = "";
  while (text.length < length) {
    seed = (seed * 48271) % 2147483647;
    text += seed.toString(36);
  }
  return text.slice(0, length);
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

describe("renderCardWidget — what the widget draws", () => {
  it("leaves a card with an image to the rich message", () => {
    const card = makeCard({
      blocks: [{ kind: "image", url: `${HTTPS_ORIGIN}chart.png`, alt: "x" }],
    });
    expect(renderCardWidget(card)).toBeNull();
  });

  it("leaves a card with code to the rich message", () => {
    const card = makeCard({
      blocks: [{ kind: "code", code: "print(1)", language: "python" }],
    });
    expect(renderCardWidget(card)).toBeNull();
  });

  it("leaves a card with a non-https link to the rich message", () => {
    expect(renderCardWidget(linkCard("http://localhost:3000"))).toBeNull();
  });

  it("leaves a card with a link longer than openLink takes to the rich message", () => {
    expect(
      renderCardWidget(linkCard(linkOfLength(LINK_MAX_CHARS + 1))),
    ).toBeNull();
  });

  it("draws a link of exactly openLink's limit", () => {
    const url = linkOfLength(LINK_MAX_CHARS);
    expect(renderCardWidget(linkCard(url))?.html).toContain(`data-u="${url}"`);
  });

  it("leaves a card past the compressed size budget to the rich message", () => {
    const card = makeCard({
      blocks: [{ kind: "text", markdown: incompressibleText(12000) }],
    });
    expect(renderCardWidget(card)).toBeNull();
  });

  it("draws a plain card with its footer as the caption", () => {
    const widget = renderCardWidget(
      makeCard({
        blocks: [{ kind: "text", markdown: "Your connection expired." }],
        footer: "Link works for 60 minutes",
      }),
    );
    expect(widget?.html).toContain("<h1>PostHog</h1>");
    expect(widget?.html).toContain("Your connection expired.");
    expect(widget?.html).toContain("<script>");
    expect(widget?.caption).toBe("Link works for 60 minutes");
  });

  it("sends no caption for a card without a footer", () => {
    const widget = renderCardWidget(makeCard());
    expect(widget).not.toBeNull();
    expect(widget).not.toHaveProperty("caption");
  });

  it("escapes the card's text so it cannot inject markup", () => {
    const html =
      renderCardWidget(makeCard({ title: "<img src=x onerror=alert(1)>" }))
        ?.html ?? "";
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });
});

describe("renderCardWidget — buttons", () => {
  it("gives each invoke button its encoded action id to send back", () => {
    const html = renderCardWidget(pendingApprovalCard())?.html ?? "";
    expect(html).toContain(
      `data-q="${encodeCardActionData("act-approve")}" onclick="q(this)">Approve</button>`,
    );
    expect(html).toContain(
      `data-q="${encodeCardActionData("act-deny")}" onclick="q(this)">Deny</button>`,
    );
  });

  it("gives the reply button its encoded prompt", () => {
    const html = renderCardWidget(pendingApprovalCard())?.html ?? "";
    expect(html).toContain(
      `data-q="${encodeCardReplyData("revise_approval")}"`,
    );
  });
});

describe("widgetAnswer", () => {
  const settled = makeCard({ status: { label: "Approved", tone: "success" } });

  it("cuts a huge message to fit the answer's byte limit", () => {
    const message = "Désolé — ".repeat(400);
    const answer = widgetAnswer(message, settled);
    expect(byteLength(answer)).toBeLessThanOrEqual(ANSWER_MAX_BYTES);
    const parsed = JSON.parse(answer) as { m: string };
    expect(parsed.m.length).toBeGreaterThan(0);
    expect(message.startsWith(parsed.m)).toBe(true);
  });

  it("carries a short message whole", () => {
    expect(JSON.parse(widgetAnswer("Sent.", null))).toEqual({ m: "Sent." });
  });

  it("includes the settled badge when the settled card has a status", () => {
    expect(JSON.parse(widgetAnswer("Approved.", settled))).toEqual({
      m: "Approved.",
      s: { l: "Approved", t: "success" },
    });
  });
});

describe("widgetState", () => {
  it("is undefined for no card or a card without a status", () => {
    expect(widgetState(null)).toBeUndefined();
    expect(widgetState(makeCard())).toBeUndefined();
  });

  it("is the settled badge as compact chat state", () => {
    const card = makeCard({
      status: { label: "Not approved", tone: "danger" },
    });
    expect(JSON.parse(widgetState(card) ?? "")).toEqual({
      s: { l: "Not approved", t: "danger" },
    });
  });
});
