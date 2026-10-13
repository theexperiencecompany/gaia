import type {
  ReferralCopyVariant,
  ReferralInviteSurface,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export const referralsApi = {
  /** 403 REFERRAL_SUBSCRIPTION_REQUIRED for a non-subscriber; silent so the page can say it kindly. */
  getMe: () => api.get("/api/v1/referrals/me", { silent: true }),

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

  /** Browser-only, logged out: credits the workflow's creator through the same first-touch cookie. */
  creditWorkflow: (workflowId: string) =>
    api.post("/api/v1/referrals/workflow-credit/{workflow_id}", {
      path: { workflow_id: workflowId },
      silent: true,
    }),

  getWeeklyCard: () =>
    api.get("/api/v1/referrals/weekly-card", { silent: true }),
};
