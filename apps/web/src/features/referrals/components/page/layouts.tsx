"use client";

import type {
  ReferralCopyVariant,
  ReferralLayoutVariant,
  ReferralMeResponse,
  ReferralSuggestion,
} from "@shared/api/generated";
import { REFERRAL_COPY } from "../../referralCopy";
import type { InviteSender } from "../../stores/inviteStore";
import { offerPrices } from "../../utils/offerPrices";
import { EarnedSummary } from "../EarnedSummary";
import { MilestoneBar } from "../MilestoneBar";
import { SuggestionsList } from "../SuggestionsList";
import { ShareLinkPanel } from "../share/ShareLinkPanel";
import { FriendsSection } from "./FriendsSection";
import { GiftTicket } from "./GiftTicket";
import { ReferralHero } from "./ReferralHero";

export interface ReferralLayoutProps {
  me: ReferralMeResponse;
  suggestions: ReferralSuggestion[];
  send: InviteSender;
  copyVariant: ReferralCopyVariant;
}

function TicketLayout({
  me,
  suggestions,
  send,
  copyVariant,
}: ReferralLayoutProps) {
  const copy = REFERRAL_COPY[copyVariant];
  const prices = offerPrices(me.offer);
  return (
    <>
      <ReferralHero title={copy.page.title} body={copy.page.body(prices)} />
      <div className="flex flex-col gap-3">
        <GiftTicket
          prices={prices}
          url={me.share_link}
          footer={<MilestoneBar paidFriends={me.months_earned} />}
        />
        <ShareLinkPanel
          url={me.share_link}
          prices={prices}
          copyVariant={copyVariant}
          surface="page"
        />
      </div>
      <FriendsSection
        friends={me.friends}
        accessory={<EarnedSummary me={me} />}
      />
      <SuggestionsList suggestions={suggestions} send={send} />
    </>
  );
}

function ProgressLayout({
  me,
  suggestions,
  send,
  copyVariant,
}: ReferralLayoutProps) {
  const copy = REFERRAL_COPY[copyVariant];
  const prices = offerPrices(me.offer);
  return (
    <>
      <section className="rounded-3xl bg-zinc-800 p-6">
        <MilestoneBar paidFriends={me.months_earned} />
      </section>
      <section className="flex flex-col gap-4">
        <ReferralHero title={copy.page.title} body={copy.page.body(prices)} />
        <ShareLinkPanel
          url={me.share_link}
          prices={prices}
          copyVariant={copyVariant}
          surface="page"
        />
      </section>
      <FriendsSection
        friends={me.friends}
        accessory={<EarnedSummary me={me} />}
      />
      <SuggestionsList suggestions={suggestions} send={send} />
    </>
  );
}

function MinimalLayout({
  me,
  suggestions,
  send,
  copyVariant,
}: ReferralLayoutProps) {
  const copy = REFERRAL_COPY[copyVariant];
  const prices = offerPrices(me.offer);
  return (
    <>
      <section className="flex flex-col gap-4">
        <ReferralHero
          compact
          title={copy.page.title}
          body={copy.page.body(prices)}
        />
        <ShareLinkPanel
          url={me.share_link}
          prices={prices}
          copyVariant={copyVariant}
          surface="page"
        />
      </section>
      <FriendsSection
        friends={me.friends}
        accessory={<EarnedSummary me={me} withMonths />}
      />
      <SuggestionsList suggestions={suggestions} send={send} />
    </>
  );
}

const LAYOUTS: Record<
  ReferralLayoutVariant,
  (props: ReferralLayoutProps) => React.JSX.Element
> = {
  ticket: TicketLayout,
  progress: ProgressLayout,
  minimal: MinimalLayout,
};

interface ReferralsViewProps extends ReferralLayoutProps {
  layout: ReferralLayoutVariant;
}

export function ReferralsView({ layout, ...props }: ReferralsViewProps) {
  const Layout = LAYOUTS[layout];
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 pb-8">
      <Layout {...props} />
    </div>
  );
}
