/**
 * One-tap onboarding link codes.
 *
 * These pin the two things that break silently in production: the trailing
 * `#<code>` regex (too loose and it eats a real hashtag; too tight and linking
 * never fires) and the unlinked-vs-linked branching that decides whether a
 * redemption is attempted at all.
 */

import type { GaiaClient, MessageTarget } from "@gaia/shared/bots";
import {
  buildLinkCodeFailureMessage,
  consumeInboundLinkCode,
  GaiaApiError,
  LINK_CODE_LENGTH,
  parseTrailingLinkCode,
  redeemLinkCode,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";

/** A real-shaped code: 22 urlsafe-base64 characters. */
const CODE = "Ab3-_xY9zQ1234567890wE";
const FIRST_MESSAGE =
  "Hi! I'm a founder. I could use help with my inbox. Who are you?";
const FRONTEND_URL = "https://gaia.test";
/** The API delivered GAIA's first contact itself, so the bot owes nothing. */
const okRedeem = () =>
  vi.fn(async () => ({ linked: true, delivered: true, firstContact: [] }));
/** The bubbles the API hands back when the outbound publish did not take them. */
const FIRST_CONTACT = [
  "Hey Aryan, I'm with you on Telegram now.",
  "From here, every morning your inbox comes sorted with replies drafted.",
  "That starts with your inbox, which I can't see yet.",
];

function fakeTarget(): MessageTarget & { sent: string[] } {
  const sent: string[] = [];
  return {
    sent,
    platform: "whatsapp",
    send: vi.fn(async (text: string) => {
      sent.push(text);
      return { id: "1", edit: async () => undefined };
    }),
    sendEphemeral: vi.fn(async (text: string) => {
      sent.push(text);
      return { id: "1", edit: async () => undefined };
    }),
    startTyping: vi.fn(async () => () => undefined),
  } as unknown as MessageTarget & { sent: string[] };
}

function fakeGaia(redeem: unknown): GaiaClient {
  return {
    redeemLinkCode: redeem,
    getFrontendUrl: () => FRONTEND_URL,
  } as unknown as GaiaClient;
}

describe("parseTrailingLinkCode", () => {
  it("splits the code off the end and trims the separator", () => {
    expect(parseTrailingLinkCode(`${FIRST_MESSAGE} #${CODE}`)).toEqual({
      code: CODE,
      text: FIRST_MESSAGE,
    });
  });

  it("tolerates trailing whitespace after the code", () => {
    expect(parseTrailingLinkCode(`hello #${CODE}  `)).toEqual({
      code: CODE,
      text: "hello",
    });
  });

  it("matches a message that is only a code", () => {
    expect(parseTrailingLinkCode(`#${CODE}`)).toEqual({ code: CODE, text: "" });
  });

  it("does not match a real hashtag", () => {
    expect(parseTrailingLinkCode("shipping today #launch")).toBeNull();
    expect(parseTrailingLinkCode("#todo remind me to call mum")).toBeNull();
  });

  it("does not match a token of the wrong length", () => {
    expect(parseTrailingLinkCode(`hi #${CODE.slice(0, -1)}`)).toBeNull();
    expect(parseTrailingLinkCode(`hi #${CODE}x`)).toBeNull();
  });

  it("does not match a token outside the code alphabet", () => {
    expect(
      parseTrailingLinkCode(`hi #${"a".repeat(LINK_CODE_LENGTH - 1)}!`),
    ).toBeNull();
  });

  it("only matches at the end of the message", () => {
    expect(parseTrailingLinkCode(`#${CODE} and then some`)).toBeNull();
  });

  it("returns null when there is no code at all", () => {
    expect(parseTrailingLinkCode(FIRST_MESSAGE)).toBeNull();
  });
});

describe("redeemLinkCode", () => {
  it("reports success and sends nothing itself: the API delivers the first contact", async () => {
    const redeem = okRedeem();
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "telegram",
      "TG42",
      CODE,
      target,
      { username: "tg_user" },
    );

    expect(result).toBe(true);
    expect(redeem).toHaveBeenCalledWith(
      "telegram",
      "TG42",
      CODE,
      { username: "tg_user" },
      undefined,
    );
    expect(target.sent).toEqual([]);
  });

  it("sends the first contact itself when the queue did not take it", async () => {
    // Nothing retries the API's outbound publish, so a bot that ignores this
    // leaves the user on a freshly linked platform that never said a word.
    const redeem = vi.fn(async () => ({
      linked: true,
      delivered: false,
      firstContact: FIRST_CONTACT,
    }));
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "telegram",
      "TG42",
      CODE,
      target,
    );

    expect(result).toBe(true);
    expect(target.sent).toEqual(FIRST_CONTACT);
  });

  it("explains an expired code instead of throwing", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 400", 400);
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("expired", FRONTEND_URL),
    ]);
    expect(target.sent[0]).toContain("expired");
  });

  it("explains an account already linked elsewhere", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 409", 409);
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("conflict", FRONTEND_URL),
    ]);
    expect(target.sent[0]).toContain("already connected to someone else");
  });

  it("points a free user at pricing instead of throwing on a paid platform", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 429", 429, { plan_required: "pro" });
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("plan", FRONTEND_URL),
    ]);
    expect(target.sent[0]).toContain(`${FRONTEND_URL}/pricing`);
  });

  it("does not pitch Pro at a plain rate limit", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 429", 429);
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent[0]).not.toContain(`${FRONTEND_URL}/pricing`);
  });

  it("tells a user holding a different handle to fix their own account", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 409", 409, {
        code: "account_has_other_platform_account",
      });
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("account-has-other", FRONTEND_URL),
    ]);
    expect(target.sent[0]).not.toContain("someone else");
  });

  it("answers an API blip instead of leaving the user in silence", async () => {
    // This is the user's first-ever message to GAIA. The adapters only log a
    // thrown error, so propagating one answered a 500 with nothing at all.
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 500", 500);
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("failed", FRONTEND_URL),
    ]);
    expect(target.sent[0]).not.toContain("expired");
  });

  it("answers a failure that is not an API error at all", async () => {
    const redeem = vi.fn(async () => {
      throw new Error("socket hang up");
    });
    const target = fakeTarget();

    const result = await redeemLinkCode(
      fakeGaia(redeem),
      "whatsapp",
      "WA1",
      CODE,
      target,
    );

    expect(result).toBe(false);
    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("failed", FRONTEND_URL),
    ]);
  });
});

