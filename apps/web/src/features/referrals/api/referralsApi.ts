import type {
  ReferralCopyVariant,
  ReferralInviteSurface,
} from "@shared/api/generated";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { api } from "@/lib/api/typed";

/** The 403s a referrer-only route answers with: states the referral surfaces render, not failures. */
const NOT_A_REFERRER_CODES = [
  API_ERROR_CODES.REFERRAL_SUBSCRIPTION_REQUIRED,
  API_ERROR_CODES.REFERRALS_DISABLED,
] as const;

export const referralsApi = {
  getMe: () =>
    api.get("/api/v1/referrals/me", {
      silent: true,
      expectedErrorCodes: NOT_A_REFERRER_CODES,
    }),

  /** The caller's own gift from whoever referred them; null when none is owed. */
  getGift: () => api.get("/api/v1/referrals/gift", { silent: true }),

  /** Empty, not failed, while the program is switched off. */
  getSuggestions: () =>
    api.get("/api/v1/referrals/suggestions", {
      silent: true,
      expectedErrorCodes: [API_ERROR_CODES.REFERRALS_DISABLED],
    }),

  /** Browser-only: the response sets the first-touch attribution cookie on the API host. */
  resolve: (code: string, landingVariant: ReferralCopyVariant) =>
    api.get("/api/v1/referrals/resolve/{code}", {
      path: { code },
      query: { landing_variant: landingVariant },
      silent: true,
    }),

  sendInvites: (emails: string[], surface: ReferralInviteSurface) =>
    api.post("/api/v1/referrals/invites", { body: { emails, surface } }),

  /** Spends this week's referral nudge when show is true; ask only at the moment the card would appear. */
  claimChatCard: () =>
    api.post("/api/v1/referrals/nudges/chat-card", { silent: true }),

  dismissChatCard: () =>
    api.post("/api/v1/referrals/nudges/chat-card/dismissal", { silent: true }),
};
