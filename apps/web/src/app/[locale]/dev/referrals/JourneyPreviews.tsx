"use client";

import {
  Invite,
  InviteComposer,
} from "@/features/onboarding/components/stages/Invite";
import { FriendsList } from "@/features/referrals/components/FriendsList";
import { PostPaymentReferral } from "@/features/referrals/components/PostPaymentShareCard";
import { WorkflowMeterSection } from "@/features/referrals/components/page/WorkflowMeterSection";
import { ReferralsSettings } from "@/features/referrals/components/ReferralsSettings";
import { SentWithGaiaToggle } from "@/features/referrals/components/SentWithGaiaToggle";
import { SuggestionsList } from "@/features/referrals/components/SuggestionsList";
import { FixtureQueries } from "./FixtureQueries";
import { Frame } from "./Frame";
import {
  FIXTURE_FRIEND_STATES,
  FIXTURE_SUGGESTION_PHASES,
  FIXTURE_WORKFLOW_METERS,
  fixtureSender,
} from "./fixtures";
import type { PreviewProps } from "./GalleryPreview";
import { proAccount, useHeldInvites } from "./previewState";

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
