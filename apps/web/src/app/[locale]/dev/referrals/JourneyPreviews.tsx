"use client";

import type { ReferralCopyVariant } from "@shared/api/generated";
import { useEffect } from "react";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import {
  Invite,
  InviteComposer,
} from "@/features/onboarding/components/stages/Invite";
import { ChatReferralCard } from "@/features/referrals/components/ChatReferralCard";
import { FriendsList } from "@/features/referrals/components/FriendsList";
import { PostPaymentReferral } from "@/features/referrals/components/PostPaymentShareCard";
import { WorkflowMeterSection } from "@/features/referrals/components/page/WorkflowMeterSection";
import { ReferralsSettings } from "@/features/referrals/components/ReferralsSettings";
import { SentWithGaiaToggle } from "@/features/referrals/components/SentWithGaiaToggle";
import { SidebarReferralSlot } from "@/features/referrals/components/SidebarReferralPromo";
import { SuggestionsList } from "@/features/referrals/components/SuggestionsList";
import { WeeklyStatsChatCard } from "@/features/referrals/components/WeeklyStatsChatCard";
import {
  type InvitePhase,
  useInviteStore,
} from "@/features/referrals/stores/inviteStore";
import { type FixtureAccount, FixtureQueries } from "./FixtureQueries";
import { Frame } from "./Frame";
import {
  FIXTURE_CONTACTS,
  FIXTURE_FRIEND_STATES,
  FIXTURE_ME,
  FIXTURE_SUGGESTION_PHASES,
  FIXTURE_WEEKLY,
  FIXTURE_WORKFLOW_METERS,
  fixtureSender,
} from "./fixtures";
import type { PreviewProps } from "./GalleryPreview";

const proAccount = (copyVariant: ReferralCopyVariant): FixtureAccount => ({
  plan: "pro",
  me: { ...FIXTURE_ME.mid, copy_variant: copyVariant },
  sentWithGaia: false,
  weekly: FIXTURE_WEEKLY.mid,
  contacts: FIXTURE_CONTACTS.map((contact) => contact.metadata),
});

/** Parks each address in its fixture phase; no timers run, so nothing is ever sent. */
function useHeldInvites(
  entries: { email: string; phase: InvitePhase | null }[],
) {
  useEffect(() => {
    useInviteStore.setState((state) => {
      const invites = { ...state.invites };
      for (const { email, phase } of entries) {
        if (phase) invites[email] = phase;
      }
      return { invites };
    });
  }, [entries]);
}

export function OnboardingPreview({ copyVariant }: PreviewProps) {
  return (
    <FixtureQueries key={copyVariant} account={proAccount(copyVariant)}>
      <div className="flex flex-col gap-10">
        <Frame label="Payment success page: post-payment share card">
          <div className="w-full max-w-sm">
            <PostPaymentReferral />
          </div>
        </Frame>
        <Frame label="Onboarding invite stage, with its Continue composer">
          <div className="flex flex-col gap-6 rounded-3xl bg-zinc-950 py-10">
            <Invite />
            {/* The stage's own Continue only advances the onboarding reducer. */}
            <InviteComposer dispatch={() => undefined} />
          </div>
        </Frame>
      </div>
    </FixtureQueries>
  );
}

const SUGGESTION_INVITES = FIXTURE_SUGGESTION_PHASES.map(
  ({ suggestion, phase }) => ({ email: suggestion.email, phase }),
);

export function SettingsStatesPreview({ copyVariant }: PreviewProps) {
  useHeldInvites(SUGGESTION_INVITES);
  return (
    <div className="flex flex-col gap-10">
      <Frame label="Not subscribed: the whole Settings tab for a free user">
        <FixtureQueries
          key={copyVariant}
          account={{ ...proAccount(copyVariant), plan: "free" }}
        >
          <ReferralsSettings />
        </FixtureQueries>
      </Frame>
      <Frame label="Sent with GAIA toggle: on">
        <FixtureQueries
          key={copyVariant}
          account={{ ...proAccount(copyVariant), sentWithGaia: true }}
        >
          <div className="w-full max-w-2xl">
            <SentWithGaiaToggle />
          </div>
        </FixtureQueries>
      </Frame>
      <div className="flex w-full max-w-2xl flex-col gap-10">
        <Frame label="Friends: none yet">
          <FriendsList friends={[]} />
        </Frame>
        <Frame label="Friends: pending, earned, and one with no first name">
          <FriendsList friends={Object.values(FIXTURE_FRIEND_STATES)} />
        </Frame>
        {Object.entries(FIXTURE_WORKFLOW_METERS).map(
          ([state, workflowMeter]) => (
            <Frame key={state} label={`From your workflows: ${state}`}>
              <WorkflowMeterSection meter={workflowMeter} />
            </Frame>
          ),
        )}
        <Frame label="Suggestions: undo window, sent, cannot invite, opted out">
          <SuggestionsList
            suggestions={FIXTURE_SUGGESTION_PHASES.map((s) => s.suggestion)}
            send={fixtureSender}
          />
        </Frame>
      </div>
    </div>
  );
}

const CONTACT_INVITES = FIXTURE_CONTACTS.map(({ metadata, phase }) => ({
  email: metadata.url,
  phase,
}));

export function NudgesPreview({ copyVariant }: PreviewProps) {
  useHeldInvites(CONTACT_INVITES);
  return (
    <FixtureQueries key={copyVariant} account={proAccount(copyVariant)}>
      <div className="flex flex-col gap-10">
        <Frame label="Sidebar promo">
          <div className="w-64 rounded-2xl bg-zinc-950 p-2">
            <SidebarReferralSlot />
          </div>
        </Frame>
        <Frame label="In-chat card under a finished reply">
          <ChatReferralCard turnId="gallery-turn" />
        </Frame>
        <Frame label="Weekly stats card on a new chat (Mondays)">
          <WeeklyStatsChatCard className="max-w-xl" />
        </Frame>
        <Frame label="Email hover card in a reply: hover an address">
          <ul className="flex w-full max-w-xl flex-col gap-3 rounded-2xl bg-zinc-800 p-4">
            {FIXTURE_CONTACTS.map(({ label, metadata }) => (
              <li key={metadata.url} className="text-sm text-zinc-300">
                {label}:{" "}
                <CustomAnchor href={metadata.url}>{metadata.url}</CustomAnchor>
              </li>
            ))}
          </ul>
        </Frame>
      </div>
    </FixtureQueries>
  );
}
