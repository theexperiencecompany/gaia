import type { ReferralCopyVariant } from "@shared/api/generated";
import { useEffect } from "react";
import {
  type InvitePhase,
  useInviteStore,
} from "@/features/referrals/stores/inviteStore";
import type { FixtureAccount } from "./FixtureQueries";
import { FIXTURE_CONTACTS, FIXTURE_ME, FIXTURE_WEEKLY } from "./fixtures";

export const proAccount = (
  copyVariant: ReferralCopyVariant,
): FixtureAccount => ({
  plan: "pro",
  me: { ...FIXTURE_ME.mid, copy_variant: copyVariant },
  sentWithGaia: false,
  weekly: FIXTURE_WEEKLY.mid,
  contacts: FIXTURE_CONTACTS.map((contact) => contact.metadata),
});

/** Parks each address in its fixture phase while the preview is open; no timers run, so nothing is ever sent. */
export function useHeldInvites(
  entries: { email: string; phase: InvitePhase | null }[],
) {
  useEffect(() => {
    const fixtureEmails = new Set(entries.map(({ email }) => email));
    const withoutFixtures = (invites: Record<string, InvitePhase>) =>
      Object.fromEntries(
        Object.entries(invites).filter(([email]) => !fixtureEmails.has(email)),
      );
    useInviteStore.setState((state) => {
      const invites = withoutFixtures(state.invites);
      for (const { email, phase } of entries) {
        if (phase) invites[email] = phase;
      }
      return { invites };
    });
    // The store is the app's own, so leaving the preview takes the fixture phases back out.
    return () =>
      useInviteStore.setState((state) => ({
        invites: withoutFixtures(state.invites),
      }));
  }, [entries]);
}
