import type {
  ReferralCopyVariant,
  ReferralInviteSurface,
} from "@shared/api/generated";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { api } from "@/lib/api/typed";

export const referralsApi = {
  /** A non-subscriber's and a switched-off program's 403s are states the referral surfaces render, not failures. */
  getMe: () =>
    api.get("/api/v1/referrals/me", {
      silent: true,
      expectedErrorCodes: [
        API_ERROR_CODES.REFERRAL_SUBSCRIPTION_REQUIRED,
        API_ERROR_CODES.REFERRALS_DISABLED,
      ],
    }),

  /** The caller's own gift from whoever referred them; null when none is owed. */
  getGift: () => api.get("/api/v1/referrals/gift", { silent: true }),

  getSuggestions: () =>
    api.get("/api/v1/referrals/suggestions", { silent: true }),

  /** Browser-only: the response sets the first-touch attribution cookie on the API host. */
  resolve: (code: string, landingVariant: ReferralCopyVariant) =>
    api.get("/api/v1/referrals/resolve/{code}", {
      path: { code },
      query: { landing_variant: landingVariant },
      silent: true,
    }),

  sendInvites: (emails: string[], surface: ReferralInviteSurface) =>
    api.post("/api/v1/referrals/invites", { body: { emails, surface } }),
};
