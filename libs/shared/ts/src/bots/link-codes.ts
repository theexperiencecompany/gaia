/**
 * One-tap onboarding link codes.
 *
 * The web mints a code at the platform-pick step and the user carries it to the
 * bot — invisibly as a Telegram `?start=<code>` payload, visibly as a trailing
 * ` #<code>` on the WhatsApp/iMessage message they send. Redeeming it links the
 * account AND sends GAIA's whole first contact, so nobody has to type `/auth`
 * and no model turn stands between linking and the first real message.
 *
 * Parsing and redemption live here, not per adapter: three platforms accepting
 * three slightly different code shapes is how one of them silently stops
 * matching.
 */

import type { GaiaClient } from "./api";
import { GaiaApiError } from "./api";
import type {
  InboundLinkCodeArgs,
  LinkCodeFailure,
  ParsedLinkCode,
} from "./link-codes.types";
import type { MessageTarget, PlatformName } from "./types";
import { hashLogIdentifier } from "./utils/logger";
import { wideLog, withWideEvent } from "./utils/wide-events";

/**
 * Exact code width. `secrets.token_urlsafe(PLATFORM_LINK_CODE_BYTES)` with 16
 * bytes is always 22 urlsafe-base64 characters — see
 * `PLATFORM_LINK_CODE_BYTES` in `apps/api/app/constants/auth.py`, which must
 * change in the same commit as this.
 */
export const LINK_CODE_LENGTH = 22;

/**
 * Mirrors `LINK_CONFLICT_ACCOUNT_HAS_OTHER` in
 * `apps/api/app/constants/platform_links.py`, which must change with this.
 */
const LINK_CONFLICT_ACCOUNT_HAS_OTHER = "account_has_other_platform_account";

/**
 * A trailing `#<code>` and nothing after it. Anchored and length-exact so a
 * real hashtag never matches: `#launch` is 6 characters, and the alphabet is
 * the urlsafe-base64 one the API mints from.
 */
const TRAILING_LINK_CODE = new RegExp(
  `\\s*#([A-Za-z0-9_-]{${LINK_CODE_LENGTH}})\\s*$`,
);

/** Splits a trailing ` #<code>` off a message, or null when there isn't one. */
export function parseTrailingLinkCode(message: string): ParsedLinkCode | null {
  const match = TRAILING_LINK_CODE.exec(message);
  if (!match) return null;
  return { code: match[1], text: message.slice(0, match.index).trim() };
}

/**
 * The WhatsApp/iMessage half of one-tap linking: the user's own first message
 * carries the code, so it must be redeemed and stripped before anything else
 * looks at the text.
 *
 * Returns the text to continue through the normal chat flow, or null when there
 * is nothing left to handle: an unlinked sender's code was redeemed (GAIA's
 * first contact IS the reply) or refused (they already have the explanation),
 * or a linked sender's message was nothing but a stray code.
 */
export async function consumeInboundLinkCode(
  args: InboundLinkCodeArgs,
): Promise<string | null> {
  const parsed = parseTrailingLinkCode(args.text);
  if (!parsed) return args.text;

  // Only redeem for a sender we know is unlinked. An already-linked one is
  // re-sending the prewritten message, and an `unknown` is a failed check —
  // redeeming there spends a stale code and answers a real message with "that
  // link has expired". Both drop the code and let the rest through.
  if ((await args.linkState()) === "unlinked") {
    // Either outcome ends the turn. A success has already delivered the whole
    // first contact, so running the stripped text on top of it would answer the
    // user's own prewritten opener a second time; a failure has already told
    // them why, and chatting past it strands them mid-explanation.
    await redeemLinkCode(
      args.gaia,
      args.platform,
      args.platformUserId,
      parsed.code,
      args.target,
      args.profile,
      parsed.text,
    );
    return null;
  }

  return parsed.text || null;
}

/** Sent when the code is stale, already used, the handle belongs elsewhere, or
 * the redemption broke on our side. */
