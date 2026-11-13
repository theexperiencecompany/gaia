/**
 * Tool-card builders: the `tool_data` payloads the web renders, turned into the
 * cards bots send. Built from the shared gallery fixtures where one exists, so a
 * payload change breaks the web gallery and these together.
 */
import {
  getFixture,
  type IntegrationConnectionData,
  type RateLimitData,
} from "@gaia/shared";
import { type Card, renderCardText } from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import {
  type CardSourceEntry,
  cardAfterTap,
  toolCardsFor,
} from "../../../../../libs/shared/ts/src/bots/cards/registry";

/** The one card an entry posts; fails the test when it posts none or several. */
function postedCard(entry: CardSourceEntry): Card {
  const cards = toolCardsFor(entry);
  expect(cards).toHaveLength(1);
  return cards[0].card;
}

const connectFixture = getFixture("integration_connection_required")
  ?.data as IntegrationConnectionData;

function connectCard(overrides: Partial<IntegrationConnectionData> = {}) {
  return postedCard({
    tool_name: "integration_connection_required",
    data: { ...connectFixture, ...overrides },
  });
}

describe("integration_connection_required card", () => {
  it("offers a one-tap connect button with the link's lifetime", () => {
    const card = connectCard();
    expect(card.title).toBe("Connect Google Calendar");
    expect(card.actions).toEqual([
      {
        kind: "link",
        label: "Connect Google Calendar",
        url: "https://heygaia.io/connect/7f3c9a",
      },
    ]);
    expect(card.footer).toBe("Link works for 60 minutes");
  });

  it("says Reconnect when the connection expired", () => {
    expect(connectCard({ expired: true }).actions[0]?.label).toBe(
      "Reconnect Google Calendar",
    );
  });

  it("points to the integrations page when no login-free link exists", () => {
    const card = connectCard({
      connect_url: "https://heygaia.io/integrations",
      connect_url_valid_minutes: null,
    });
    expect(card.actions).toEqual([
      {
        kind: "link",
        label: "Open integrations",
        url: "https://heygaia.io/integrations",
      },
    ]);
    expect(card.footer).toBeUndefined();
  });

  it("carries no button when the payload has no link (a UI-run card)", () => {
    const card = connectCard({
      connect_url: null,
      connect_url_valid_minutes: null,
    });
    expect(card.actions).toEqual([]);
    expect(renderCardText(card)).toContain(connectFixture.message);
  });
});

describe("rate_limit_data card", () => {
  const rateLimit = getFixture("rate_limit_data")?.data as RateLimitData;

  it("names the feature and links the upgrade when one applies", () => {
    const card = postedCard({
      tool_name: "rate_limit_data",
      data: { ...rateLimit, upgrade_url: "https://heygaia.io/checkout/x" },
    });
    expect(renderCardText(card)).toContain(
      "You've reached your Deep research limit.",
    );
    expect(card.actions).toEqual([
      {
        kind: "link",
        label: "Upgrade to Pro",
        url: "https://heygaia.io/checkout/x",
      },
    ]);
  });

  it("prefers the backend's message and offers no upgrade to a Pro user", () => {
    const card = postedCard({
      tool_name: "rate_limit_data",
      data: {
        feature: "memory_storage",
        message: "You've hit the memory cap.",
        upgrade_url: null,
      },
    });
    expect(renderCardText(card)).toBe(
      "**Limit reached**\n\nYou've hit the memory cap.",
    );
    expect(card.actions).toEqual([]);
  });
});

describe("approval_request card", () => {
  const approval = (status: string, extra: object = {}) => ({
    tool_name: "approval_request",
    data: {
      approval_id: "a1",
      tool_call_id: "t1",
      gated_tool_name: "gmail_send",
      integration_name: "Gmail",
      summary: "Send the deck to Vee",
      args_preview: {},
      status,
      feedback: null,
      timeout_seconds: 6 * 60 * 60,
      ...extra,
    },
  });

  it("asks a pending approval with a reply hint and its expiry", () => {
    const text = renderCardText(postedCard(approval("pending")));
    expect(text).toContain("**Send the deck to Vee**");
    expect(text).toContain(
      "Reply **yes** to approve, **no** to decline, or tell me what to change.",
    );
    expect(text).toContain("expires in 6 hours");
  });

  it("shows how long ago the approval was asked", () => {
    const card = postedCard(
      approval("pending", { age_seconds: 2 * 24 * 60 * 60 }),
    );
    expect(card.footer).toContain("asked 2d ago");
  });

  it("posts nothing for a settled approval", () => {
    expect(toolCardsFor(approval("approved"))).toEqual([]);
  });

  it("turns a tapped approval into its receipt", () => {
    const receipt = cardAfterTap(approval("approved"), "any");
    expect(receipt?.title).toBe("Approved");
    expect(receipt?.status).toEqual({ label: "Approved", tone: "success" });
    expect(receipt?.actions).toEqual([]);
  });
});

it("posts nothing for a tool bots don't show", () => {
  expect(
    toolCardsFor({ tool_name: "memory_data", data: { memories: [] } }),
  ).toEqual([]);
});