describe("consumeInboundLinkCode", () => {
  const base = (overrides: Record<string, unknown>) => ({
    platform: "whatsapp" as const,
    platformUserId: "WA1",
    target: fakeTarget(),
    ...overrides,
  });

  it("passes a codeless message straight through and never calls the API", async () => {
    const redeem = vi.fn();
    const linkState = vi.fn(async () => "unlinked" as const);

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: "what's on my calendar?",
        linkState,
      }),
    );

    expect(result).toBe("what's on my calendar?");
    expect(redeem).not.toHaveBeenCalled();
    expect(linkState).not.toHaveBeenCalled();
  });

  it("redeems for an unlinked sender and leaves no turn to run", async () => {
    // The bundle IS the reply. Returning the stripped text here would answer the
    // user's own prewritten opener a second time, underneath a reply that
    // already covers everything they picked.
    const redeem = okRedeem();
    const target = fakeTarget();

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `${FIRST_MESSAGE} #${CODE}`,
        linkState: async () => "unlinked" as const,
        target,
      }),
    );

    expect(result).toBeNull();
    expect(redeem).toHaveBeenCalledOnce();
    expect(target.sent).toEqual([]);
  });

  it("carries the text the user actually typed into the redemption", async () => {
    // The wa.me prefill is editable, so this is their real first question. It
    // is stored as their opening turn; without it the canned line was stored
    // as theirs and the question was dropped.
    const redeem = okRedeem();
    const edited = "actually, can you sort my inbox before monday?";

    await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `${edited} #${CODE}`,
        linkState: async () => "unlinked" as const,
      }),
    );

    expect(redeem).toHaveBeenCalledWith(
      "whatsapp",
      "WA1",
      CODE,
      undefined,
      edited,
    );
  });

  it("sends no first message when the code arrived on its own", async () => {
    const redeem = okRedeem();

    await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `#${CODE}`,
        linkState: async () => "unlinked" as const,
      }),
    );

    expect(redeem).toHaveBeenCalledWith("whatsapp", "WA1", CODE, undefined, "");
  });

  it("does not greet when the inbound redemption fails", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 409", 409);
    });
    const target = fakeTarget();

    await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `${FIRST_MESSAGE} #${CODE}`,
        linkState: async () => "unlinked" as const,
        target,
      }),
    );

    expect(target.sent).toEqual([
      buildLinkCodeFailureMessage("conflict", FRONTEND_URL),
    ]);
  });

  it("redeems even when the user edited the prewritten text, and sends nothing itself", async () => {
    const target = fakeTarget();

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(okRedeem()),
        text: `hi #${CODE}`,
        linkState: async () => "unlinked" as const,
        target,
      }),
    );

    expect(result).toBeNull();
    expect(target.sent).toEqual([]);
  });

  it("answers the message instead of redeeming when the link check failed", async () => {
    const redeem = vi.fn();
    const target = fakeTarget();

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `remind me tomorrow #${CODE}`,
        linkState: async () => "unknown" as const,
        target,
      }),
    );

    // A failed check used to read as "unlinked", which spent a stale code and
    // answered a real message with "that link has expired".
    expect(result).toBe("remind me tomorrow");
    expect(redeem).not.toHaveBeenCalled();
    expect(target.sent).toEqual([]);
  });

  it("strips a stray code from a linked sender without redeeming or replying", async () => {
    const redeem = vi.fn();
    const target = fakeTarget();

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `remind me tomorrow #${CODE}`,
        linkState: async () => "linked" as const,
        target,
      }),
    );

    expect(result).toBe("remind me tomorrow");
    expect(redeem).not.toHaveBeenCalled();
    expect(target.sent).toEqual([]);
  });

  it("stops the turn when redemption fails", async () => {
    const redeem = vi.fn(async () => {
      throw new GaiaApiError("API error: 400", 400);
    });

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `${FIRST_MESSAGE} #${CODE}`,
        linkState: async () => "unlinked" as const,
      }),
    );

    expect(result).toBeNull();
  });

  it("redeems a message that was nothing but a code, and sends nothing itself", async () => {
    const redeem = okRedeem();
    const target = fakeTarget();

    const result = await consumeInboundLinkCode(
      base({
        gaia: fakeGaia(redeem),
        text: `#${CODE}`,
        linkState: async () => "unlinked" as const,
        target,
      }),
    );

    expect(result).toBeNull();
    expect(redeem).toHaveBeenCalledOnce();
    expect(target.sent).toEqual([]);
  });
});