export function buildLinkCodeFailureMessage(
  reason: LinkCodeFailure,
  frontendUrl: string,
): string {
  if (reason === "failed") {
    return (
      "**Something went wrong on our end**\n\n" +
      "Nothing to fix on your side. Tap the link again in a moment.\n" +
      `${frontendUrl}/onboarding`
    );
  }
  if (reason === "plan") {
    return (
      "**This platform is part of GAIA Pro**\n\n" +
      "Subscribe and tap the link again.\n" +
      `${frontendUrl}/pricing`
    );
  }
  if (reason === "account-has-other") {
    return (
      "**Your account already has a different account connected here**\n\n" +
      "Disconnect the one you have in settings, then tap the link again.\n" +
      `${frontendUrl}/settings?section=linked-accounts`
    );
  }
  if (reason === "conflict") {
    return (
      "**This account is already connected to someone else**\n\n" +
      "Disconnect it from the other GAIA account first, then try again.\n" +
      `${frontendUrl}/settings?section=linked-accounts`
    );
  }
  return (
    "**That link has expired**\n\n" +
    "Head back to GAIA and pick your platform again — it only takes a tap.\n" +
    `${frontendUrl}/onboarding`
  );
}

/**
 * Reads the API's stated reason. A 409 covers two opposite conflicts, and a 429
 * means "needs Pro" only when it says so — a real rate limit there would
 * otherwise tell people to subscribe over a limit they just have to wait out.
 *
 * Anything else — a 500, a timeout, a socket that hung up — is ours, and is
 * told as such rather than dressed up as an expired code the user would go and
 * re-mint for nothing.
 */
function classifyLinkFailure(error: unknown): LinkCodeFailure {
  if (!(error instanceof GaiaApiError)) return "failed";
  if (error.status === 429) {
    return error.reason.plan_required ? "plan" : "expired";
  }
  if (error.status === 409) {
    return error.reason.code === LINK_CONFLICT_ACCOUNT_HAS_OTHER
      ? "account-has-other"
      : "conflict";
  }
  if (error.status === 400) return "expired";
  return "failed";
}

/**
 * Redeems `code` for `platformUserId`.
 *
 * The API composes GAIA's whole first contact and delivers it itself on the
 * outbound queue the moment the link completes, so this normally sends nothing
 * on success. No model turn runs: the opener turn used to skip the per-pick
 * lines and lose the links, and the one message a new user is guaranteed to
 * read does not get to be unreliable. When that delivery failed the API hands
 * the bubbles back and they are sent from here — nothing else will.
 *
 * ``firstMessage`` is what the user typed over the WhatsApp/iMessage prefill,
 * with the code stripped: their real opening turn, which the API stores as
 * theirs. A Telegram deep link carries none, and none is invented.
 *
 * Returns true once the link is in. Every failure is answered and returns
 * false — never a stack trace, and never silence: a user the code can act on
 * (expired/used code, handle already linked elsewhere) is told what to do, and
 * a failure of ours is named as ours. Nothing is rethrown, because this is the
 * user's first-ever message and the adapters above only log.
 */
export async function redeemLinkCode(
  gaia: GaiaClient,
  platform: PlatformName,
  platformUserId: string,
  code: string,
  target: MessageTarget,
  profile?: { username?: string; displayName?: string },
  firstMessage?: string,
): Promise<boolean> {
  return withWideEvent(
    "link_code_redemption",
    {
      platform,
      component: "link-codes",
      user_hash: hashLogIdentifier(platformUserId),
    },
    async () => {
      try {
        const redeemed = await gaia.redeemLinkCode(
          platform,
          platformUserId,
          code,
          profile,
          firstMessage,
        );
        wideLog.audit("platform_linked_via_code", {
          user_hash: hashLogIdentifier(platformUserId),
        });
        // The outbound publish is never retried, so bubbles the queue refused
        // are sent from here or not at all — and the one message a new user is
        // guaranteed to read is the whole point of the link.
        if (!redeemed.delivered) {
          for (const bubble of redeemed.firstContact) {
            await target.send(bubble);
          }
        }
        wideLog.set({
          link_result: "linked",
          first_contact_sent_by_bot: !redeemed.delivered,
        });
        return true;
      } catch (error: unknown) {
        const reason = classifyLinkFailure(error);
        // "rejected" is a refusal the user caused; ours is its own result, so a
        // dashboard cannot read our outage as people presenting bad codes.
        wideLog.set({
          link_result: reason === "failed" ? "failed" : "rejected",
          reason,
        });
        if (reason === "failed") {
          // Nothing is rethrown: the adapters' last-resort handlers only log,
          // so a propagated error answered the user's first-ever message with
          // silence. The failure is recorded here instead.
          wideLog.error(
            "platform_link_code_failed",
            { user_hash: hashLogIdentifier(platformUserId) },
            error,
          );
        } else {
          wideLog.audit("platform_link_code_rejected", {
            user_hash: hashLogIdentifier(platformUserId),
            reason,
          });
        }
        await target.send(
          buildLinkCodeFailureMessage(reason, gaia.getFrontendUrl()),
        );
        return false;
      }
    },
  );
}
