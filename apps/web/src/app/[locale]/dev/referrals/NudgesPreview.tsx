"use client";

import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import { ChatReferralCard } from "@/features/referrals/components/ChatReferralCard";
import { SidebarReferralSlot } from "@/features/referrals/components/SidebarReferralPromo";
import { WeeklyStatsChatCard } from "@/features/referrals/components/WeeklyStatsChatCard";
import { FixtureQueries } from "./FixtureQueries";
import { Frame } from "./Frame";
import { FIXTURE_CONTACTS } from "./fixtures";
import type { PreviewProps } from "./GalleryPreview";
import { proAccount, useHeldInvites } from "./previewState";

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
