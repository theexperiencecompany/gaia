import type { RegistrationPolicy } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

/** Self-host instance administration: accounts, invite links, sign-up policy. */
export const membersApi = {
  getOverview: () => api.get("/api/v1/members", { silent: true }),

  createInvite: () =>
    api.post("/api/v1/members/invites", {
      errorMessage: "Could not create an invite link",
    }),

  revokeInvite: (inviteId: string) =>
    api.delete("/api/v1/members/invites/{invite_id}", {
      path: { invite_id: inviteId },
      successMessage: "Invite link revoked",
      errorMessage: "Could not revoke this invite link",
    }),

  setRegistrationPolicy: (policy: RegistrationPolicy) =>
    api.put("/api/v1/members/registration", {
      body: { policy },
      errorMessage: "Could not change who can sign up",
    }),

  removeMember: (userId: string) =>
    api.delete("/api/v1/members/{user_id}", {
      path: { user_id: userId },
      successMessage: "Member removed",
      errorMessage: "Could not remove this member",
    }),
};
